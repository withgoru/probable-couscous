"""수강생 명단 규칙(AC15, AC16, AC18). CSV 올리기와 한 명 추가가 같은 검사를 쓴다.

이름·이메일·학번은 명단 표에만 둔다(C7, C11). 이 모듈은 닉네임을 다루지 않는다(C9).
"""

import csv
import io
import re
import sqlite3
from dataclasses import dataclass

from app.db import transaction

ROSTER_LIMIT = 200
IMPORT_MAX_BYTES = 1024 * 1024  # CSV 한 번에 1MB
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


def is_valid_email(text: str) -> bool:
    """이메일 형식 검사. 명단 입력과 학생 입장이 같은 규칙을 쓴다."""
    return bool(_EMAIL.match(text))


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
    if not is_valid_email(values["email"]):
        raise RosterError("email_format", "이메일 형식을 확인해 주세요.", "email")
    return CleanEntry(values["student_no"], values["name"], normalize_email(values["email"]))


def live_count(db: sqlite3.Connection, classroom_id: int) -> int:
    return db.execute(
        "SELECT COUNT(*) FROM roster_entries WHERE classroom_id = ? AND removed_at IS NULL", (classroom_id,)
    ).fetchone()[0]


def find_live_by_email(db: sqlite3.Connection, classroom_id: int, email_norm: str) -> sqlite3.Row | None:
    """이 강좌의 살아 있는 명단에서 이메일(정규화한 값)로 학생을 찾는다. 빼기한 학생은 찾지 않는다."""
    return db.execute(
        "SELECT * FROM roster_entries WHERE classroom_id = ? AND email_norm = ? AND removed_at IS NULL",
        (classroom_id, email_norm),
    ).fetchone()


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
        return _insert(db, classroom_id, entry, now)


def _insert(db: sqlite3.Connection, classroom_id: int, entry: CleanEntry, now: str) -> int:
    cursor = db.execute(
        "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at) "
        "VALUES (?, ?, ?, ?, ?)",
        (classroom_id, entry.student_no, entry.name, entry.email_norm, now),
    )
    return cursor.lastrowid


# --- CSV 올리기 (AC13, AC14, AC18) ---------------------------------------------------------

UNREADABLE = "파일을 읽을 수 없습니다. UTF-8 CSV로 저장해 다시 올려 주세요."
EMPTY_FILE = "파일이 비어 있습니다. 첫 줄에 제목(학번, 이름, 이메일)을 쓰고 학생을 한 줄에 한 명씩 적어 올려 주세요."
NO_TITLE = (
    "첫 줄은 제목(학번, 이름, 이메일)이어야 합니다. 제목 줄을 맨 위에 넣고 다시 올려 주세요."
)
TOO_LARGE = "파일이 너무 큽니다. 1MB 이하로 나눠 올려 주세요."
# 건너뛴 줄에 보여 주는 이유(AC14)
SKIP_LABELS = {
    "blank": "빈 칸",
    "too_long": "입력이 너무 깁니다",
    "email_format": "이메일 형식 오류",
    "duplicate_email": "이메일 중복",
    "duplicate_student_no": "학번 중복",
    "columns": "열 개수 오류",
}


def parse_csv(data: bytes) -> list[tuple[int, list[str]]]:
    """UTF-8(BOM 허용) CSV를 (줄 번호, 칸 목록)으로 나눈다. 첫 줄은 제목이라 빼고, 줄 번호는 파일의 줄 기준이다."""
    if not data.strip():
        raise RosterError("empty", EMPTY_FILE)
    try:
        text = data.decode("utf-8-sig")  # 엄격하게: CP949 같은 다른 인코딩은 실패해야 한다
    except UnicodeDecodeError as err:
        raise RosterError("unreadable", UNREADABLE) from err
    if "\x00" in text:
        raise RosterError("unreadable", UNREADABLE)
    reader = csv.reader(io.StringIO(text, newline=""))
    rows: list[tuple[int, list[str]]] = []
    try:
        while True:
            first_line = reader.line_num + 1
            try:
                cells = next(reader)
            except StopIteration:
                break
            rows.append((first_line, cells))
    except csv.Error as err:
        raise RosterError("unreadable", UNREADABLE) from err
    # 제목 줄이 없으면 첫 학생이 조용히 사라진다. 첫 줄의 이메일 칸이 이메일처럼 보이면 알려 준다
    header = rows[0][1] if rows else []
    if len(header) >= 3 and _EMAIL.match(header[2].strip()):
        raise RosterError("no_title", NO_TITLE)
    return rows[1:]


def import_rows(db: sqlite3.Connection, classroom_id: int, rows: list[tuple[int, list[str]]], now: str) -> dict:
    """올바른 줄만 한 트랜잭션으로 등록한다. 등록할 인원이 200명을 넘으면 아무도 넣지 않는다(AC18)."""
    with transaction(db):
        accepted: list[CleanEntry] = []
        skipped: list[dict] = []
        seen_email: set[str] = set()
        seen_no: set[str] = set()

        def skip(line: int, reason: str) -> None:
            skipped.append({"line": line, "reason": SKIP_LABELS[reason]})

        for line, cells in rows:
            if all(not c.strip() for c in cells):
                continue  # 엑셀이 붙이는 빈 줄은 세지 않는다
            if len(cells) < 3 or any(c.strip() for c in cells[3:]):
                skip(line, "columns")
                continue
            try:
                entry = clean_entry(*cells[:3])
            except RosterError as err:
                skip(line, err.reason)
                continue
            problem = find_duplicate(db, classroom_id, entry)
            if problem:
                skip(line, problem.reason)
            elif entry.email_norm in seen_email:
                skip(line, "duplicate_email")
            elif entry.student_no in seen_no:
                skip(line, "duplicate_student_no")
            else:
                seen_email.add(entry.email_norm)
                seen_no.add(entry.student_no)
                accepted.append(entry)
        over = live_count(db, classroom_id) + len(accepted) - ROSTER_LIMIT
        if over > 0:
            raise RosterError("roster_full", full_message(over))
        for entry in accepted:
            _insert(db, classroom_id, entry, now)
    return {"added": len(accepted), "skipped": len(skipped), "skipped_lines": skipped}
