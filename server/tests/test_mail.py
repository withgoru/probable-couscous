"""AC25의 기반(C11, C12, C13, C15): 메일 발송 구조. 요청은 DB 표에 먼저 쓰고, 같은 프로세스의 작업 스레드가 보낸다.

시간은 가짜 시계, 발송은 가짜 Mailer로 확인한다.
"""

import logging
import threading
import time
from datetime import UTC, datetime, timedelta

import pytest
from conftest import ORIGIN

from app.challenges import code_for, ensure_device, issue_challenge, verify_code
from app.clock import ManualClock
from app.db import transaction
from app.mail import (
    MAX_ATTEMPTS,
    MailError,
    MailMessage,
    MailWorker,
    OutboxMailer,
    enqueue_code_mail,
)
from app.main import create_app

SECRET = "test-secret"
START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class Env:
    pass


@pytest.fixture
def env(world):
    e = Env()
    e.cid = world.client("kim").post("/api/classrooms", json={"name": "웹 프로그래밍"}, headers=ORIGIN).json()["id"]
    e.world = world
    e.db = world.db()
    e.clock = ManualClock(START)
    e.mailer = OutboxMailer()
    e.device = ensure_device(e.db, None, e.clock.now()).device_id
    e.n = 0
    return e


def worker(e, mailer=None, rate=8):
    return MailWorker(e.world.db, mailer or e.mailer, SECRET, e.clock, rate_per_sec=rate)


def queue(e, email=None, when=None):
    """학생이 코드를 요청한 상태: 챌린지를 만들고 같은 쓰기 트랜잭션에서 발송 요청을 쌓는다."""
    e.n += 1
    email = email or f"s{e.n}@x.kr"
    cid = issue_challenge(e.db, SECRET, e.cid, email, e.device, e.clock.now())
    with transaction(e.db):
        outbox_id = enqueue_code_mail(e.db, e.cid, cid, email, when or e.clock.now())
    return outbox_id, cid, email


def outbox(e, outbox_id):
    return e.db.execute("SELECT * FROM mail_outbox WHERE id = ?", (outbox_id,)).fetchone()


class Scripted:
    """차례로 정해 둔 결과를 내는 가짜 Mailer. 값이 예외면 던지고 None이면 보낸 것으로 친다."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[MailMessage] = []

    def send(self, message):
        self.calls.append(message)
        result = self.results.pop(0) if self.results else None
        if isinstance(result, BaseException):
            raise result


# --- 먼저 DB에 쓴다 (C13) -----------------------------------------------------------------------


def test_the_request_is_written_to_the_table_before_anything_is_sent(env):
    oid, cid, email = queue(env)
    r = outbox(env, oid)
    assert (r["classroom_id"], r["kind"], r["body_ref"], r["to_email"]) == (env.cid, "code", cid, email)
    assert r["status"] == "pending" and r["attempts"] == 0 and r["sent_at"] is None
    assert r["created_at"] == START.isoformat() and r["next_try_at"] == START.isoformat()
    assert env.mailer.sent == []  # 쌓기만 했고 아직 보내지 않았다


def test_the_request_holds_no_code_and_no_mail_body(env):
    oid, cid, _ = queue(env)
    code = code_for(env.db, SECRET, cid)
    r = outbox(env, oid)
    assert code not in [str(v) for v in tuple(r)]
    assert "body" not in r.keys() and "subject" not in r.keys()  # noqa: SIM118 (Row의 in은 값을 본다)


def test_enqueue_joins_the_callers_transaction_so_a_failed_request_leaves_no_mail(env):
    cid = issue_challenge(env.db, SECRET, env.cid, "a@x.kr", env.device, env.clock.now())
    with pytest.raises(RuntimeError), transaction(env.db):
        enqueue_code_mail(env.db, env.cid, cid, "a@x.kr", env.clock.now())
        raise RuntimeError("뒤의 쓰기가 실패")
    assert env.db.execute("SELECT COUNT(*) FROM mail_outbox").fetchone()[0] == 0


def test_pending_mail_survives_a_restart_and_a_new_worker_sends_it(env):
    oid, _, _ = queue(env)
    assert worker(env).process_due() == 1  # 같은 DB 파일을 새로 열어도 남아 있다(작업자마다 연결을 새로 연다)
    assert outbox(env, oid)["status"] == "sent"


# --- 보내기 -------------------------------------------------------------------------------------


def test_a_code_mail_goes_out_with_the_code_the_classroom_and_the_rules(env):
    _, cid, email = queue(env)
    assert worker(env).process_due() == 1
    (msg,) = env.mailer.sent
    code = code_for(env.db, SECRET, cid)
    assert msg.to == email
    assert code in msg.text and code in msg.subject
    assert "웹 프로그래밍" in msg.text
    assert "10분" in msg.text  # 만료
    assert "요청한 기기" in msg.text  # 요청한 기기에서만 입력
    assert "직접 요청하지 않았다면" in msg.text


def test_the_mail_never_contains_other_personal_data_or_a_nickname(env):
    _, _, email = queue(env)
    worker(env).process_due()
    msg = env.mailer.sent[0]
    assert email not in msg.text and email not in msg.subject  # 수신 주소는 받는 사람 칸에만


def test_after_sending_the_row_is_marked_sent_and_the_address_is_cleared(env):
    oid, _, _ = queue(env)
    env.clock.advance(seconds=3)
    worker(env).process_due()
    r = outbox(env, oid)
    assert r["status"] == "sent" and r["to_email"] is None  # C11
    assert r["sent_at"] == env.clock.now().isoformat() and r["attempts"] == 1


@pytest.mark.constitution
def test_c11_no_address_stays_in_the_mail_table_after_sending_or_giving_up(env):
    sent, _, _ = queue(env, "sent@x.kr")
    stale, _, _ = queue(env, "stale@x.kr")
    dead, _, _ = queue(env, "dead@x.kr")
    env.db.execute("UPDATE login_challenges SET status = 'superseded' WHERE id = (SELECT body_ref FROM mail_outbox WHERE id = ?)", (stale,))
    mailer = Scripted(None, *[MailError("거부", retryable=False)])
    worker(env, mailer).process_due()
    rows = env.db.execute("SELECT to_email, status FROM mail_outbox").fetchall()
    assert {r["status"] for r in rows} == {"sent", "failed"}
    assert all(r["to_email"] is None for r in rows)
    assert outbox(env, sent)["status"] == "sent" and outbox(env, dead)["status"] == "failed"


def test_rows_not_due_yet_are_left_alone_and_rows_go_in_order(env):
    later, _, _ = queue(env, "later@x.kr", when=START + timedelta(seconds=30))
    queue(env, "first@x.kr")
    queue(env, "second@x.kr")
    worker(env).process_due()
    assert [m.to for m in env.mailer.sent] == ["first@x.kr", "second@x.kr"]
    assert outbox(env, later)["status"] == "pending"
    env.clock.advance(seconds=30)
    worker(env).process_due()
    assert env.mailer.sent[-1].to == "later@x.kr"


def test_a_sent_row_is_never_sent_twice(env):
    queue(env)
    w = worker(env)
    w.process_due()
    env.clock.advance(seconds=10)
    assert w.process_due() == 0 and len(env.mailer.sent) == 1


# --- 초당 8건 이하 ------------------------------------------------------------------------------------


def test_at_most_eight_mails_go_out_in_any_second(env):
    for _ in range(20):
        queue(env)
    stamps: list[datetime] = []

    class Timed(OutboxMailer):
        def send(self, message):
            stamps.append(env.clock.now())
            super().send(message)

    w = worker(env, Timed())
    sent_per_pass = []
    for _ in range(14):  # 0.5초 간격으로 7초
        sent_per_pass.append(w.process_due())
        env.clock.advance(seconds=0.5)
    assert sum(sent_per_pass) == 20
    for t in stamps:  # 어떤 1초 구간을 잡아도 8건 이하
        assert sum(1 for s in stamps if t <= s < t + timedelta(seconds=1)) <= 8
    assert sent_per_pass[:3] == [8, 0, 8]  # 첫 순간 8건, 같은 1초 안에는 더 보내지 않고, 딱 1초 뒤에 다시 8건


def test_the_rate_comes_from_the_setting(env):
    for _ in range(10):
        queue(env)
    assert worker(env, rate=3).process_due() == 3


def test_failed_attempts_also_use_the_rate_budget(env):
    # 실패해도 서비스에 요청을 보낸 것이라 상한에 센다(429를 더 부르지 않게)
    for _ in range(12):
        queue(env)
    mailer = Scripted(*[MailError("실패")] * 12)
    assert worker(env, mailer).process_due() == 8
    assert len(mailer.calls) == 8


# --- 실패와 재시도 ---------------------------------------------------------------------------------------


def test_a_failure_keeps_the_row_pending_and_waits_exponentially(env):
    oid, _, _ = queue(env)
    mailer = Scripted(*[MailError("일시 오류")] * 4, None)
    w = worker(env, mailer)
    waits = []
    for _ in range(4):
        w.process_due()
        r = outbox(env, oid)
        assert r["status"] == "pending" and r["to_email"] is not None
        waits.append((datetime.fromisoformat(r["next_try_at"]) - env.clock.now()).total_seconds())
        # 기다리는 동안에는 다시 보내지 않는다
        env.clock.advance(seconds=waits[-1] - 1)
        calls = len(mailer.calls)
        w.process_due()
        assert len(mailer.calls) == calls
        env.clock.advance(seconds=1)
    assert waits == [5, 10, 20, 40]
    w.process_due()
    assert outbox(env, oid)["status"] == "sent"
    assert outbox(env, oid)["attempts"] == 5


def test_the_wait_is_capped(env):
    oid, _, _ = queue(env)
    env.db.execute("UPDATE mail_outbox SET attempts = ? WHERE id = ?", (MAX_ATTEMPTS - 2, oid))
    worker(env, Scripted(MailError("x"))).process_due()
    wait = (datetime.fromisoformat(outbox(env, oid)["next_try_at"]) - env.clock.now()).total_seconds()
    assert wait == 300  # 5초 x 2의 거듭제곱이 상한(5분)을 넘으면 상한에서 멈춘다


def test_a_retry_after_from_the_service_is_respected(env):
    oid, _, _ = queue(env)
    worker(env, Scripted(MailError("429", retry_after=90))).process_due()
    wait = (datetime.fromisoformat(outbox(env, oid)["next_try_at"]) - env.clock.now()).total_seconds()
    assert wait >= 90


def test_a_failure_that_cannot_be_retried_gives_up_at_once(env):
    oid, _, _ = queue(env)
    w = worker(env, Scripted(MailError("주소가 올바르지 않습니다", retryable=False)))
    w.process_due()
    r = outbox(env, oid)
    assert r["status"] == "failed" and r["to_email"] is None and r["attempts"] == 1
    assert r["sent_at"] is None  # 보내지 못한 요청에는 보낸 시각이 없다
    env.clock.advance(hours=1)
    assert w.process_due() == 0


def test_after_the_last_attempt_it_gives_up_and_clears_the_address(env):
    oid, cid, _ = queue(env)
    # 코드는 10분이면 낡아서 보내지 않는다. 여기서는 포기 규칙만 보려고 만료를 먼 미래로 둔다
    env.db.execute("UPDATE login_challenges SET expires_at = ? WHERE id = ?", ((START + timedelta(days=1)).isoformat(), cid))
    mailer = Scripted(*[MailError("계속 실패")] * (MAX_ATTEMPTS + 3))
    w = worker(env, mailer)
    for _ in range(MAX_ATTEMPTS + 2):
        w.process_due()
        env.clock.advance(minutes=10)
    r = outbox(env, oid)
    assert r["status"] == "failed" and r["to_email"] is None and r["attempts"] == MAX_ATTEMPTS
    assert len(mailer.calls) == MAX_ATTEMPTS == 8  # 최대 8번 시도한다


def test_an_unexpected_error_in_the_mailer_does_not_stop_the_worker_or_other_mail(env):
    bad, _, _ = queue(env, "bad@x.kr")
    good, _, _ = queue(env, "good@x.kr")
    worker(env, Scripted(RuntimeError("뜻밖의 오류"))).process_due()
    assert outbox(env, bad)["status"] == "pending"  # 다시 시도한다
    assert outbox(env, good)["status"] == "sent"


def test_a_code_that_is_no_longer_valid_is_not_mailed(env):
    # 새 코드를 받았거나, 이미 입장했거나, 만료된 뒤에 낡은 코드 메일을 보내지 않는다
    superseded, _, _ = queue(env, "same@x.kr")
    env.clock.advance(seconds=60)
    issue_challenge(env.db, SECRET, env.cid, "same@x.kr", env.device, env.clock.now())  # c1은 superseded
    used, c2, _ = queue(env, "used@x.kr")
    verify_code(env.db, SECRET, env.cid, "used@x.kr", env.device, code_for(env.db, SECRET, c2), env.clock.now())
    expired, _, _ = queue(env, "old@x.kr")
    env.clock.advance(minutes=11)
    mailer = Scripted()
    worker(env, mailer).process_due()
    assert mailer.calls == []
    assert {outbox(env, i)["status"] for i in (superseded, used, expired)} == {"failed"}


# --- 작업 스레드 ----------------------------------------------------------------------------------------


def test_the_background_thread_sends_pending_mail_and_stops_promptly(env):
    oid, _, _ = queue(env)
    w = worker(env)
    w.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and outbox(env, oid)["status"] != "sent":
            time.sleep(0.05)
        assert outbox(env, oid)["status"] == "sent"
    finally:
        began = time.time()
        w.stop()
    assert time.time() - began < 2
    assert not any(t.name == "mail-worker" and t.is_alive() for t in threading.enumerate())


def test_mail_queued_while_the_thread_is_running_goes_out_within_a_second_or_two(env):
    w = worker(env)
    w.start()
    try:
        time.sleep(0.3)  # 스레드가 한 번 돌고 쉬는 중
        oid, _, _ = queue(env)
        deadline = time.time() + 2
        while time.time() < deadline and outbox(env, oid)["status"] != "sent":
            time.sleep(0.05)
        assert outbox(env, oid)["status"] == "sent"
    finally:
        w.stop()


def test_start_twice_runs_one_thread_and_stop_is_safe_to_repeat(env):
    w = worker(env)
    w.start()
    w.start()
    assert sum(1 for t in threading.enumerate() if t.name == "mail-worker") == 1
    w.stop()
    w.stop()


def test_the_thread_survives_a_failing_pass(env, monkeypatch):
    oid, _, _ = queue(env)
    w = worker(env)
    real = w.process_due
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] == 1:
            raise sqlite_error()
        return real()

    monkeypatch.setattr(w, "process_due", flaky)
    w.start()
    try:
        deadline = time.time() + 5
        while time.time() < deadline and outbox(env, oid)["status"] != "sent":
            time.sleep(0.05)
        assert outbox(env, oid)["status"] == "sent"
    finally:
        w.stop()


def sqlite_error():
    import sqlite3

    return sqlite3.OperationalError("database is locked")


# --- 앱에 붙이기 -------------------------------------------------------------------------------------------


def test_the_outbox_mailer_collects_messages_safely_from_many_threads():
    mailer = OutboxMailer()
    threads = [threading.Thread(target=lambda: [mailer.send(MailMessage("a@x.kr", "s", "t")) for _ in range(50)]) for _ in range(8)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(mailer.sent) == 400


def test_the_app_has_a_mailer_and_a_worker_and_runs_the_thread_only_when_asked(world):
    assert world.app.state.mailer is not None and world.app.state.mail_worker is not None
    from fastapi.testclient import TestClient

    quiet = create_app(world.settings, clock=world.clock, start_mail_worker=False)
    with TestClient(quiet):
        assert not any(t.name == "mail-worker" for t in threading.enumerate())
    busy = create_app(world.settings, clock=world.clock)
    with TestClient(busy):
        assert any(t.name == "mail-worker" and t.is_alive() for t in threading.enumerate())
    assert not any(t.name == "mail-worker" and t.is_alive() for t in threading.enumerate())  # 앱이 닫히면 멈춘다


def test_the_app_warns_when_it_would_not_really_send_mail(world, caplog):
    from fastapi.testclient import TestClient

    app = create_app(world.settings, clock=world.clock, start_mail_worker=False)
    with caplog.at_level(logging.WARNING), TestClient(app):
        pass
    assert any("메일" in r.message and "보내지 않" in r.message for r in caplog.records)
