"""수강생 명단 규칙(AC15, AC16, AC18). CSV 올리기와 한 명 추가가 같은 검사를 쓴다.

이름·이메일·학번은 명단 표에만 둔다(C7, C11). 이 모듈은 닉네임을 다루지 않는다(C9).
"""

import re
import sqlite3
from dataclasses import dataclass

from app.db import transaction

ROSTER_LIMIT = 200
STUDENT_NO_MAX = 50
NAME_MAX = 100
EMAIL_MAX = 254

# 공백 없는 `이름@도메인.최상위`. 더 엄격한 검사는 오히려 정상 주소를 막는다. 진짜 확인은 인증 코드 메일이 한다
_EMAIL = re.compile(r"^[^@\s]+@[^@\s.]+(\.[^@\s.]+)+$")

LABELS = {"student_no": "학번", "name": "이름", "email": "이메일"}
LIMITS = {"student_no": STUDENT_NO_MAX, "name": NAME_MAX, "email": EMAIL_MAX}


class RosterError(Exception):
    """한 줄을 명단에 넣을 수 없는 이유. field는 화면의 입력 칸(없으면 명단 전체), reason은 CSV 결과 표에도 쓴다."""

    def __init__(self, reason: str, message: str, field: str | None = None):
        super().__init__(message)
        self.reason = reason
        self.message = message
        self.field = field


@dataclass(frozen=True)
class CleanEntry:
    student_no: str
    name: str
    email_norm: str


def normalize_email(email: str) -> str:
    """앞뒤 공백과 대소문자를 무시한다(AC16)."""
    return email.strip().lower()


def full_message(over: int) -> str:
    """AC18 문구. CSV는 넘는 만큼(over)을 알려 준다."""
    return f"명단은 {ROSTER_LIMIT}명까지 등록할 수 있습니다. {over}명을 줄여 다시 올려 주세요."


def clean_entry(student_no: object, name: object, email: object) -> CleanEntry:
    """공백을 정리하고 빈 칸, 길이, 이메일 형식을 검사한다. 화면의 칸 순서대로 첫 오류를 올린다."""
    values: dict[str, str] = {}
    for field, raw in (("student_no", student_no), ("name", name), ("email", email)):
        text = raw.strip() if isinstance(raw, str) else ""
        if not text:
            raise RosterError("blank", f"{LABELS[field]}을 입력해 주세요.", field)
        if len(text) > LIMITS[field]:
            raise RosterError("too_long", f"{LABELS[field]}은 {LIMITS[field]}자 이하로 입력해 주세요.", field)
        values[field] = text
    if not _EMAIL.match(values["email"]):
        raise RosterError("email_format", "이메일 형식을 확인해 주세요.", "email")
    return CleanEntry(values["student_no"], values["name"], normalize_email(values["email"]))


def live_count(db: sqlite3.Connection, classroom_id: int) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM roster_entries WHERE classroom_id = ? AND removed_at IS NULL", (classroom_id,)
    ).fetchone()[0]


def find_duplicate(db: sqlite3.Connection, classroom_id: int, entry: CleanEntry) -> RosterError | None:
    """같은 강좌의 살아 있는 명단과 겹치는지. 빼기한 학생과는 겹쳐도 된다."""
    if db.execute(
        "SELECT 1 FROM roster_entries WHERE classroom_id = ? AND email_norm = ? AND removed_at IS NULL",
        (classroom_id, entry.email_norm),
    ).fetchone():
        return RosterError("duplicate_email", "이미 명단에 있는 이메일입니다. 다른 이메일을 입력해 주세요.", "email")
    if db.execute(
        "SELECT 1 FROM roster_entries WHERE classroom_id = ? AND student_no = ? AND removed_at IS NULL",
        (classroom_id, entry.student_no),
    ).fetchone():
        return RosterError("duplicate_student_no", "이미 명단에 있는 학번입니다. 학번을 확인해 주세요.", "student_no")
    return None


def add_entry(db: sqlite3.Connection, classroom_id: int, entry: CleanEntry, now: str) -> int:
    """한 명을 추가한다. 중복과 200명 상한은 쓰기 잠금을 잡은 같은 트랜잭션 안에서 센다."""
    with transaction(db):
        duplicate = find_duplicate(db, classroom_id, entry)
        if duplicate:
            raise duplicate
        if live_count(db, classroom_id) >= ROSTER_LIMIT:
            raise RosterError(
                "roster_full",
                f"명단은 {ROSTER_LIMIT}명까지 등록할 수 있습니다. 다른 학생을 빼고 다시 추가해 주세요.",
            )
        cursor = db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (classroom_id, entry.student_no, entry.name, entry.email_norm, now),
        )
        return cursor.lastrowid
