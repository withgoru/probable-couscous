"""출석 받는 창과 출석 상태를 DB에서 읽고 쓰는 함수(003 plan 데이터 모델).

- 창은 회차마다 "아직 닫지 않은" 행이 하나다. 열림 = `closed_at`이 없고 `closes_at`이 지금보다 뒤.
  시간이 지나 닫힐 때 서버는 아무것도 쓰지 않는다. 마감·다시 받기·수업 종료가 `closed_at`을 채운다.
- 시각은 모두 UTC `datetime.isoformat()` 문자열로 저장하고, 비교는 파이썬 `datetime`으로 한다.
- 쓰는 함수는 부르는 쪽이 연 쓰기 트랜잭션 안에서 부른다(수업 시작·종료와 같은 트랜잭션, C13).
- 학생은 명단 항목 번호로 센다. 출석 수와 명단 인원은 지금 명단(`removed_at IS NULL`)만 본다(AC6, AC25).
"""

import secrets
import sqlite3
from datetime import datetime, timedelta

from app import events, identity
from app.attendance_core import AttendanceStatus, attendance_status


def _at(value: str) -> datetime:
    return datetime.fromisoformat(value)


def unclosed_window(db: sqlite3.Connection, classroom_id: int, session_id: int) -> sqlite3.Row | None:
    """아직 `closed_at`을 채우지 않은 창(시간이 지나 사실상 닫혔을 수 있다)."""
    return db.execute(
        "SELECT * FROM attendance_windows WHERE classroom_id = ? AND session_id = ? AND closed_at IS NULL",
        (classroom_id, session_id),
    ).fetchone()


def is_open(window: sqlite3.Row | None, now: datetime) -> bool:
    return window is not None and window["closed_at"] is None and _at(window["closes_at"]) > now


def open_window(
    db: sqlite3.Connection,
    classroom_id: int,
    session_id: int,
    opened_by: str,
    github_id: int,
    now: datetime,
) -> int:
    """강좌의 출석 받는 시간만큼 새 창을 연다. 새 난수라 새 코드다(AC5). 남아 있는 창은 먼저 닫아야 한다."""
    (minutes,) = db.execute("SELECT attendance_minutes FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()
    window_id = db.execute(
        "INSERT INTO attendance_windows(classroom_id, session_id, nonce, opened_at, closes_at, opened_by) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            classroom_id,
            session_id,
            secrets.token_hex(16),
            now.isoformat(),
            (now + timedelta(minutes=minutes)).isoformat(),
            opened_by,
        ),
    ).lastrowid
    events.record_event(
        db,
        classroom_id,
        "attendance_opened",
        "professor",
        github_id,
        None,
        {"session_id": session_id, "window_id": window_id, "minutes": minutes},
        now,
    )
    return window_id


def close_window(
    db: sqlite3.Connection, classroom_id: int, session_id: int, by: str, github_id: int, now: datetime
) -> bool:
    """남아 있는 창의 `closed_at`을 채운다. 시간이 지나 이미 닫혔으면 마감 시각을, 열려 있으면 지금을 쓴다.

    열려 있던 창을 닫았을 때만 `attendance_closed`를 기록하고 참을 돌려준다.
    """
    window = unclosed_window(db, classroom_id, session_id)
    if window is None:
        return False
    was_open = is_open(window, now)
    closed_at = now if was_open else _at(window["closes_at"])
    db.execute("UPDATE attendance_windows SET closed_at = ? WHERE id = ?", (closed_at.isoformat(), window["id"]))
    if was_open:
        events.record_event(
            db,
            classroom_id,
            "attendance_closed",
            "professor",
            github_id,
            None,
            {"session_id": session_id, "window_id": window["id"], "by": by},
            now,
        )
    return was_open


def window_summary(db: sqlite3.Connection, classroom_id: int, session_id: int, now: datetime) -> dict | None:
    """화면에 보이는 마지막 창. 한 번도 열지 않았으면 None."""
    window = db.execute(
        "SELECT * FROM attendance_windows WHERE classroom_id = ? AND session_id = ? ORDER BY id DESC LIMIT 1",
        (classroom_id, session_id),
    ).fetchone()
    if window is None:
        return None
    open_ = is_open(window, now)
    closed_at = window["closed_at"]
    if closed_at is None and not open_:
        closed_at = window["closes_at"]  # 시간이 지나 닫혔다
    return {"open": open_, "opened_at": window["opened_at"], "closes_at": window["closes_at"], "closed_at": closed_at}


def latest_kinds(db: sqlite3.Connection, classroom_id: int, session_id: int) -> dict[int, str]:
    """명단 항목 번호 → 이 회차의 마지막 기록 종류. 기록이 없는 학생은 없다(결석)."""
    rows = db.execute(
        "SELECT m.roster_entry_id, m.kind FROM attendance_marks m "
        "WHERE m.classroom_id = ? AND m.session_id = ? AND m.id = ("
        "  SELECT MAX(id) FROM attendance_marks l"
        "   WHERE l.classroom_id = m.classroom_id AND l.session_id = m.session_id AND l.roster_entry_id = m.roster_entry_id"
        ")",
        (classroom_id, session_id),
    )
    return {r["roster_entry_id"]: r["kind"] for r in rows}


def last_status(db: sqlite3.Connection, classroom_id: int, session_id: int, roster_entry_id: int) -> AttendanceStatus:
    """한 학생의 이 회차 상태(마지막 기록 한 줄만 읽는다)."""
    last = db.execute(
        "SELECT kind FROM attendance_marks WHERE classroom_id = ? AND session_id = ? AND roster_entry_id = ? "
        "ORDER BY id DESC LIMIT 1",
        (classroom_id, session_id, roster_entry_id),
    ).fetchone()
    return attendance_status([last["kind"]] if last else [])


def status_of(kinds: dict[int, str], roster_entry_id: int) -> AttendanceStatus:
    kind = kinds.get(roster_entry_id)
    return attendance_status([kind] if kind else [])


def professor_tally(db: sqlite3.Connection, classroom_id: int, session_id: int) -> dict:
    """교수 화면의 "출석 N / M"과 "수기 출석 요청 N"(AC6, AC18). 지금 명단만 센다."""
    roster = [
        r["id"]
        for r in db.execute(
            "SELECT id FROM roster_entries WHERE classroom_id = ? AND removed_at IS NULL", (classroom_id,)
        )
    ]
    kinds = latest_kinds(db, classroom_id, session_id)
    present = sum(1 for entry in roster if status_of(kinds, entry) is not AttendanceStatus.ABSENT)
    # 대기 요청: 처리하지 않았고, 지금 명단에 있고, 아직 결석인 학생의 것(요청 뒤 코드로 출석했으면 세지 않는다)
    pending = sum(
        1 for r in pending_requests(db, classroom_id, session_id) if status_of(kinds, r["roster_entry_id"])
        is AttendanceStatus.ABSENT
    )
    return {"present": present, "roster": len(roster), "pending": pending}


def pending_requests(db: sqlite3.Connection, classroom_id: int, session_id: int) -> list[sqlite3.Row]:
    """처리하지 않은 요청 중 지금 명단 학생의 것(요청 번호 순)."""
    return db.execute(
        "SELECT q.* FROM attendance_requests q "
        "JOIN roster_entries r ON r.id = q.roster_entry_id AND r.classroom_id = q.classroom_id AND r.removed_at IS NULL "
        "WHERE q.classroom_id = ? AND q.session_id = ? "
        "AND NOT EXISTS (SELECT 1 FROM attendance_decisions d WHERE d.request_id = q.id) ORDER BY q.id",
        (classroom_id, session_id),
    ).fetchall()


def student_view(db: sqlite3.Connection, classroom_id: int, session_id: int, membership_id: int) -> dict:
    """학생 본인의 출석 상태와 수기 요청 상태. 다른 학생 정보는 담지 않는다(AC27)."""
    entry = identity.roster_entry_of(db, classroom_id, membership_id)
    if entry is None:
        return {"status": AttendanceStatus.ABSENT.value, "request": "none"}
    status = last_status(db, classroom_id, session_id, entry)  # 다시 받을 때마다 학생 수만큼 불려 한 줄만 읽는다
    request = db.execute(
        "SELECT d.decision FROM attendance_requests q LEFT JOIN attendance_decisions d ON d.request_id = q.id "
        "WHERE q.classroom_id = ? AND q.session_id = ? AND q.roster_entry_id = ?",
        (classroom_id, session_id, entry),
    ).fetchone()
    if request is None:
        state = "none"
    else:
        state = request["decision"] or "pending"
    return {"status": status.value, "request": state}


def live_attendance(
    db: sqlite3.Connection, classroom_id: int, session_id: int, now: datetime, membership_id: int | None
) -> dict:
    """`GET …/live`의 `attendance`. 교수(membership_id 없음)는 수까지, 학생은 자기 것만."""
    body = {"window": window_summary(db, classroom_id, session_id, now)}
    if membership_id is None:
        body.update(professor_tally(db, classroom_id, session_id))
    else:
        body.update(student_view(db, classroom_id, session_id, membership_id))
    body["server_now"] = now.isoformat()
    return body
