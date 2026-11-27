"""003 T003: 출석의 계산 함수(코드, 받는 칸, 틀린 코드 제한기, 상태). DB와 시계 없이 본다."""

import hashlib
import hmac
import threading
from datetime import UTC, datetime, timedelta

import pytest

from app.attendance_core import (
    LOCK_AFTER,
    SLOT_SECONDS,
    Attempt,
    AttendanceStatus,
    WrongCodeLimiter,
    attendance_status,
    code_accepted,
    compute_attendance_code,
    slot_bounds,
    slot_of,
)

SECRET = "test-secret"
NONCE = "0123456789abcdef0123456789abcdef"
T0 = datetime(2026, 3, 2, 9, 0, 0, tzinfo=UTC)  # 15초 경계(유닉스 시각이 15로 나누어떨어진다)


def code(slot, window_id=1, nonce=NONCE, secret=SECRET):
    return compute_attendance_code(secret, window_id, nonce, slot)


# --- 칸 -------------------------------------------------------------------------------


def test_slots_are_15_seconds_on_the_unix_epoch_grid():
    assert SLOT_SECONDS == 15
    s = slot_of(T0)
    assert s == int(T0.timestamp()) // 15
    assert slot_of(T0 + timedelta(seconds=14, microseconds=999_999)) == s
    assert slot_of(T0 + timedelta(seconds=15)) == s + 1
    assert slot_of(T0 - timedelta(microseconds=1)) == s - 1
    start, end = slot_bounds(s)
    assert (start, end) == (T0, T0 + timedelta(seconds=15))
    assert start.tzinfo is not None


def test_slot_needs_an_aware_time():
    with pytest.raises(ValueError):
        slot_of(datetime(2026, 3, 2, 9))


# --- 코드 -----------------------------------------------------------------------------


def test_same_inputs_give_the_same_six_digit_code():
    s = slot_of(T0)
    assert code(s) == code(s)
    assert len(code(s)) == 6 and code(s).isdigit()


def test_code_matches_the_documented_derivation():
    # plan: HMAC-SHA256(서버 비밀값, "attendance:{창}:{난수}:{칸}")의 앞 8바이트 % 100만, 6자리 0 채움
    s = slot_of(T0)
    digest = hmac.new(SECRET.encode(), f"attendance:1:{NONCE}:{s}".encode(), hashlib.sha256).digest()
    assert code(s) == str(int.from_bytes(digest[:8], "big") % 1_000_000).zfill(6)


def test_codes_are_zero_padded():
    # 많은 칸 중 앞자리가 0인 코드가 있고, 그래도 6자리다
    codes = [code(s) for s in range(2000)]
    assert all(len(c) == 6 and c.isdigit() for c in codes)
    assert any(c.startswith("0") for c in codes)
    assert any(c[0] != "0" for c in codes)  # 5자리 코드에 0을 붙인 것만 나오지 않는다


def test_code_changes_with_slot_window_nonce_and_secret():
    s = slot_of(T0)
    base = code(s)
    assert code(s + 1) != base
    assert code(s, window_id=2) != base
    assert code(s, nonce="f" * 32) != base  # 다시 받기는 새 난수라 새 코드(AC5)
    assert code(s, secret="other") != base


def test_code_needs_the_server_secret():
    with pytest.raises(ValueError, match="SERVER_SECRET"):
        compute_attendance_code("", 1, NONCE, slot_of(T0))


# --- 받는 칸 ----------------------------------------------------------------------------


def test_current_and_previous_codes_are_accepted():
    s = slot_of(T0)
    now = T0 + timedelta(seconds=3)
    assert code_accepted(SECRET, 1, NONCE, code(s), now)
    assert code_accepted(SECRET, 1, NONCE, code(s - 1), now)  # 입력하는 사이에 바뀌어도 된다


def test_older_and_future_codes_are_refused():
    s = slot_of(T0)
    now = T0 + timedelta(seconds=3)
    for other in (s - 2, s - 3, s + 1):
        typed = code(other)
        if typed in (code(s), code(s - 1)):
            continue  # 우연히 같은 값이면 건너뛴다(100만분의 1)
        assert not code_accepted(SECRET, 1, NONCE, typed, now)


def test_codes_of_another_window_are_refused():
    s = slot_of(T0)
    assert not code_accepted(SECRET, 2, NONCE, code(s, window_id=1), T0)


@pytest.mark.parametrize("typed", ["", "12345", "1234567", "12a456", " 123456", "１２３４５６", None, 123456])
def test_malformed_input_is_refused(typed):
    assert not code_accepted(SECRET, 1, NONCE, typed, T0)


# --- 틀린 코드 제한기 --------------------------------------------------------------------


def test_fifth_wrong_code_within_a_minute_locks_with_remaining_seconds():
    assert LOCK_AFTER == 5
    limiter = WrongCodeLimiter()
    key = (1, 7)
    for i in range(4):
        assert limiter.record_wrong(key, T0 + timedelta(seconds=i)) == 0
        assert limiter.locked_for(key, T0 + timedelta(seconds=i)) == 0
    # 5번째(4초 시점): 첫 틀림(0초) + 60초까지 막는다
    assert limiter.record_wrong(key, T0 + timedelta(seconds=4)) == 56
    assert limiter.locked_for(key, T0 + timedelta(seconds=10)) == 50
    assert limiter.locked_for(key, T0 + timedelta(seconds=59, milliseconds=500)) == 1  # 올림
    assert limiter.locked_for(key, T0 + timedelta(seconds=60)) == 0  # 60초가 지나면 풀린다


def test_wrong_codes_spread_over_more_than_a_minute_do_not_lock():
    limiter = WrongCodeLimiter()
    key = (1, 7)
    for i in range(10):
        assert limiter.record_wrong(key, T0 + timedelta(seconds=16 * i)) == 0


def test_counts_are_per_classroom_and_membership():
    limiter = WrongCodeLimiter()
    for _ in range(5):
        limiter.record_wrong((1, 7), T0)
    assert limiter.locked_for((1, 7), T0) > 0
    assert limiter.locked_for((1, 8), T0) == 0  # 다른 학생
    assert limiter.locked_for((2, 7), T0) == 0  # 다른 강좌


def test_lock_runs_from_the_fifth_latest_wrong_code():
    limiter = WrongCodeLimiter()
    key = (1, 7)
    for i in range(5):
        limiter.record_wrong(key, T0 + timedelta(seconds=i))
    # 막혀 있는 동안 더 틀려도(라우트는 먼저 막힘을 보지만) 기준은 최근 다섯 번 중 가장 오래된 것: 1초 + 60
    assert limiter.record_wrong(key, T0 + timedelta(seconds=5)) == 56
    assert limiter.locked_for(key, T0 + timedelta(seconds=60)) == 1


def test_lock_after_expiry_needs_five_wrong_codes_within_a_minute_again():
    limiter = WrongCodeLimiter()
    key = (1, 7)
    for _ in range(5):
        limiter.record_wrong(key, T0)
    later = T0 + timedelta(seconds=61)
    assert limiter.locked_for(key, later) == 0
    assert limiter.record_wrong(key, later) == 0  # 앞의 다섯은 1분 밖이다


def fill(limiter, n=100):
    for m in range(n):
        limiter.record_wrong((1, m), T0)


def test_checking_a_lock_forgets_entries_older_than_a_minute():
    limiter = WrongCodeLimiter()
    fill(limiter)
    limiter.locked_for((9, 9), T0 + timedelta(seconds=60))  # 정확히 60초 된 기록도 빠진다
    assert limiter.tracked() == 0


def test_recording_forgets_entries_older_than_a_minute():
    limiter = WrongCodeLimiter()
    fill(limiter)
    limiter.record_wrong((1, 999), T0 + timedelta(minutes=2))
    assert limiter.tracked() == 1


def test_attempt_forgets_entries_older_than_a_minute():
    limiter = WrongCodeLimiter()
    fill(limiter)
    limiter.attempt((1, 999), T0 + timedelta(minutes=2), lambda: True)
    assert limiter.tracked() == 0


def test_attempt_checks_the_code_only_when_not_locked():
    limiter = WrongCodeLimiter()
    key = (1, 7)
    assert limiter.attempt(key, T0, lambda: True) == Attempt(ok=True, locked=False, seconds=0)
    for i in range(4):
        assert limiter.attempt(key, T0 + timedelta(seconds=i), lambda: False) == Attempt(False, False, 0)
    assert limiter.attempt(key, T0 + timedelta(seconds=4), lambda: False) == Attempt(False, False, 56)

    def must_not_run():
        raise AssertionError("막혀 있으면 코드를 보지 않는다")

    assert limiter.attempt(key, T0 + timedelta(seconds=10), must_not_run) == Attempt(False, True, 50)
    assert limiter.attempt(key, T0 + timedelta(seconds=61), lambda: True).ok  # 풀린 뒤에는 다시 본다


def test_parallel_attempts_cannot_get_past_the_limit():
    # 한 학생이 동시에 여러 번 보내도 코드를 보는 횟수는 5번까지다
    limiter = WrongCodeLimiter()
    key = (1, 7)
    checked = []
    gate = threading.Barrier(30)

    def go():
        gate.wait()
        limiter.attempt(key, T0, lambda: checked.append(1) or False)

    threads = [threading.Thread(target=go) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert len(checked) == 5


def test_limiter_is_safe_across_threads():
    limiter = WrongCodeLimiter()
    key = (1, 7)
    threads = [threading.Thread(target=limiter.record_wrong, args=(key, T0)) for _ in range(50)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert limiter.locked_for(key, T0) == 60


# --- 상태 ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kinds", "expected"),
    [
        ([], AttendanceStatus.ABSENT),
        (["code"], AttendanceStatus.PRESENT),
        (["manual_present"], AttendanceStatus.MANUAL),
        (["request_approved"], AttendanceStatus.MANUAL),
        (["manual_absent"], AttendanceStatus.ABSENT),
        (["code", "manual_absent"], AttendanceStatus.ABSENT),  # 교수가 결석으로 바꿨다
        (["code", "manual_absent", "manual_present"], AttendanceStatus.MANUAL),  # 다시 출석으로 바꾸면 수기
        (["manual_present", "code"], AttendanceStatus.PRESENT),
        (["manual_absent", "request_approved"], AttendanceStatus.MANUAL),
    ],
)
def test_status_is_the_last_record(kinds, expected):
    assert attendance_status(kinds) is expected


def test_status_values_are_stable_strings():
    assert [s.value for s in AttendanceStatus] == ["present", "manual", "absent"]


def test_unknown_record_kind_is_an_error():
    with pytest.raises(ValueError):
        attendance_status(["late"])
