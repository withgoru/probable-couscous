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



