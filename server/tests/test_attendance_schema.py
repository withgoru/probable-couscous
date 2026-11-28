"""003 T001: 출석 스키마(0004). 출석 받는 창, 출석 기록, 수기 요청, 요청 처리, 강좌의 출석 받는 시간.

C7(개인정보 열 없음, 명단과의 외래 키 없음)과 C5 분류는 `test_schema.py`가 모든 표에 대해 확인한다.
여기서는 DB가 직접 막아야 하는 규칙과 C6(추가만)을 본다.
"""

import itertools
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest

from app.clock import ManualClock
from app.db import MIGRATIONS_DIR, connect, migrate

NOW = "2026-03-01T09:00:00+00:00"
LATER = "2026-03-01T09:10:00+00:00"
APP_DIR = Path(__file__).resolve().parent.parent / "app"
RECORD_TABLES = ("attendance_marks", "attendance_requests", "attendance_decisions")
ATTENDANCE_TABLES = ("attendance_windows", *RECORD_TABLES)
_nick = itertools.count(1)


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "app.db")
    migrate(conn, MIGRATIONS_DIR, ManualClock(datetime(2026, 3, 1, 9, tzinfo=UTC)))
    yield conn
    conn.close()


def make_classroom(db, name="알고리즘"):
    owner = abs(hash(name)) % 10_000 + 2
    db.execute("INSERT OR IGNORE INTO professors(github_id, login, created_at) VALUES (?, 'p', ?)", (owner, NOW))
    return db.execute(
        "INSERT INTO classrooms(owner_github_id, name, invite_token, created_at) VALUES (?, ?, ?, ?)",
        (owner, name, f"tok-{name}", NOW),
    ).lastrowid


def make_session(db, classroom_id, order=1):
    return db.execute(
        "INSERT INTO class_sessions(classroom_id, title, sort_order, status, created_at) VALUES (?, '1회차', ?, 'live', ?)",
        (classroom_id, order, NOW),
    ).lastrowid


def make_member(db, classroom_id, nickname="용감한 수달"):
    return db.execute(
        "INSERT INTO memberships(classroom_id, nickname, created_at) VALUES (?, ?, ?)", (classroom_id, nickname, NOW)
    ).lastrowid


def make_window(db, classroom_id, session_id, closed_at=None, nonce="0" * 32):
    return db.execute(
        "INSERT INTO attendance_windows(classroom_id, session_id, nonce, opened_at, closes_at, closed_at, opened_by) "
        "VALUES (?, ?, ?, ?, ?, ?, 'start')",
        (classroom_id, session_id, nonce, NOW, LATER, closed_at),
    ).lastrowid


def code_mark(db, classroom_id, session_id, roster_entry_id=1, membership_id=None, key="k1"):
    membership_id = membership_id or make_member(db, classroom_id, f"닉{key}")
    return db.execute(
        "INSERT INTO attendance_marks(classroom_id, session_id, roster_entry_id, membership_id, kind, actor_kind, "
        "actor_ref, client_key, created_at) VALUES (?, ?, ?, ?, 'code', 'student', ?, ?, ?)",
        (classroom_id, session_id, roster_entry_id, membership_id, membership_id, key, NOW),
    ).lastrowid


def manual_mark(db, classroom_id, session_id, roster_entry_id=1, kind="manual_present", request_id=None):
    return db.execute(
        "INSERT INTO attendance_marks(classroom_id, session_id, roster_entry_id, kind, actor_kind, actor_ref, "
        "request_id, created_at) VALUES (?, ?, ?, ?, 'professor', 7, ?, ?)",
        (classroom_id, session_id, roster_entry_id, kind, request_id, NOW),
    ).lastrowid


def make_request(db, classroom_id, session_id, roster_entry_id=1, reason="휴대폰 배터리가 없었습니다"):
    # 요청마다 새 멤버십(닉네임이 겹쳐 엉뚱한 이유로 실패하지 않게 번호를 붙인다)
    membership_id = make_member(db, classroom_id, f"요청{next(_nick)}")
    return db.execute(
        "INSERT INTO attendance_requests(classroom_id, session_id, roster_entry_id, membership_id, reason, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (classroom_id, session_id, roster_entry_id, membership_id, reason, NOW),
    ).lastrowid


def decide(db, classroom_id, request_id, decision="approved"):
    db.execute(
        "INSERT INTO attendance_decisions(request_id, classroom_id, decision, github_id, decided_at) "
        "VALUES (?, ?, ?, 7, ?)",
        (request_id, classroom_id, decision, NOW),
    )


# --- 필수 회귀 (constitution 표시) ---------------------------------------------------


@pytest.mark.constitution
def test_c6_attendance_records_cannot_be_updated(db):
    c = make_classroom(db)
    s = make_session(db, c)
    code_mark(db, c, s)
    r = make_request(db, c, s, roster_entry_id=2)
    decide(db, c, r)
    for table in RECORD_TABLES:
        with pytest.raises(sqlite3.DatabaseError, match="추가만"):
            db.execute(f"UPDATE {table} SET classroom_id = classroom_id")


@pytest.mark.constitution
def test_c6_attendance_records_cannot_be_overwritten_with_replace(db):
    c = make_classroom(db)
    s = make_session(db, c)
    m = make_member(db, c)
    first = code_mark(db, c, s, roster_entry_id=1, membership_id=m, key="k1")
    r = make_request(db, c, s, roster_entry_id=2)
    decide(db, c, r, "approved")
    attempts = [
        (
            ("INSERT OR REPLACE INTO attendance_marks(classroom_id, session_id, roster_entry_id, membership_id, kind, "
            "actor_kind, actor_ref, client_key, created_at) VALUES (?, ?, 1, ?, 'code', 'student', ?, 'k2', ?)"),
            (c, s, m, m, NOW),
        ),
        (
            ("INSERT OR REPLACE INTO attendance_marks(id, classroom_id, session_id, roster_entry_id, kind, actor_kind, "
            "actor_ref, created_at) VALUES (?, ?, ?, 3, 'manual_absent', 'professor', 7, ?)"),
            (first, c, s, NOW),
        ),
        (
            ("INSERT OR REPLACE INTO attendance_requests(classroom_id, session_id, roster_entry_id, membership_id, "
            "reason, created_at) VALUES (?, ?, 2, ?, '바꾼 사유', ?)"),
            (c, s, m, NOW),
        ),
        (
            ("INSERT OR REPLACE INTO attendance_decisions(request_id, classroom_id, decision, github_id, decided_at) "
            "VALUES (?, ?, 'rejected', 7, ?)"),
            (r, c, NOW),
        ),
    ]
    for sql, args in attempts:
        with pytest.raises(sqlite3.IntegrityError, match="추가만"):
            db.execute(sql, args)
    assert db.execute("SELECT client_key FROM attendance_marks WHERE id = ?", (first,)).fetchone()[0] == "k1"
    assert db.execute("SELECT decision FROM attendance_decisions").fetchone()[0] == "approved"


@pytest.mark.constitution
def test_c6_only_the_purge_deletes_or_replaces_attendance_records():
    # 출석 기록은 보관 6개월 정리 때만 지운다(사용자 결정). 트리거로 지우기를 막으면 정리도 못 하므로 코드로 고정한다
    forbidden = re.compile(
        r"(DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO|UPDATE)\s+attendance_(marks|requests|decisions)",
        re.IGNORECASE,
    )
    # 표 이름을 변수로 넘기는 지우기(purge.py처럼 f"DELETE FROM {table}")도 잡으려고, 기록 표 이름과 지우기·덮어쓰기
    # 문장이 한 파일에 함께 있으면 정리 작업 밖에서는 거절한다
    # 출석 창은 연장·마감에서 고치는 상태 표라 UPDATE는 되지만, 지우기·덮어쓰기는 정리 작업만 한다(T012)
    window_forbidden = re.compile(
        r"(DELETE\s+FROM|REPLACE\s+INTO|INSERT\s+OR\s+REPLACE\s+INTO)\s+attendance_windows", re.IGNORECASE
    )
    names = re.compile(r"attendance_(marks|requests|decisions|windows)")
    destructive = re.compile(r"(DELETE\s+FROM|REPLACE)", re.IGNORECASE)
    offenders = []
    for path in sorted(APP_DIR.rglob("*.py")):
        if path.name == "purge.py":
            continue
        text = path.read_text(encoding="utf-8")
        if (
            forbidden.search(text)
            or window_forbidden.search(text)
            or (names.search(text) and destructive.search(text))
        ):
            offenders.append(path.name)
    assert offenders == [], f"출석 기록을 고치거나 지우는 코드가 정리 작업 밖에 있다: {offenders}"


@pytest.mark.constitution
def test_c7_attendance_tables_are_checked_for_personal_data(db):
    # test_schema.py의 C7 검사가 새 표를 실제로 훑는지(표 이름이 바뀌면 여기서 알린다)
    names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert set(ATTENDANCE_TABLES) <= names
    for table in ATTENDANCE_TABLES:
        cols = [r["name"] for r in db.execute(f"PRAGMA table_info({table})")]
        assert "classroom_id" in cols
        # test_schema.py보다 넓게 본다: 이 표들에는 이름 종류의 열이 하나도 없어야 한다(student_name 등)
        assert not [c for c in cols if re.search(r"(email|student|name|phone)", c)]


# --- 강좌 설정 ------------------------------------------------------------------------


def test_attendance_minutes_defaults_to_ten_and_allows_only_5_10_15(db):
    c = make_classroom(db)
    assert db.execute("SELECT attendance_minutes FROM classrooms WHERE id = ?", (c,)).fetchone()[0] == 10
    for minutes in (5, 15, 10):
        db.execute("UPDATE classrooms SET attendance_minutes = ? WHERE id = ?", (minutes, c))
    for bad in (0, 7, 20, None):
        with pytest.raises(sqlite3.IntegrityError):
            db.execute("UPDATE classrooms SET attendance_minutes = ? WHERE id = ?", (bad, c))


# --- 출석 받는 창 -----------------------------------------------------------------------


def test_only_one_unclosed_window_per_session(db):
    c = make_classroom(db)
    s, other = make_session(db, c, 1), db.execute(
        "INSERT INTO class_sessions(classroom_id, title, sort_order, created_at) VALUES (?, '2회차', 2, ?)", (c, NOW)
    ).lastrowid
    first = make_window(db, c, s)
    with pytest.raises(sqlite3.IntegrityError):
        make_window(db, c, s, nonce="1" * 32)
    make_window(db, c, other)  # 다른 회차는 따로 센다
    db.execute("UPDATE attendance_windows SET closed_at = ? WHERE id = ?", (LATER, first))
    make_window(db, c, s, nonce="2" * 32)  # 닫은 뒤에는 다시 받기
    make_window(db, c, s, closed_at=LATER, nonce="3" * 32)  # 닫힌 창은 몇 개든 된다


def test_window_must_close_after_it_opens_and_carry_a_hex_nonce(db):
    c = make_classroom(db)
    s = make_session(db, c)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO attendance_windows(classroom_id, session_id, nonce, opened_at, closes_at, opened_by) "
            "VALUES (?, ?, ?, ?, ?, 'start')",
            (c, s, "0" * 32, LATER, NOW),
        )
    with pytest.raises(sqlite3.IntegrityError):  # 같은 순간은 안 된다
        db.execute(
            "INSERT INTO attendance_windows(classroom_id, session_id, nonce, opened_at, closes_at, opened_by) "
            "VALUES (?, ?, ?, ?, ?, 'start')",
            (c, s, "0" * 32, NOW, NOW),
        )
    for bad_nonce in ("", "abc", "g" * 32, "0" * 31, "0" * 33):
        with pytest.raises(sqlite3.IntegrityError):
            make_window(db, c, s, nonce=bad_nonce)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO attendance_windows(classroom_id, session_id, nonce, opened_at, closes_at, opened_by) "
            "VALUES (?, ?, ?, ?, ?, 'manual')",
            (c, s, "0" * 32, NOW, LATER),
        )


def test_window_session_must_belong_to_the_same_classroom(db):
    a, b = make_classroom(db, "A"), make_classroom(db, "B")
    s = make_session(db, a)
    with pytest.raises(sqlite3.IntegrityError):
        make_window(db, b, s)


# --- 출석 기록 --------------------------------------------------------------------------


def test_one_code_attendance_per_student_per_session(db):
    # AC16: 다른 기기(다른 멤버십 요청이 와도 같은 명단 항목)로 다시 넣어도 하나
    c = make_classroom(db)
    s1, s2 = make_session(db, c, 1), db.execute(
        "INSERT INTO class_sessions(classroom_id, title, sort_order, created_at) VALUES (?, '2회차', 2, ?)", (c, NOW)
    ).lastrowid
    code_mark(db, c, s1, roster_entry_id=1, key="a")
    with pytest.raises(sqlite3.IntegrityError):
        code_mark(db, c, s1, roster_entry_id=1, key="b")
    code_mark(db, c, s2, roster_entry_id=1, key="c")  # 다른 회차
    code_mark(db, c, s1, roster_entry_id=2, key="d")  # 다른 학생
    manual_mark(db, c, s1, roster_entry_id=1, kind="manual_absent")  # 교수의 바꾸기는 몇 번이든 쌓인다
    manual_mark(db, c, s1, roster_entry_id=1, kind="manual_present")


def test_mark_kind_must_match_who_did_it(db):
    c = make_classroom(db)
    s = make_session(db, c)
    m = make_member(db, c)
    base = (
        "INSERT INTO attendance_marks(classroom_id, session_id, roster_entry_id, membership_id, kind, actor_kind, "
        "actor_ref, request_id, client_key, created_at) VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?)"
    )
    bad = [
        (None, "code", "student", 1, None, "k"),  # 코드 출석에 멤버십이 없다
        (m, "code", "student", m, None, None),  # 코드 출석에 client_key가 없다
        (m, "code", "professor", 7, None, "k"),  # 코드 출석은 학생만
        (None, "manual_present", "student", m, None, None),  # 직접 바꾸기는 교수만
        (None, "request_approved", "professor", 7, None, None),  # 승인 기록에 요청이 없다
        (None, "manual_present", "professor", 7, None, "k"),  # client_key는 코드 출석에만
        (m, "code", "student", m + 100, None, "k"),  # 코드 출석의 행위자는 그 멤버십이다
        (m, "code", "professor", m, None, "k"),  # 코드 출석을 교수로 적을 수 없다
        (m, "code", "student", m, None, ""),  # 빈 client_key
        (m, "code", "student", m, None, "k" * 65),  # client_key는 64자까지
        (m, "manual_present", "professor", 7, None, None),  # 직접 바꾸기에 멤버십을 붙이지 않는다
        (None, "manual_present", "admin", 7, None, None),  # 없는 행위자 종류
        (None, "late", "professor", 7, None, None),  # 없는 종류
        (None, "manual_absent", "professor", None, None, None),  # 행위자가 없다
    ]
    for membership, kind, actor_kind, actor_ref, request_id, key in bad:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(base, (c, s, membership, kind, actor_kind, actor_ref, request_id, key, NOW))
    r = make_request(db, c, s)
    with pytest.raises(sqlite3.IntegrityError):  # 요청 번호는 승인 기록에만
        db.execute(base, (c, s, None, "manual_present", "professor", 7, r, None, NOW))
    db.execute(base, (c, s, m, "code", "student", m, None, "k" * 64, NOW))  # 64자는 된다


def test_marks_point_to_a_session_and_membership_of_the_same_classroom(db):
    a, b = make_classroom(db, "A"), make_classroom(db, "B")
    sa = make_session(db, a)
    with pytest.raises(sqlite3.IntegrityError):
        manual_mark(db, b, sa)
    other_member = make_member(db, b)
    with pytest.raises(sqlite3.IntegrityError):
        code_mark(db, a, sa, membership_id=other_member)


# --- 수기 요청과 처리 --------------------------------------------------------------------


def test_one_request_per_student_per_session_and_reason_is_1_to_200_chars(db):
    c = make_classroom(db)
    s = make_session(db, c)
    make_request(db, c, s, roster_entry_id=1)
    with pytest.raises(sqlite3.IntegrityError):
        make_request(db, c, s, roster_entry_id=1)
    make_request(db, c, s, roster_entry_id=2, reason="가" * 200)
    for n, bad in enumerate(("", "   ", "가" * 201, " " + "가" * 200), start=3):
        with pytest.raises(sqlite3.IntegrityError):
            make_request(db, c, s, roster_entry_id=n, reason=bad)


def test_request_points_to_a_session_and_membership_of_the_same_classroom(db):
    a, b = make_classroom(db, "A"), make_classroom(db, "B")
    sa, sb = make_session(db, a), make_session(db, b)
    member_b = make_member(db, b)
    sql = (
        "INSERT INTO attendance_requests(classroom_id, session_id, roster_entry_id, membership_id, reason, created_at) "
        "VALUES (?, ?, 1, ?, '늦었습니다', ?)"
    )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (b, sa, member_b, NOW))  # 다른 강좌의 회차
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (a, sa, member_b, NOW))  # 다른 강좌의 멤버십
    db.execute(sql, (b, sb, member_b, NOW))


def test_a_request_is_decided_once(db):
    # AC19: 승인·거절은 되돌리지 않는다
    c = make_classroom(db)
    s = make_session(db, c)
    r = make_request(db, c, s)
    decide(db, c, r, "approved")
    with pytest.raises(sqlite3.IntegrityError):
        decide(db, c, r, "rejected")
    with pytest.raises(sqlite3.IntegrityError):
        decide(db, c, make_request(db, c, s, roster_entry_id=2), "maybe")


def test_decision_and_approval_mark_point_to_a_request_of_the_same_classroom(db):
    a, b = make_classroom(db, "A"), make_classroom(db, "B")
    sa, sb = make_session(db, a), make_session(db, b)
    r = make_request(db, a, sa)
    with pytest.raises(sqlite3.IntegrityError):
        decide(db, b, r)
    with pytest.raises(sqlite3.IntegrityError):
        manual_mark(db, b, sb, kind="request_approved", request_id=r)
    with pytest.raises(sqlite3.IntegrityError):
        decide(db, a, 999)
    manual_mark(db, a, sa, kind="request_approved", request_id=r)


def test_approval_mark_must_match_its_request(db):
    c = make_classroom(db)
    s1 = make_session(db, c, 1)
    s2 = db.execute(
        "INSERT INTO class_sessions(classroom_id, title, sort_order, created_at) VALUES (?, '2회차', 2, ?)", (c, NOW)
    ).lastrowid
    r = make_request(db, c, s1, roster_entry_id=1)
    with pytest.raises(sqlite3.IntegrityError):
        manual_mark(db, c, s2, roster_entry_id=1, kind="request_approved", request_id=r)  # 다른 회차
    with pytest.raises(sqlite3.IntegrityError):
        manual_mark(db, c, s1, roster_entry_id=2, kind="request_approved", request_id=r)  # 다른 학생
    manual_mark(db, c, s1, roster_entry_id=1, kind="request_approved", request_id=r)
    with pytest.raises(sqlite3.IntegrityError):
        manual_mark(db, c, s1, roster_entry_id=1, kind="request_approved", request_id=r)  # 승인 기록은 하나


def test_window_cannot_close_before_it_opens(db):
    c = make_classroom(db)
    s = make_session(db, c)
    with pytest.raises(sqlite3.IntegrityError):
        make_window(db, c, s, closed_at="2026-03-01T08:59:00+00:00")
    make_window(db, c, s, closed_at=NOW)


def test_records_can_still_be_deleted_for_the_retention_purge(db):
    # 사용자 결정: 보관 6개월 정리 때 지운다. 순서는 처리 → 기록 → 요청 → 창
    c = make_classroom(db)
    s = make_session(db, c)
    make_window(db, c, s)
    r = make_request(db, c, s)
    decide(db, c, r)
    manual_mark(db, c, s, kind="request_approved", request_id=r)
    for table in ("attendance_decisions", "attendance_marks", "attendance_requests", "attendance_windows"):
        db.execute(f"DELETE FROM {table} WHERE classroom_id = ?", (c,))
        assert db.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0


def test_upgrading_from_0003_gives_existing_classrooms_ten_minutes(tmp_path):
    import shutil

    old = tmp_path / "old"
    old.mkdir()
    for name in ("0001_core_schema.sql", "0002_class_sessions.sql", "0003_deck_visibility.sql"):
        shutil.copy(MIGRATIONS_DIR / name, old / name)
    clock = ManualClock(datetime(2026, 3, 1, 9, tzinfo=UTC))
    conn = connect(tmp_path / "app.db")
    migrate(conn, old, clock)
    c = make_classroom(conn)
    assert migrate(conn, MIGRATIONS_DIR, clock)[0] == "0004_attendance"
    assert conn.execute("SELECT attendance_minutes FROM classrooms WHERE id = ?", (c,)).fetchone()[0] == 10
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []
    conn.close()


def test_migration_applies_once_on_an_existing_database(tmp_path):
    path = tmp_path / "app.db"
    clock = ManualClock(datetime(2026, 3, 1, 9, tzinfo=UTC))
    conn = connect(path)
    migrate(conn, MIGRATIONS_DIR, clock)
    c = make_classroom(conn)
    conn.execute("UPDATE classrooms SET attendance_minutes = 15 WHERE id = ?", (c,))
    conn.close()
    conn = connect(path)
    migrate(conn, MIGRATIONS_DIR, clock)
    assert conn.execute("SELECT attendance_minutes FROM classrooms WHERE id = ?", (c,)).fetchone()[0] == 15
    assert conn.execute("SELECT count(*) FROM schema_migrations WHERE version LIKE '0004%'").fetchone()[0] == 1
    conn.close()
