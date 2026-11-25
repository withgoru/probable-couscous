"""002 T002: 회차 스키마(0002). 회차, 슬라이드 묶음, 보낸 항목.

C7 필수 회귀(새 표에 개인정보 열 없음)와 C5 분류는 `test_schema.py`가 모든 표에 대해 확인한다.
여기서는 DB가 직접 막아야 하는 규칙을 본다(C13: 경쟁 상태도 저장소가 막는다).
"""

import sqlite3
from datetime import UTC, datetime

import pytest

from app.clock import ManualClock
from app.db import MIGRATIONS_DIR, connect, migrate

NOW = "2026-03-01T09:00:00+00:00"


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


def make_session(db, classroom_id, title="3주차 1회차", order=1, status="scheduled"):
    return db.execute(
        "INSERT INTO class_sessions(classroom_id, title, sort_order, status, created_at) VALUES (?, ?, ?, ?, ?)",
        (classroom_id, title, order, status, NOW),
    ).lastrowid


def make_deck(db, classroom_id, session_id, removed_at=None):
    return db.execute(
        "INSERT INTO decks(classroom_id, session_id, original_name, slide_count, size_bytes, uploaded_at, removed_at) "
        "VALUES (?, ?, 'week3.zip', 4, 1000, ?, ?)",
        (classroom_id, session_id, NOW, removed_at),
    ).lastrowid


def make_item(db, classroom_id, session_id, key="k1", body="프롬프트", url=None):
    return db.execute(
        "INSERT INTO session_items(classroom_id, session_id, body, url, client_key, created_at) VALUES (?, ?, ?, ?, ?, ?)",
        (classroom_id, session_id, body, url, key, NOW),
    ).lastrowid


# --- 회차 ---------------------------------------------------------------------------


def test_new_session_starts_scheduled_at_the_first_slide(db):
    c = make_classroom(db)
    s = db.execute("SELECT * FROM class_sessions WHERE id = ?", (make_session(db, c),)).fetchone()
    assert s["status"] == "scheduled"
    assert (s["current_slide"], s["current_click"], s["furthest_slide"], s["furthest_click"]) == (1, 0, 1, 0)
    assert s["version"] == 0
    assert s["first_started_at"] is None and s["started_at"] is None and s["ended_at"] is None


def test_only_one_live_session_per_classroom(db):
    # AC10: 두 화면이 동시에 '수업 시작'을 눌러도 DB가 하나만 받아들인다
    a, b = make_classroom(db, "A"), make_classroom(db, "B")
    make_session(db, a, "1회차", 1, "live")
    with pytest.raises(sqlite3.IntegrityError):
        make_session(db, a, "2회차", 2, "live")
    second = make_session(db, a, "2회차", 2)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE class_sessions SET status = 'live' WHERE id = ?", (second,))
    make_session(db, b, "1회차", 1, "live")  # 다른 강좌는 따로 센다
    make_session(db, a, "3회차", 3, "ended")  # 종료 회차는 몇 개든 된다
    make_session(db, a, "4회차", 4, "ended")


def test_session_title_is_1_to_40_characters_and_may_repeat(db):
    c = make_classroom(db)
    make_session(db, c, "가" * 40, 1)
    make_session(db, c, "가" * 40, 2)  # 같은 강좌에서 이름이 겹쳐도 된다(AC2)
    for bad in ("", "   ", "가" * 41):
        with pytest.raises(sqlite3.IntegrityError):
            make_session(db, c, bad, 3)


def test_session_status_only_accepts_known_values(db):
    c = make_classroom(db)
    with pytest.raises(sqlite3.IntegrityError):
        make_session(db, c, status="paused")


def test_positions_are_valid_and_furthest_never_behind_current(db):
    c = make_classroom(db)
    s = make_session(db, c)
    db.execute(
        "UPDATE class_sessions SET current_slide = 2, current_click = 1, furthest_slide = 4, furthest_click = 0 WHERE id = ?",
        (s,),
    )  # 교수가 4번까지 갔다가 2번으로 돌아옴
    for current, furthest in [((0, 0), (1, 0)), ((1, -1), (1, 0)), ((3, 0), (2, 5)), ((2, 2), (2, 1))]:
        with pytest.raises(sqlite3.IntegrityError):
            db.execute(
                "UPDATE class_sessions SET current_slide = ?, current_click = ?, furthest_slide = ?, furthest_click = ? "
                "WHERE id = ?",
                (*current, *furthest, s),
            )


# --- 슬라이드 묶음 ---------------------------------------------------------------------


def test_a_session_has_at_most_one_live_deck(db):
    c = make_classroom(db)
    s = make_session(db, c)
    old = make_deck(db, c, s)
    with pytest.raises(sqlite3.IntegrityError):
        make_deck(db, c, s)
    db.execute("UPDATE decks SET removed_at = ? WHERE id = ?", (NOW, old))
    make_deck(db, c, s)  # 이전 묶음을 지운 뒤에는 새 묶음을 둘 수 있다(바꾸기)


def test_deck_must_belong_to_a_session_of_the_same_classroom(db):
    a, b = make_classroom(db, "A"), make_classroom(db, "B")
    session_in_a = make_session(db, a)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        make_deck(db, b, session_in_a)


def test_deck_needs_at_least_one_slide(db):
    c = make_classroom(db)
    s = make_session(db, c)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO decks(classroom_id, session_id, original_name, slide_count, size_bytes, uploaded_at) "
            "VALUES (?, ?, 'x.zip', 0, 10, ?)",
            (c, s, NOW),
        )


# --- 보낸 항목 -------------------------------------------------------------------------


def test_same_client_key_is_stored_once_per_session(db):
    # 오류 동작 "한 번 누른 보내기는 두 번 저장되지 않는다"
    c = make_classroom(db)
    s1, s2 = make_session(db, c, "1회차", 1), make_session(db, c, "2회차", 2)
    make_item(db, c, s1, "same")
    with pytest.raises(sqlite3.IntegrityError):
        make_item(db, c, s1, "same")
    make_item(db, c, s2, "same")  # 다른 회차는 따로 센다


def test_item_has_text_or_link_and_the_link_is_http(db):
    c = make_classroom(db)
    s = make_session(db, c)
    make_item(db, c, s, "a", body="글만")
    make_item(db, c, s, "b", body=None, url="https://example.com/x")
    make_item(db, c, s, "c", body="글과 링크", url="http://example.com")
    make_item(db, c, s, "d", body="가" * 2000)
    for key, body, url in [
        ("e", None, None),
        ("f", "", None),
        ("g", "가" * 2001, None),
        ("h", None, "javascript:alert(1)"),
        ("i", None, "ftp://example.com"),
    ]:
        with pytest.raises(sqlite3.IntegrityError):
            make_item(db, c, s, key, body=body, url=url)


def test_item_must_belong_to_a_session_of_the_same_classroom(db):
    a, b = make_classroom(db, "A"), make_classroom(db, "B")
    session_in_a = make_session(db, a)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        make_item(db, b, session_in_a)


def test_migrations_apply_again_without_change(db):
    before = db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    migrate(db, MIGRATIONS_DIR, ManualClock(datetime(2026, 3, 2, 9, tzinfo=UTC)))
    after = db.execute("SELECT sql FROM sqlite_master ORDER BY name").fetchall()
    assert [r[0] for r in before] == [r[0] for r in after]
