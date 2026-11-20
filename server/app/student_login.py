"""학생의 기기 로그인(자동 로그인) 만들기. 코드를 확인하면 이 기기에 로그인 상태를 심는다(AC26, AC35, AC36).

- 로그인 토큰은 쿠키에만 있고 DB에는 해시만 둔다.
- '이 기기에서 로그인 유지'를 켜면 만료 없이(강좌가 보관될 때까지), 끄면 브라우저를 닫을 때 사라지는 쿠키와 24시간 안전 상한을 둔다.
- 이 로그인은 계정 단위라 이것만으로는 어느 강좌에도 들어갈 수 없다. 강좌별 입장은 `classroom_verifications`가 따로 기록한다(T020).
"""

import secrets
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timedelta

from app.auth import hash_token
from app.challenges import find_device

LOGIN_COOKIE = "student_login"
PERSISTENT_MAX_AGE = 60 * 60 * 24 * 365  # 쿠키 수명 1년(서버의 로그인 상태는 강좌가 보관될 때까지)
SESSION_LIMIT = timedelta(hours=24)


@dataclass(frozen=True)
class DeviceLogin:
    token: str
    persistent: bool


def create_device_login(
    db: sqlite3.Connection, account_id: int, device_id: int, persistent: bool, now: datetime
) -> DeviceLogin:
    """이 기기의 로그인 상태를 만든다. 호출하는 쪽이 연 쓰기 트랜잭션 안에서 부른다."""
    token = secrets.token_urlsafe(16)  # 128비트
    db.execute(
        "INSERT INTO device_logins(token_hash, account_id, device_id, persistent, created_at, expires_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            hash_token(token),
            account_id,
            device_id,
            1 if persistent else 0,
            now.isoformat(),
            None if persistent else (now + SESSION_LIMIT).isoformat(),
        ),
    )
    return DeviceLogin(token, persistent)





@dataclass(frozen=True)
class LoginRef:
    id: int
    account_id: int
    created_at: datetime


def current_login(
    db: sqlite3.Connection, login_token: str | None, device_token: str | None, now: datetime
) -> LoginRef | None:
    """요청한 기기의 유효한 로그인 상태. 없거나, 끝났거나(만료·취소), 이 기기의 것이 아니면 None.

    로그인 쿠키만 훔쳐도 쓸 수 없도록 로그인이 만들어진 기기의 쿠키가 함께 맞아야 한다.
    """
    if not login_token:
        return None
    device_id = find_device(db, device_token)
    if device_id is None:
        return None
    row = db.execute(
        "SELECT id, account_id, created_at, expires_at FROM device_logins "
        "WHERE token_hash = ? AND device_id = ? AND revoked_at IS NULL",
        (hash_token(login_token), device_id),
    ).fetchone()
    if row is None:
        return None
    if row["expires_at"] is not None and now >= datetime.fromisoformat(row["expires_at"]):
        return None
    return LoginRef(row["id"], row["account_id"], datetime.fromisoformat(row["created_at"]))


def account_email(db: sqlite3.Connection, account_id: int) -> str:
    return db.execute("SELECT email_norm FROM accounts WHERE id = ?", (account_id,)).fetchone()["email_norm"]


def record_verification(
    db: sqlite3.Connection, device_login_id: int, classroom_id: int, membership_id: int, now: datetime
) -> None:
    """이 기기가 이 강좌에서 인증을 마쳤다는 기록(입장 확정). 이미 있으면 처음 기록을 그대로 둔다."""
    db.execute(
        "INSERT OR IGNORE INTO classroom_verifications(device_login_id, classroom_id, membership_id, verified_at) "
        "VALUES (?, ?, ?, ?)",
        (device_login_id, classroom_id, membership_id, now.isoformat()),
    )


def verified_at(db: sqlite3.Connection, device_login_id: int, classroom_id: int) -> datetime | None:
    row = db.execute(
        "SELECT verified_at FROM classroom_verifications WHERE device_login_id = ? AND classroom_id = ?",
        (device_login_id, classroom_id),
    ).fetchone()
    return datetime.fromisoformat(row["verified_at"]) if row else None
