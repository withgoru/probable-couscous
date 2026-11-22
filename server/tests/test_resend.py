"""AC25, C12, C17(T035): Resend로 실제 메일을 보내는 `ResendMailer`.

진짜 Resend 대신 같은 모양으로 답하는 가짜 HTTP 서버로 확인한다(네트워크·계정 없이).
- 보내는 요청: POST /emails, Bearer 인증, from·to·subject·text, 같은 발송 요청은 같은 Idempotency-Key(중복 발송 방지)
- 응답 처리: 2xx는 성공, 429·5xx·일부 409·연결 실패는 다시 시도, 그 밖의 4xx는 포기. 429의 retry-after를 따른다
- 초당 8건 상한(작업 스레드와 함께), API 키는 설정(환경 변수·.env)에서만 읽고 로그·오류·설정 출력에 남지 않는다
"""

import json
import logging
import threading
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from conftest import ORIGIN

from app.challenges import ensure_device, issue_challenge
from app.clock import ManualClock
from app.config import ConfigError, Settings, load_settings
from app.db import transaction
from app.mail import MailError, MailMessage, MailWorker, OutboxMailer, enqueue_code_mail
from app.main import create_app
from app.resend import ResendMailer, mailer_from_settings

KEY = "re_test_SECRET_key_123"
SENDER = "강의 도구 <no-reply@class.example.kr>"
START = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class FakeResend:
    """Resend처럼 답하는 가짜 서버. 정해 둔 응답(status, headers, body)을 차례로 내고, 받은 요청을 모두 기록한다."""

    def __init__(self):
        self.requests: list[dict] = []
        self.replies: list[tuple[int, dict, dict]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(length)
                fake.requests.append(
                    {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": json.loads(raw or b"{}")}
                )
                status, headers, body = fake.replies.pop(0) if fake.replies else (200, {}, {"id": f"email-{len(fake.requests)}"})
                data = json.dumps(body).encode()
                self.send_response(status)
                for k, v in headers.items():
                    self.send_header(k, v)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, *_args):  # 테스트 출력을 어지럽히지 않는다
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"
        self.thread = threading.Thread(target=self.server.serve_forever, kwargs={"poll_interval": 0.05}, daemon=True)
        self.thread.start()

    def reply(self, status, body=None, headers=None):
        self.replies.append((status, headers or {}, body or {}))

    def close(self):
        self.server.shutdown()
        self.server.server_close()


@pytest.fixture
def fake():
    f = FakeResend()
    yield f
    f.close()


def mailer(fake, **kw):
    return ResendMailer(KEY, SENDER, base_url=fake.url, timeout=2, **kw)


MESSAGE = MailMessage(to="kim@x.kr", subject="인증 코드 123456 (웹)", text="웹 입장 인증 코드: 123456", idempotency_key="mail-outbox/7")


# --- 보내는 요청 --------------------------------------------------------------------------------------------------------


def test_a_mail_is_sent_as_one_post_to_emails_with_bearer_auth(fake):
    mailer(fake).send(MESSAGE)
    (req,) = fake.requests
    assert req["path"] == "/emails"
    assert req["headers"]["authorization"] == f"Bearer {KEY}"
    assert req["headers"]["content-type"].startswith("application/json")
    assert req["body"] == {"from": SENDER, "to": ["kim@x.kr"], "subject": MESSAGE.subject, "text": MESSAGE.text}


def test_the_same_outbox_row_always_sends_the_same_idempotency_key(fake):
    # 작업 스레드는 '최소 한 번' 보낸다. 같은 발송 요청을 다시 보내도 Resend가 같은 키로 알아보고 한 번만 보낸다
    mailer(fake).send(MESSAGE)
    mailer(fake).send(MESSAGE)
    assert [r["headers"]["idempotency-key"] for r in fake.requests] == ["mail-outbox/7", "mail-outbox/7"]


def test_without_a_key_no_idempotency_header_is_sent(fake):
    mailer(fake).send(MailMessage(to="a@x.kr", subject="s", text="t"))
    assert "idempotency-key" not in fake.requests[0]["headers"]


def test_the_user_agent_names_only_the_service(fake):
    mailer(fake).send(MESSAGE)
    agent = fake.requests[0]["headers"].get("user-agent", "")
    assert agent.startswith("classroom-server") and "@" not in agent


# --- 응답 처리 ----------------------------------------------------------------------------------------------------------


def test_a_429_is_retried_after_the_time_the_service_asks(fake):
    fake.reply(429, {"name": "rate_limit_exceeded", "message": "Too many requests"}, {"retry-after": "3", "ratelimit-reset": "1"})
    with pytest.raises(MailError) as err:
        mailer(fake).send(MESSAGE)
    assert err.value.retryable and err.value.retry_after == 3


def test_a_429_without_retry_after_uses_ratelimit_reset(fake):
    fake.reply(429, {"name": "rate_limit_exceeded"}, {"ratelimit-reset": "2"})
    with pytest.raises(MailError) as err:
        mailer(fake).send(MESSAGE)
    assert err.value.retryable and err.value.retry_after == 2


@pytest.mark.parametrize("status,name", [(500, "application_error"), (502, None), (503, "service_unavailable"), (504, None)])
def test_server_errors_are_retried(fake, status, name):
    fake.reply(status, {"name": name} if name else {})
    with pytest.raises(MailError) as err:
        mailer(fake).send(MESSAGE)
    assert err.value.retryable


@pytest.mark.parametrize("name", ["concurrent_idempotent_requests", "resource_locked"])
def test_409s_that_say_try_later_are_retried(fake, name):
    fake.reply(409, {"name": name})
    with pytest.raises(MailError) as err:
        mailer(fake).send(MESSAGE)
    assert err.value.retryable


@pytest.mark.parametrize(
    "status,name",
    [
        (400, "validation_error"),
        (401, "missing_api_key"),
        (403, "validation_error"),  # 인증하지 않은 발신 도메인 등
        (409, "invalid_idempotent_request"),
        (422, "missing_required_field"),
    ],
)
def test_requests_the_service_will_never_accept_are_given_up(fake, status, name):
    fake.reply(status, {"name": name, "message": "kim@x.kr is not allowed"})
    with pytest.raises(MailError) as err:
        mailer(fake).send(MESSAGE)
    assert not err.value.retryable


def test_a_service_that_cannot_be_reached_is_retried():
    unreachable = ResendMailer(KEY, SENDER, base_url="http://127.0.0.1:9", timeout=1)  # 아무도 듣지 않는 포트
    with pytest.raises(MailError) as err:
        unreachable.send(MESSAGE)
    assert err.value.retryable


def test_a_slow_service_times_out_and_is_retried(fake, monkeypatch):
    import time as _time

    real = fake.server.RequestHandlerClass.do_POST

    def slow(self):
        _time.sleep(1.5)
        real(self)

    monkeypatch.setattr(fake.server.RequestHandlerClass, "do_POST", slow)
    with pytest.raises(MailError) as err:
        ResendMailer(KEY, SENDER, base_url=fake.url, timeout=0.5).send(MESSAGE)
    assert err.value.retryable


# --- 비밀 값 (C17, C11) --------------------------------------------------------------------------------------------------


def test_the_key_and_the_address_never_reach_the_logs_or_the_error(fake, caplog):
    caplog.set_level(logging.DEBUG)
    for status in (401, 500, 429):
        fake.reply(status, {"name": "x", "message": f"bad key {KEY} for kim@x.kr"})
        with pytest.raises(MailError) as err:
            mailer(fake).send(MESSAGE)
        assert KEY not in str(err.value) and "kim@x.kr" not in str(err.value)
    assert KEY not in caplog.text
    assert "kim@x.kr" not in caplog.text  # 서비스 안내에 주소가 섞여 와도 남기지 않는다(C11)


def test_the_key_is_not_in_the_mailers_or_the_settings_printed_form():
    m = ResendMailer(KEY, SENDER)
    assert KEY not in repr(m) and KEY not in str(m)
    s = Settings(resend_api_key=KEY, github_client_secret="gh-secret", server_secret="srv-secret")
    for secret in (KEY, "gh-secret", "srv-secret"):
        assert secret not in repr(s)


def test_the_key_comes_from_the_environment_or_dotenv(tmp_path):
    env = tmp_path / ".env"
    env.write_text("RESEND_API_KEY=from-dotenv\nMAIL_FROM=a@b.kr\n", encoding="utf-8")
    assert load_settings(env={}, dotenv_path=env).resend_api_key == "from-dotenv"
    assert load_settings(env={"RESEND_API_KEY": "from-env"}, dotenv_path=env).resend_api_key == "from-env"


# --- 설정에서 고르기 -------------------------------------------------------------------------------------------------------


def test_with_a_key_and_a_sender_the_app_uses_resend():
    m = mailer_from_settings(Settings(resend_api_key=KEY, mail_from=SENDER))
    assert isinstance(m, ResendMailer)


def test_without_a_key_the_app_keeps_mail_in_memory():
    assert isinstance(mailer_from_settings(Settings()), OutboxMailer)


def test_a_key_without_a_sender_is_a_clear_configuration_error():
    with pytest.raises(ConfigError) as err:
        mailer_from_settings(Settings(resend_api_key=KEY))
    assert "MAIL_FROM" in str(err.value) and "인증한 도메인" in str(err.value)  # 무엇을 어떻게 고치는지 알려 준다
    assert KEY not in str(err.value)


def test_create_app_picks_the_mailer_from_the_settings(world):
    from dataclasses import replace

    app = create_app(replace(world.settings, resend_api_key=KEY, mail_from=SENDER), start_mail_worker=False)
    assert isinstance(app.state.mailer, ResendMailer)


# --- 작업 스레드와 함께: 초당 8건, 다시 시도, 중복 방지 ---------------------------------------------------------------------


@pytest.fixture
def queued(world):
    """코드 메일 발송 요청 n개를 쌓는 도구."""
    db = world.db()
    cid = world.client("kim").post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    clock = ManualClock(START)
    device = ensure_device(db, None, clock.now()).device_id

    def make(n):
        ids = []
        for i in range(n):
            email = f"s{i}@x.kr"
            challenge = issue_challenge(db, "secret", cid, email, device, clock.now())
            with transaction(db):
                ids.append(enqueue_code_mail(db, cid, challenge, email, clock.now()))
        return ids

    make.db, make.clock = db, clock
    return make


def test_with_the_worker_at_most_8_mails_go_out_per_second(world, fake, queued):
    queued(20)
    w = MailWorker(world.db, mailer(fake), "secret", queued.clock, rate_per_sec=8)
    assert w.process_due() == 8 and len(fake.requests) == 8
    assert w.process_due() == 0  # 같은 1초 안에는 더 보내지 않는다
    queued.clock.advance(seconds=1)
    assert w.process_due() == 8
    queued.clock.advance(seconds=1)
    assert w.process_due() == 4 and len(fake.requests) == 20
    assert {r["body"]["to"][0] for r in fake.requests} == {f"s{i}@x.kr" for i in range(20)}


def test_a_rate_limited_mail_waits_as_asked_then_goes_out_with_the_same_key(world, fake, queued):
    (outbox_id,) = queued(1)
    fake.reply(429, {"name": "rate_limit_exceeded"}, {"retry-after": "30"})
    w = MailWorker(world.db, mailer(fake), "secret", queued.clock, rate_per_sec=8)
    w.process_due()
    row = queued.db.execute("SELECT * FROM mail_outbox WHERE id = ?", (outbox_id,)).fetchone()
    assert row["status"] == "pending" and row["attempts"] == 1
    queued.clock.advance(seconds=29)
    assert w.process_due() == 0  # 서비스가 말한 30초가 지나지 않았다
    queued.clock.advance(seconds=1)
    w.process_due()
    row = queued.db.execute("SELECT * FROM mail_outbox WHERE id = ?", (outbox_id,)).fetchone()
    assert row["status"] == "sent" and row["to_email"] is None
    assert [r["headers"]["idempotency-key"] for r in fake.requests] == [f"mail-outbox/{outbox_id}"] * 2


def test_a_mail_the_service_refuses_is_given_up_and_the_address_is_cleared(world, fake, queued):
    (outbox_id,) = queued(1)
    fake.reply(403, {"name": "validation_error", "message": "domain not verified"})
    MailWorker(world.db, mailer(fake), "secret", queued.clock).process_due()
    row = queued.db.execute("SELECT * FROM mail_outbox WHERE id = ?", (outbox_id,)).fetchone()
    assert row["status"] == "failed" and row["to_email"] is None and len(fake.requests) == 1
