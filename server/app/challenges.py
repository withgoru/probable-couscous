"""학생 입장의 인증 코드: 계산, 검증, 만료, 횟수, 다시 받기, 기기 묶음(AC30~AC33, C7, C13).

- 코드는 6자리 숫자이고 **저장하지 않는다**. 서버 비밀값과 챌린지 번호·난수에서 계산한다(교수에게 보여 줄 때도 다시 계산).
  DB가 새도 코드를 복원할 수 없고, 교수는 필요할 때 같은 값을 계산해 볼 수 있다.
- 코드는 요청한 기기에서만 쓸 수 있다. 다른 기기가 입력하면 일반 오류이고 요청한 기기의 코드와 횟수는 그대로다.
- 상태(횟수, 만료, 사용)는 모두 DB에 쓴다. 서버를 다시 시작해도 남는다(C13).
- 이 모듈은 이메일을 `email_norm`으로만 받고, 명단이 아닌 곳에 개인정보를 쓰지 않는다(C7).
"""

import hashlib
import hmac
import math
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from app.auth import hash_token
from app.db import transaction

DEVICE_COOKIE = "device"
CODE_DIGITS = 6
CODE_LIFETIME = timedelta(minutes=10)
MAX_ATTEMPTS = 5
RESEND_INTERVAL = timedelta(seconds=60)

GENERIC_WRONG = "코드가 맞지 않습니다."
SUPERSEDED = "이 코드는 더 이상 쓸 수 없습니다. 코드를 다시 받아 주세요."


class Outcome(StrEnum):
    OK = "ok"
    WRONG = "wrong"
    LOCKED = "locked"
    EXPIRED = "expired"
    USED = "used"
    BAD_FORMAT = "bad_format"


@dataclass(frozen=True)
class VerifyResult:
    outcome: Outcome
    message: str = ""
    remaining: int | None = None  # 틀렸을 때 더 입력할 수 있는 횟수. 알 수 없으면 None
    challenge_id: int | None = None


class ResendTooSoon(Exception):
    """직전 요청 60초 안에 다시 요청했다(AC32)."""

    def __init__(self, seconds: int) -> None:
        super().__init__(f"코드는 {seconds}초 뒤에 다시 받을 수 있습니다.")
        self.seconds = seconds


# --- 계산 ---------------------------------------------------------------------------------------


def _require_secret(secret: str) -> None:
    if not secret:
        raise ValueError("SERVER_SECRET이 비어 있습니다. .env에 값을 넣고 서버를 다시 시작해 주세요.")


def compute_code(secret: str, challenge_id: int, nonce: str) -> str:
    """HMAC-SHA256(서버 비밀값, 챌린지 번호:난수)에서 6자리 숫자를 뽑는다."""
    _require_secret(secret)
    digest = hmac.new(secret.encode(), f"{challenge_id}:{nonce}".encode(), hashlib.sha256).digest()
    # 64비트에서 뽑아 100만으로 나눈 나머지의 치우침은 무시할 만큼 작다(약 5e-14)
    return str(int.from_bytes(digest[:8], "big") % 10**CODE_DIGITS).zfill(CODE_DIGITS)


def code_for(db: sqlite3.Connection, secret: str, challenge_id: int) -> str:
    """저장된 챌린지의 코드. 메일 본문과 교수 화면이 쓴다. 코드는 저장하지 않고 이때마다 계산한다."""
    row = db.execute("SELECT id, nonce FROM login_challenges WHERE id = ?", (challenge_id,)).fetchone()
    return compute_code(secret, row["id"], row["nonce"])


# --- 기기 ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Device:
    device_id: int
    token: str  # 쿠키에 심을 값
    is_new: bool


def find_device(db: sqlite3.Connection, token: str | None) -> int | None:
    """쿠키의 기기 번호. 없거나 모르는 값이면 None(새 기기를 만들지 않는다)."""
    if not token:
        return None
    row = db.execute("SELECT id FROM devices WHERE token_hash = ?", (hash_token(token),)).fetchone()
    return row["id"] if row else None


def ensure_device(db: sqlite3.Connection, token: str | None, now: datetime) -> Device:
    """쿠키의 기기를 찾는다. 없거나 모르는 값이면 새 기기로 만든다(브라우저 데이터를 지우면 새 기기, AC33)."""
    if token:
        row = db.execute("SELECT id FROM devices WHERE token_hash = ?", (hash_token(token),)).fetchone()
        if row:
            return Device(row["id"], token, False)
    new_token = secrets.token_urlsafe(16)  # 128비트. DB에는 해시만 둔다
    with transaction(db):
        cursor = db.execute(
            "INSERT INTO devices(token_hash, first_seen_at) VALUES (?, ?)", (hash_token(new_token), now.isoformat())
        )
    return Device(cursor.lastrowid, new_token, True)


# --- 챌린지 -----------------------------------------------------------------------------------------


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def resend_wait(db: sqlite3.Connection, classroom_id: int, email_norm: str, now: datetime) -> int:
    """다시 받기까지 남은 초(올림). 지금 받을 수 있으면 0. 같은 강좌·같은 이메일의 직전 요청 기준이다."""
    last = db.execute(
        "SELECT created_at FROM login_challenges WHERE classroom_id = ? AND email_norm = ? ORDER BY id DESC LIMIT 1",
        (classroom_id, email_norm),
    ).fetchone()
    if last is None:
        return 0
    remaining = (_at(last["created_at"]) + RESEND_INTERVAL - now).total_seconds()
    return max(0, math.ceil(remaining))


def supersede_active(db: sqlite3.Connection, classroom_id: int, email_norm: str) -> None:
    """이 강좌에서 이 이메일의 쓸 수 있는 코드를 모두 쓸 수 없게 한다(새 코드를 받았거나 명단에서 빠졌을 때)."""
    db.execute(
        "UPDATE login_challenges SET status = 'superseded' "
        "WHERE classroom_id = ? AND email_norm = ? AND status = 'active'",
        (classroom_id, email_norm),
    )


def supersede_classroom(db: sqlite3.Connection, classroom_id: int) -> None:
    """이 강좌의 쓸 수 있는 코드를 모두 쓸 수 없게 한다(강좌 보관). 보내지 않은 코드 메일도 발송 작업이 버린다."""
    db.execute(
        "UPDATE login_challenges SET status = 'superseded' WHERE classroom_id = ? AND status = 'active'",
        (classroom_id,),
    )


def issue_challenge_unlocked(
    db: sqlite3.Connection, secret: str, classroom_id: int, email_norm: str, device_id: int, now: datetime
) -> int:
    """`issue_challenge`의 본체. 호출하는 쪽이 이미 연 쓰기 트랜잭션 안에서 부른다(예: 메일 발송 요청과 함께 저장하려고)."""
    _require_secret(secret)  # 비밀값이 비어 있으면 챌린지를 남기기 전에 알린다
    wait = resend_wait(db, classroom_id, email_norm, now)
    if wait > 0:
        raise ResendTooSoon(wait)
    supersede_active(db, classroom_id, email_norm)
    cursor = db.execute(
        "INSERT INTO login_challenges(classroom_id, email_norm, device_id, nonce, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            classroom_id,
            email_norm,
            device_id,
            secrets.token_hex(16),
            now.isoformat(),
            (now + CODE_LIFETIME).isoformat(),
        ),
    )
    return cursor.lastrowid


def issue_challenge(
    db: sqlite3.Connection, secret: str, classroom_id: int, email_norm: str, device_id: int, now: datetime
) -> int:
    """새 챌린지를 만든다. 이전 챌린지는 쓸 수 없게 하고, 60초 안의 다시 요청은 거부한다. 챌린지 번호를 돌려준다."""
    _require_secret(secret)
    with transaction(db):
        return issue_challenge_unlocked(db, secret, classroom_id, email_norm, device_id, now)


def verify_code(
    db: sqlite3.Connection,
    secret: str,
    classroom_id: int,
    email_norm: str,
    device_id: int,
    typed: str,
    now: datetime,
) -> VerifyResult:
    """입력한 코드를 확인한다. 상태 변경(횟수, 만료, 사용)은 한 쓰기 트랜잭션 안에서 한다."""
    with transaction(db):
        return verify_code_unlocked(db, secret, classroom_id, email_norm, device_id, typed, now)


def verify_code_unlocked(
    db: sqlite3.Connection,
    secret: str,
    classroom_id: int,
    email_norm: str,
    device_id: int,
    typed: str,
    now: datetime,
) -> VerifyResult:
    """`verify_code`의 본체. 호출하는 쪽이 이미 연 쓰기 트랜잭션 안에서 부른다(맞으면 멤버십 만들기와 함께 저장하려고)."""
    typed = typed.strip()
    if not (len(typed) == CODE_DIGITS and typed.isascii() and typed.isdigit()):
        # 형식이 틀린 입력은 횟수를 쓰지 않는다(오타로 기회를 잃지 않게)
        return VerifyResult(Outcome.BAD_FORMAT, f"코드는 {CODE_DIGITS}자리 숫자입니다. 메일의 코드를 확인해 주세요.")
    row = db.execute(
        "SELECT * FROM login_challenges WHERE classroom_id = ? AND email_norm = ? ORDER BY id DESC LIMIT 1",
        (classroom_id, email_norm),
    ).fetchone()
    if row is None or row["device_id"] != device_id:
        # 다른 기기이거나 요청한 적이 없다. 코드가 있는지, 쓰였는지도 알려 주지 않고 아무것도 바꾸지 않는다(AC33)
        return VerifyResult(Outcome.WRONG, GENERIC_WRONG)
    challenge_id = row["id"]  # 가장 최근 챌린지다. 더 새 챌린지가 생기면 이전 것은 superseded가 되어 여기에 오지 않는다
    if row["status"] == "used":
        return VerifyResult(Outcome.USED, "이미 사용된 코드입니다. 코드를 다시 받아 주세요.", challenge_id=challenge_id)
    if row["status"] == "expired":
        return _unusable(row)
    if row["status"] == "superseded":  # 새 코드 없이 대체된 경우: 명단에서 빠졌을 때(다시 넣어도 이 코드는 쓸 수 없다)
        return VerifyResult(Outcome.EXPIRED, SUPERSEDED, challenge_id=challenge_id)
    if now >= _at(row["expires_at"]):
        db.execute("UPDATE login_challenges SET status = 'expired' WHERE id = ?", (challenge_id,))
        return VerifyResult(Outcome.EXPIRED, "코드가 만료되었습니다. 코드를 다시 받아 주세요.", challenge_id=challenge_id)
    expected = compute_code(secret, challenge_id, row["nonce"])
    if hmac.compare_digest(typed, expected):
        db.execute(
            "UPDATE login_challenges SET status = 'used', used_at = ? WHERE id = ?", (now.isoformat(), challenge_id)
        )
        return VerifyResult(Outcome.OK, challenge_id=challenge_id)
    attempts = row["attempts"] + 1
    if attempts >= MAX_ATTEMPTS:
        db.execute(
            "UPDATE login_challenges SET attempts = ?, status = 'expired' WHERE id = ?", (attempts, challenge_id)
        )
        return VerifyResult(Outcome.LOCKED, "코드를 다시 받아 주세요.", 0, challenge_id)
    db.execute("UPDATE login_challenges SET attempts = ? WHERE id = ?", (attempts, challenge_id))
    left = MAX_ATTEMPTS - attempts
    return VerifyResult(Outcome.WRONG, f"{GENERIC_WRONG} {left}번 더 입력할 수 있습니다.", left, challenge_id)


def _unusable(row: sqlite3.Row) -> VerifyResult:
    """이미 만료로 표시된 챌린지. 횟수를 다 써서 잠긴 것과 시간이 지난 것을 구별해 안내한다."""
    if row["attempts"] >= MAX_ATTEMPTS:
        return VerifyResult(Outcome.LOCKED, "코드를 다시 받아 주세요.", 0, row["id"])
    return VerifyResult(Outcome.EXPIRED, "코드가 만료되었습니다. 코드를 다시 받아 주세요.", challenge_id=row["id"])


def notify_professor(
    db: sqlite3.Connection, classroom_id: int, email_norm: str, device_id: int | None, now: datetime
) -> tuple[str, int | None]:
    """학생이 '교수님께 알리기'를 눌렀다. 알린 시각을 남기면 교수의 '대기 중인 인증' 목록에 코드가 보인다(AC44, AC45).

    코드를 요청한 기기에서만 알릴 수 있다. 결과: "ok"(처음 알림), "again"(이미 알렸다), "none"(알릴 코드가 없다. 다른 기기나 요청한 적 없음도 같다),
    "used"(이미 사용), "expired"(만료됐거나 횟수를 다 썼다). 알린 시각은 처음 것을 그대로 둔다.
    챌린지 번호도 함께 돌려준다(없으면 None).
    """
    with transaction(db):
        row = db.execute(
            "SELECT * FROM login_challenges WHERE classroom_id = ? AND email_norm = ? ORDER BY id DESC LIMIT 1",
            (classroom_id, email_norm),
        ).fetchone()
        if row is None or row["device_id"] != device_id:  # 기기 쿠키가 없는 경우(None)도 여기서 걸린다
            return "none", None
        if row["status"] == "used":
            return "used", None
        if row["status"] != "active" or now >= _at(row["expires_at"]):
            return "expired", None
        if row["professor_notified_at"] is not None:
            return "again", row["id"]
        db.execute("UPDATE login_challenges SET professor_notified_at = ? WHERE id = ?", (now.isoformat(), row["id"]))
        return "ok", row["id"]


def notified_active_ids(db: sqlite3.Connection, classroom_id: int, email_norm: str) -> list[int]:
    """교수에게 알린 채 아직 쓸 수 있는 챌린지 번호. 새 코드를 받으면 이것들이 대체된다."""
    rows = db.execute(
        "SELECT id FROM login_challenges WHERE classroom_id = ? AND email_norm = ? AND status = 'active' "
        "AND professor_notified_at IS NOT NULL",
        (classroom_id, email_norm),
    ).fetchall()
    return [r["id"] for r in rows]


def was_notified(db: sqlite3.Connection, challenge_id: int) -> bool:
    row = db.execute("SELECT professor_notified_at FROM login_challenges WHERE id = ?", (challenge_id,)).fetchone()
    return row is not None and row["professor_notified_at"] is not None
