"""메일 발송 구조(AC25, C11, C12, C13, C15).

흐름: 코드를 요청하면 **챌린지와 같은 쓰기 트랜잭션에서** 발송 요청을 `mail_outbox`에 쌓고(C13), 같은 프로세스의
작업 스레드가 표를 읽어 `Mailer`로 보낸다. 메일이 늦거나 실패해도 코드는 DB에 남아 있어 교수가 알려 줄 수 있다(C12).

- 메일 본문과 코드는 표에 쓰지 않는다. 보낼 때 챌린지에서 코드를 다시 계산한다.
- 발송이 끝나거나(성공) 포기하면(실패, 낡은 코드) 수신 주소를 비운다(C11).
- 서비스의 초당 호출 상한을 넘지 않게 초당 `rate_per_sec`건 이하로 보낸다(실패한 시도도 센다).
- 한 번의 처리에서 보낼 몫은 **동시에** 보낸다(최대 `max_parallel`통). 한 통씩 차례로 보내면 서비스 응답이 0.3초일 때
  초당 3통쯤밖에 못 보내 200명 강좌에서 1분이 넘게 걸린다(T036 측정). DB를 읽고 쓰는 일은 작업 스레드 하나가 차례로 하고,
  동시에 하는 것은 서비스 호출뿐이다.
- 실패는 지수 대기(5초, 10초, 20초, …, 상한 5분) 뒤 다시 시도한다. 응답이 알려 준 대기 시간이 더 길면 따른다.
- 메일은 **최소 한 번** 보낸다. 보낸 직후 표에 기록하기 전에 멈추면 같은 코드 메일이 한 번 더 갈 수 있는데,
  같은 챌린지의 같은 코드라 해롭지 않다.
- 실제 발송은 `app.resend.ResendMailer`(T035). 설정이 없으면 `OutboxMailer`가 메모리에만 모은다(개발·테스트).
"""

import logging
import sqlite3
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Protocol

from app.challenges import compute_code
from app.clock import Clock
from app.db import transaction

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 8
BACKOFF_BASE_SECONDS = 5
BACKOFF_CAP_SECONDS = 300
CODE_MAIL = "code"
THREAD_NAME = "mail-worker"


@dataclass(frozen=True)
class MailMessage:
    to: str
    subject: str
    text: str
    # 같은 발송 요청이면 같은 값. 다시 보내도 서비스가 알아보고 한 번만 보낸다(최소 한 번 발송의 중복 방지)
    idempotency_key: str | None = None


class MailError(Exception):
    """발송에 실패했다. retryable이 False면 다시 시도하지 않는다(예: 주소가 올바르지 않음).
    retry_after는 서비스가 알려 준 대기 시간(초, 예: 429 응답)이다."""

    def __init__(self, message: str, retryable: bool = True, retry_after: float | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class Mailer(Protocol):
    """메일 한 통을 보낸다. 실패하면 MailError를 던진다(C15: 서비스를 바꿔도 이 구현 하나만 바꾼다)."""

    def send(self, message: MailMessage) -> None: ...


class OutboxMailer:
    """개발·테스트용. 보내지 않고 `sent`에 모은다."""

    def __init__(self) -> None:
        self.sent: list[MailMessage] = []
        self._lock = threading.Lock()

    def send(self, message: MailMessage) -> None:
        with self._lock:
            self.sent.append(message)


# --- 쌓기 ---------------------------------------------------------------------------------------------


def enqueue_code_mail(
    db: sqlite3.Connection, classroom_id: int, challenge_id: int, to_email: str, now: datetime
) -> int:
    """코드 메일 발송 요청을 쌓는다. 호출하는 쪽이 연 쓰기 트랜잭션 안에서 부른다(챌린지와 함께 저장되거나 함께 취소된다)."""
    cursor = db.execute(
        "INSERT INTO mail_outbox(classroom_id, kind, to_email, body_ref, next_try_at, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (classroom_id, CODE_MAIL, to_email, challenge_id, now.isoformat(), now.isoformat()),
    )
    return cursor.lastrowid


def render_code_mail(secret: str, classroom_name: str, to_email: str, challenge: sqlite3.Row) -> MailMessage:
    """코드 메일. 짧고 정확하게 쓴다. 받는 사람의 주소와 닉네임은 본문에 넣지 않는다."""
    code = compute_code(secret, challenge["id"], challenge["nonce"])
    text = (
        f"{classroom_name} 입장 인증 코드: {code}\n"
        "\n"
        "이 코드는 10분 동안 쓸 수 있고, 코드를 요청한 기기(브라우저)에서만 입력할 수 있습니다.\n"
        "직접 요청하지 않았다면 이 메일은 무시해 주세요."
    )
    return MailMessage(to=to_email, subject=f"인증 코드 {code} ({classroom_name})", text=text)


# --- 보내기 --------------------------------------------------------------------------------------------


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


class MailWorker:
    """`mail_outbox`의 보낼 차례가 된 요청을 보낸다. `process_due()`가 한 번의 처리이고, 스레드는 이를 되풀이한다."""

    def __init__(
        self,
        open_db: Callable[[], sqlite3.Connection],
        mailer: Mailer,
        secret: str,
        clock: Clock,
        rate_per_sec: int = 8,
        max_parallel: int = 8,
    ) -> None:
        self._open_db = open_db
        self._mailer = mailer
        self._secret = secret
        self._clock = clock
        self._rate = max(1, rate_per_sec)
        self._parallel = max(1, max_parallel)  # 동시에 보내는 최대 통수
        self._window: deque[datetime] = deque()  # 최근 1초 안에 서비스를 부른 시각
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # 한 번의 처리 -----------------------------------------------------------------------------

    def process_due(self) -> int:
        """보낼 차례가 된 요청을 상한 안에서 보낸다. 서비스를 부른 횟수(성공과 실패)를 돌려준다."""
        now = self._clock.now()
        while self._window and now - self._window[0] >= timedelta(seconds=1):
            self._window.popleft()
        budget = self._rate - len(self._window)
        if budget <= 0:
            return 0
        db = self._open_db()
        try:
            rows = db.execute("SELECT * FROM mail_outbox WHERE status = 'pending' ORDER BY id").fetchall()
            batch: list[tuple[sqlite3.Row, MailMessage]] = []
            for row in rows:  # 오래된 요청부터 이번 몫을 고른다
                if len(batch) >= budget:
                    break
                if _at(row["next_try_at"]) > now:
                    continue
                message = self._compose(db, row, now)
                if message is None:  # 낡은 코드: 보내지 않고 포기한다(몫을 쓰지 않는다)
                    self._finish(db, row, "failed", now)
                    continue
                batch.append((row, message))
            if not batch:
                return 0
            self._window.extend([now] * len(batch))
            outcomes = self._send_all([message for _, message in batch])
            for (row, _), error in zip(batch, outcomes, strict=True):  # 결과 기록은 다시 차례로
                self._record(db, row, now, error)
            return len(batch)
        finally:
            db.close()

    def _send_one(self, message: MailMessage) -> BaseException | None:
        try:
            self._mailer.send(message)
        except Exception as err:  # noqa: BLE001 한 통의 뜻밖의 오류가 다른 통을 막지 않게 결과로 돌려준다(_record가 로그와 재시도)
            return err
        return None

    def _send_all(self, messages: list[MailMessage]) -> list[BaseException | None]:
        """서비스 호출만 동시에 한다. 결과는 보낸 목록과 같은 순서로 돌려준다."""
        if len(messages) == 1 or self._parallel == 1:
            return [self._send_one(m) for m in messages]
        workers = min(self._parallel, len(messages))
        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="mail-send") as pool:
            return list(pool.map(self._send_one, messages))

    def _record(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime, error: BaseException | None) -> None:
        attempts = row["attempts"] + 1
        if error is None:
            self._finish(db, row, "sent", now, attempts)
        elif isinstance(error, MailError):
            self._retry_or_give_up(db, row, now, attempts, error.retryable, error.retry_after)
        else:
            log.error("메일을 보내다 뜻밖의 오류가 났습니다. 다시 시도합니다(요청 %s)", row["id"], exc_info=error)
            self._retry_or_give_up(db, row, now, attempts, True, None)

    def _compose(self, db: sqlite3.Connection, row: sqlite3.Row, now: datetime) -> MailMessage | None:
        challenge = db.execute("SELECT * FROM login_challenges WHERE id = ?", (row["body_ref"],)).fetchone()
        if challenge is None or challenge["status"] != "active" or now >= _at(challenge["expires_at"]):
            return None  # 새 코드를 받았거나, 이미 입장했거나, 만료되었다
        classroom = db.execute("SELECT name FROM classrooms WHERE id = ?", (row["classroom_id"],)).fetchone()
        message = render_code_mail(self._secret, classroom["name"], row["to_email"], challenge)
        return replace(message, idempotency_key=f"mail-outbox/{row['id']}")

    def _finish(
        self, db: sqlite3.Connection, row: sqlite3.Row, status: str, now: datetime, attempts: int | None = None
    ) -> None:
        """끝난 요청(성공 또는 포기)은 수신 주소를 비운다(C11)."""
        with transaction(db):
            db.execute(
                "UPDATE mail_outbox SET status = ?, to_email = NULL, attempts = ?, sent_at = ? WHERE id = ?",
                (status, attempts if attempts is not None else row["attempts"], now.isoformat() if status == "sent" else None, row["id"]),
            )

    def _retry_or_give_up(
        self,
        db: sqlite3.Connection,
        row: sqlite3.Row,
        now: datetime,
        attempts: int,
        retryable: bool,
        retry_after: float | None,
    ) -> None:
        if not retryable or attempts >= MAX_ATTEMPTS:
            self._finish(db, row, "failed", now, attempts)
            return
        wait = min(BACKOFF_BASE_SECONDS * 2 ** (attempts - 1), BACKOFF_CAP_SECONDS)
        if retry_after:
            wait = max(wait, retry_after)
        with transaction(db):
            db.execute(
                "UPDATE mail_outbox SET attempts = ?, next_try_at = ? WHERE id = ?",
                (attempts, (now + timedelta(seconds=wait)).isoformat(), row["id"]),
            )

    # 스레드 ---------------------------------------------------------------------------------------

    def start(self) -> None:
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name=THREAD_NAME, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                calls = self.process_due()
            except Exception:  # DB가 잠겼거나 일시 오류여도 스레드는 계속 돈다
                log.exception("메일 작업 스레드의 처리 중 오류가 났습니다. 잠시 뒤 다시 시도합니다.")
                calls = 0
            self._stop.wait(0.2 if calls else 0.5)
