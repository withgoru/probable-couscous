"""AC30~AC33의 규칙(C7, C13): 인증 코드의 계산, 검증, 만료, 횟수, 재요청, 기기 묶음.

시간은 가짜 시계를 옮겨서 확인한다. 코드는 DB에 저장하지 않고 서버 비밀값과 챌린지의 난수에서 계산한다.
"""

import hmac
import re
import secrets
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ORIGIN

from app import challenges
from app.auth import hash_token
from app.challenges import (
    MAX_ATTEMPTS,
    Outcome,
    ResendTooSoon,
    code_for,
    compute_code,
    ensure_device,
    issue_challenge,
    resend_wait,
    verify_code,
)
from app.clock import ManualClock

SECRET = "test-secret"
EMAIL = "kim@x.kr"
START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def env(world):
    cid = world.client("kim").post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    db = world.db()
    clock = ManualClock(START)

    class Env:
        pass

    e = Env()
    e.db, e.cid, e.clock = db, cid, clock
    e.device = ensure_device(db, None, clock.now()).device_id
    e.other_device = ensure_device(db, None, clock.now()).device_id
    return e


def issue(e, email=EMAIL, device=None, cid=None):
    return issue_challenge(e.db, SECRET, cid or e.cid, email, device or e.device, e.clock.now())


def verify(e, code, email=EMAIL, device=None, cid=None):
    return verify_code(e.db, SECRET, cid or e.cid, email, device or e.device, code, e.clock.now())


def row(e, challenge_id):
    return e.db.execute("SELECT * FROM login_challenges WHERE id = ?", (challenge_id,)).fetchone()


# --- 코드 계산 ---------------------------------------------------------------------------


def test_the_code_is_six_digits_and_the_same_inputs_give_the_same_code():
    code = compute_code(SECRET, 7, "nonce-a")
    assert re.fullmatch(r"\d{6}", code)
    assert compute_code(SECRET, 7, "nonce-a") == code


def test_each_input_changes_the_code():
    base = compute_code(SECRET, 7, "nonce-a")
    codes = {base, compute_code("other-secret", 7, "nonce-a"), compute_code(SECRET, 8, "nonce-a"), compute_code(SECRET, 7, "nonce-b")}
    assert len(codes) == 4


def test_codes_are_always_exactly_six_digits_including_leading_zeros():
    codes = [compute_code(SECRET, i, f"n{i}") for i in range(3000)]
    assert all(re.fullmatch(r"\d{6}", c) for c in codes)
    assert any(c.startswith("0") for c in codes)  # 앞자리 0도 6자리로 맞춘다
    assert {c[0] for c in codes} == set("0123456789")  # 첫 자리도 0~9가 모두 나온다(6자리 전체를 쓴다)
    assert len(set(codes)) > 2900  # 거의 겹치지 않는다(100만 가지 중 3000개)


def test_an_empty_server_secret_is_refused_instead_of_making_guessable_codes():
    with pytest.raises(ValueError, match="SERVER_SECRET"):
        compute_code("", 1, "n")


def test_issuing_with_an_empty_secret_fails_before_leaving_a_challenge_behind(env):
    with pytest.raises(ValueError, match="SERVER_SECRET"):
        issue_challenge(env.db, "", env.cid, EMAIL, env.device, env.clock.now())
    assert env.db.execute("SELECT COUNT(*) FROM login_challenges").fetchone()[0] == 0


# --- 챌린지 만들기, 코드는 저장하지 않는다 -----------------------------------------------------


def test_issuing_records_a_challenge_without_any_code(env):
    cid = issue(env)
    r = row(env, cid)
    assert (r["classroom_id"], r["email_norm"], r["device_id"]) == (env.cid, EMAIL, env.device)
    assert r["status"] == "active" and r["attempts"] == 0 and r["used_at"] is None
    assert r["created_at"] == START.isoformat()
    assert r["expires_at"] == (START + timedelta(minutes=10)).isoformat()
    assert len(r["nonce"]) >= 32  # 128비트 난수
    assert "code" not in r.keys()  # noqa: SIM118 (sqlite3.Row의 in은 열 이름이 아니라 값을 본다)


def test_the_code_appears_nowhere_in_the_database(env):
    cid = issue(env)
    code = code_for(env.db, SECRET, cid)
    for table in [t[0] for t in env.db.execute("SELECT name FROM sqlite_master WHERE type='table'")]:
        for values in env.db.execute(f"SELECT * FROM {table}"):
            assert code not in [str(v) for v in values], f"{table}에 코드가 저장되어 있다"


def test_code_for_reproduces_the_code_for_the_professors_view(env):
    cid = issue(env)
    r = row(env, cid)
    assert code_for(env.db, SECRET, cid) == compute_code(SECRET, cid, r["nonce"])


def test_two_challenges_get_different_nonces(env):
    a = issue(env)
    env.clock.advance(seconds=60)
    b = issue(env)
    assert row(env, a)["nonce"] != row(env, b)["nonce"]


# --- 맞는 코드 ---------------------------------------------------------------------------------


def test_the_right_code_from_the_requesting_device_passes_and_marks_the_challenge_used(env):
    cid = issue(env)
    result = verify(env, code_for(env.db, SECRET, cid))
    assert result.outcome == Outcome.OK and result.challenge_id == cid
    r = row(env, cid)
    assert r["status"] == "used" and r["used_at"] == env.clock.now().isoformat()


def test_a_used_code_cannot_be_used_again(env):
    cid = issue(env)
    code = code_for(env.db, SECRET, cid)
    assert verify(env, code).outcome == Outcome.OK
    again = verify(env, code)
    assert again.outcome == Outcome.USED
    assert "다시 받아" in again.message


def test_surrounding_spaces_in_the_typed_code_are_ignored(env):
    cid = issue(env)
    assert verify(env, f" {code_for(env.db, SECRET, cid)} ").outcome == Outcome.OK


# --- AC30: 틀린 코드와 5회 -----------------------------------------------------------------------


def wrong_code(real):
    return "000000" if real != "000000" else "111111"


def test_wrong_codes_count_down_and_the_fifth_locks_the_code(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    bad = wrong_code(real)
    remaining = []
    for _ in range(MAX_ATTEMPTS - 1):
        r = verify(env, bad)
        assert r.outcome == Outcome.WRONG
        remaining.append(r.remaining)
    assert remaining == [4, 3, 2, 1]
    last = verify(env, bad)
    assert last.outcome == Outcome.LOCKED and last.message == "코드를 다시 받아 주세요."
    # 잠긴 뒤에는 맞는 코드도 받지 않는다
    assert verify(env, real).outcome == Outcome.LOCKED
    assert row(env, cid)["status"] == "expired"


def test_the_wrong_code_message_says_how_many_tries_are_left(env):
    cid = issue(env)
    r = verify(env, wrong_code(code_for(env.db, SECRET, cid)))
    assert r.message == "코드가 맞지 않습니다. 4번 더 입력할 수 있습니다."


def test_the_right_code_still_works_after_some_wrong_tries(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    for _ in range(4):
        verify(env, wrong_code(real))
    assert verify(env, real).outcome == Outcome.OK


def test_attempts_are_stored_in_the_database_so_a_restart_does_not_reset_them(env, world):
    cid = issue(env)
    verify(env, wrong_code(code_for(env.db, SECRET, cid)))
    assert world.db().execute("SELECT attempts FROM login_challenges WHERE id = ?", (cid,)).fetchone()[0] == 1


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "abcdef", "12 345", "１２３４５６", "12-456"])
def test_a_malformed_code_is_explained_and_does_not_use_up_a_try(env, typed):
    cid = issue(env)
    r = verify(env, typed)
    assert r.outcome == Outcome.BAD_FORMAT and "6자리" in r.message
    assert row(env, cid)["attempts"] == 0


# --- AC31: 10분 만료 --------------------------------------------------------------------------------


def test_the_code_works_until_ten_minutes_and_not_at_ten_minutes(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    env.clock.advance(minutes=9, seconds=59)
    assert verify(env, wrong_code(real)).outcome == Outcome.WRONG  # 아직 유효하다
    env.clock.advance(seconds=1)
    r = verify(env, real)
    assert r.outcome == Outcome.EXPIRED
    assert r.message == "코드가 만료되었습니다. 코드를 다시 받아 주세요."
    assert row(env, cid)["status"] == "expired"


def test_an_expired_code_stays_expired_even_if_the_clock_is_read_again(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    env.clock.advance(minutes=11)
    assert verify(env, real).outcome == Outcome.EXPIRED
    assert verify(env, real).outcome == Outcome.EXPIRED


def test_a_locked_code_says_get_a_new_code_not_expired(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    for _ in range(MAX_ATTEMPTS):
        verify(env, wrong_code(real))
    assert verify(env, real).message == "코드를 다시 받아 주세요."


# --- AC32: 다시 받기 -------------------------------------------------------------------------------


def test_asking_again_within_60_seconds_is_refused_with_the_seconds_left(env):
    issue(env)
    env.clock.advance(seconds=20)
    with pytest.raises(ResendTooSoon) as err:
        issue(env)
    assert err.value.seconds == 40
    assert "40초" in str(err.value)
    assert env.db.execute("SELECT COUNT(*) FROM login_challenges").fetchone()[0] == 1


def test_resend_wait_reports_the_seconds_and_rounds_up(env):
    assert resend_wait(env.db, env.cid, EMAIL, env.clock.now()) == 0  # 처음에는 기다릴 필요 없다
    issue(env)
    assert resend_wait(env.db, env.cid, EMAIL, env.clock.now()) == 60
    env.clock.advance(seconds=0.5)
    assert resend_wait(env.db, env.cid, EMAIL, env.clock.now()) == 60  # 59.5초 남음은 60초로 올림
    env.clock.advance(seconds=59.5)
    assert resend_wait(env.db, env.cid, EMAIL, env.clock.now()) == 0


def test_after_60_seconds_a_new_code_can_be_requested(env):
    issue(env)
    env.clock.advance(seconds=59)
    with pytest.raises(ResendTooSoon):
        issue(env)
    env.clock.advance(seconds=1)
    issue(env)


def test_the_wait_is_per_email_and_per_classroom(env, world):
    issue(env)
    issue(env, email="lee@x.kr")  # 다른 이메일은 기다리지 않는다
    other = world.client("lee").post("/api/classrooms", json={"name": "DB"}, headers=ORIGIN).json()["id"]
    issue(env, cid=other)  # 다른 강좌도 기다리지 않는다


def test_a_new_code_invalidates_the_earlier_one(env, monkeypatch):
    nonces = iter(["aaaa" * 8, "bbbb" * 8])
    monkeypatch.setattr(secrets, "token_hex", lambda *_: next(nonces))
    first = issue(env)
    old = code_for(env.db, SECRET, first)
    env.clock.advance(seconds=60)
    second = issue(env)
    new = code_for(env.db, SECRET, second)
    assert old != new
    assert row(env, first)["status"] == "superseded" and row(env, second)["status"] == "active"
    assert verify(env, old).outcome == Outcome.WRONG  # 이전 코드는 쓸 수 없다
    assert verify(env, new).outcome == Outcome.OK


def test_asking_again_after_a_code_was_used_still_waits_60_seconds(env):
    cid = issue(env)
    verify(env, code_for(env.db, SECRET, cid))
    with pytest.raises(ResendTooSoon):
        issue(env)


# --- AC33: 요청한 기기에서만 -----------------------------------------------------------------------


def test_another_device_gets_the_same_wrong_code_message_and_changes_nothing(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    other = verify(env, real, device=env.other_device)  # 맞는 코드를 다른 기기에서 입력
    assert other.outcome == Outcome.WRONG and other.message.startswith("코드가 맞지 않습니다")
    r = row(env, cid)
    assert r["attempts"] == 0 and r["status"] == "active"
    assert verify(env, real).outcome == Outcome.OK  # 요청한 기기의 코드는 그대로 쓸 수 있다


def test_another_devices_tries_never_use_up_the_requesting_devices_tries(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    for _ in range(MAX_ATTEMPTS * 3):
        assert verify(env, real, device=env.other_device).outcome == Outcome.WRONG
    assert row(env, cid)["attempts"] == 0
    assert verify(env, real).outcome == Outcome.OK


def test_another_device_cannot_tell_whether_a_code_exists_expired_or_used(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    messages = {verify(env, real, device=env.other_device).message}
    verify(env, real)  # 사용
    messages.add(verify(env, real, device=env.other_device).message)
    env.clock.advance(minutes=20)
    messages.add(verify(env, real, device=env.other_device).message)
    assert len(messages) == 1 and next(iter(messages)).startswith("코드가 맞지 않습니다")


def test_a_device_that_never_requested_a_code_gets_the_generic_message(env):
    r = verify(env, "123456")
    assert r.outcome == Outcome.WRONG and r.remaining is None and r.challenge_id is None
    assert r.message == "코드가 맞지 않습니다."


def test_a_code_is_only_good_for_its_own_classroom_and_email(env, world):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    other = world.client("lee").post("/api/classrooms", json={"name": "DB"}, headers=ORIGIN).json()["id"]
    assert verify(env, real, cid=other).outcome == Outcome.WRONG
    assert verify(env, real, email="lee@x.kr").outcome == Outcome.WRONG
    assert verify(env, real).outcome == Outcome.OK


def test_the_code_comparison_is_constant_time(env, monkeypatch):
    cid = issue(env)
    calls = []
    real_compare = hmac.compare_digest
    monkeypatch.setattr(challenges.hmac, "compare_digest", lambda a, b: (calls.append(1), real_compare(a, b))[1])
    verify(env, code_for(env.db, SECRET, cid))
    assert calls


# --- 기기 쿠키 ---------------------------------------------------------------------------------------


def test_a_new_device_gets_a_random_token_and_only_its_hash_is_stored(env):
    d = ensure_device(env.db, None, env.clock.now())
    assert d.is_new and len(d.token) >= 20
    stored = env.db.execute("SELECT * FROM devices WHERE id = ?", (d.device_id,)).fetchone()
    assert stored["token_hash"] == hash_token(d.token) and d.token not in stored["token_hash"]
    assert stored["first_seen_at"] == env.clock.now().isoformat()


def test_the_same_token_finds_the_same_device(env):
    d = ensure_device(env.db, None, env.clock.now())
    again = ensure_device(env.db, d.token, env.clock.now())
    assert again.device_id == d.device_id and not again.is_new and again.token == d.token


def test_a_forged_or_unknown_token_becomes_a_new_device_instead_of_an_old_one(env):
    d = ensure_device(env.db, None, env.clock.now())
    forged = ensure_device(env.db, "forged-token-0123456789", env.clock.now())
    assert forged.is_new and forged.device_id != d.device_id and forged.token != "forged-token-0123456789"


def test_clearing_browser_data_means_a_new_device_that_needs_its_own_code(env):
    cid = issue(env)
    real = code_for(env.db, SECRET, cid)
    fresh = ensure_device(env.db, None, env.clock.now())  # 쿠키가 지워진 같은 사람
    assert verify(env, real, device=fresh.device_id).outcome == Outcome.WRONG


@pytest.mark.constitution
def test_c7_no_table_has_a_column_that_could_hold_the_code(env):
    # 코드는 저장하지 않는다. 어느 표에도 코드, 해시된 코드, 평문 비밀번호로 보이는 열이 없다
    for (table,) in env.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall():
        for col in env.db.execute(f"PRAGMA table_info({table})").fetchall():  # noqa: S608
            assert not re.search(r"code|otp|passw", col["name"], re.I), f"{table}.{col['name']}"
