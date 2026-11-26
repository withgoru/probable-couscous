"""핵심 스키마(0001)와 constitution 필수 회귀 테스트.

C5 강의실 단위 구분, C6 이벤트는 추가만, C7 정체성 3층 분리.
새 표를 만들면 아래 분류(계정층 / 강좌 소속 / 개인정보 허용)에 넣어야 테스트가 통과한다.
"""

import re
import sqlite3
from datetime import UTC, datetime

import pytest

from app.clock import ManualClock
from app.db import MIGRATIONS_DIR, connect, migrate

NOW = "2026-03-01T09:00:00+00:00"

# 정의상 강좌를 넘나드는 표(C7 1층). plan의 C5 해석(사용자 결정 2026-11-17)에 따라 classroom_id가 없다.
ACCOUNT_LAYER = {"professors", "professor_sessions", "accounts", "devices", "device_logins"}
# 강좌에 속한 표. 모두 classroom_id를 가진다(C5).
CLASSROOM_SCOPED = {
    "roster_entries",
    "join_requests",
    "memberships",
    "member_identities",
    "classroom_verifications",
    "login_challenges",
    "mail_outbox",
    "events",
    # 002 회차·슬라이드·보낸 항목. 학생을 가리키는 열이 없다
    "class_sessions",
    "decks",
    "session_items",
}
SESSION_TABLES = {"class_sessions", "decks", "session_items"}
# 이메일·이름·학번을 가져도 되는 표. 보관 후 6개월 정리 작업(C11)이 비우는 대상이다.
PERSONAL_DATA = {"accounts", "roster_entries", "join_requests", "login_challenges", "mail_outbox"}
FORBIDDEN_COLUMN = re.compile(r"(email|student_no|student_id|phone|^name$|real_name)")
SYSTEM_TABLES = {"schema_migrations"}


@pytest.fixture
def db(tmp_path):
    conn = connect(tmp_path / "app.db")
    migrate(conn, MIGRATIONS_DIR, ManualClock(datetime(2026, 3, 1, 9, tzinfo=UTC)))
    yield conn
    conn.close()


def tables(conn) -> set[str]:
    rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")
    return {r["name"] for r in rows} - SYSTEM_TABLES


def columns(conn, table: str) -> list[str]:
    return [r["name"] for r in conn.execute(f"PRAGMA table_info({table})")]


def make_professor(db, github_id=1):
    db.execute("INSERT INTO professors(github_id, login, created_at) VALUES (?, 'prof', ?)", (github_id, NOW))
    return github_id


def make_classroom(db, owner=None, name="알고리즘", token=None):
    owner = owner or make_professor(db, github_id=abs(hash(name)) % 10_000 + 2)
    cur = db.execute(
        "INSERT INTO classrooms(owner_github_id, name, invite_token, created_at) VALUES (?, ?, ?, ?)",
        (owner, name, token or f"tok-{name}", NOW),
    )
    return cur.lastrowid


def make_roster(db, classroom_id, student_no="2024001", email="a@x.kr"):
    cur = db.execute(
        "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at) VALUES (?, ?, '홍길동', ?, ?)",
        (classroom_id, student_no, email, NOW),
    )
    return cur.lastrowid


def make_membership(db, classroom_id, nickname="용감한 수달"):
    cur = db.execute(
        "INSERT INTO memberships(classroom_id, nickname, created_at) VALUES (?, ?, ?)",
        (classroom_id, nickname, NOW),
    )
    return cur.lastrowid


def make_account(db, email="a@x.kr"):
    return db.execute("INSERT INTO accounts(email_norm, created_at) VALUES (?, ?)", (email, NOW)).lastrowid


# --- 필수 회귀 테스트 (constitution 표시) ---------------------------------------


@pytest.mark.constitution
def test_c7_activity_tables_have_no_email_name_or_student_number_columns(db):
    # 개인정보를 둘 수 있는 표 밖의 모든 표(멤버십, 이벤트, 앞으로 생길 채팅·출석·퀴즈 표)가 대상이다
    checked = tables(db) - PERSONAL_DATA - {"classrooms"}
    assert {"memberships", "events"} | SESSION_TABLES <= checked
    for table in sorted(checked):
        bad = [c for c in columns(db, table) if FORBIDDEN_COLUMN.search(c)]
        assert bad == [], f"{table}에 개인정보 열이 있다: {bad}"


@pytest.mark.constitution
def test_c7_only_member_identities_links_memberships_to_people(db):
    assert {"memberships", "member_identities", "accounts", "roster_entries"} <= tables(db)
    allowed_to_account = {"member_identities", "device_logins"}
    allowed_to_roster = {"member_identities"}
    for table in tables(db):
        refs = {r["table"] for r in db.execute(f"PRAGMA foreign_key_list({table})")}
        if "accounts" in refs:
            assert table in allowed_to_account, f"{table}이 accounts를 참조한다"
        if "roster_entries" in refs:
            assert table in allowed_to_roster, f"{table}이 roster_entries를 참조한다"
    assert "account_id" not in columns(db, "memberships")
    assert "roster_entry_id" not in columns(db, "memberships")


@pytest.mark.constitution
def test_c6_events_cannot_be_updated_or_deleted(db):
    cid = make_classroom(db)
    db.execute(
        "INSERT INTO events(classroom_id, type, actor_kind, payload, created_at) VALUES (?, 'x', 'system', '{}', ?)",
        (cid, NOW),
    )
    with pytest.raises(sqlite3.DatabaseError, match="추가만"):
        db.execute("UPDATE events SET type = 'y'")
    with pytest.raises(sqlite3.DatabaseError, match="추가만"):
        db.execute("DELETE FROM events")
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1


@pytest.mark.constitution
def test_c6_events_cannot_be_overwritten_with_replace(db):
    cid = make_classroom(db)
    db.execute(
        "INSERT INTO events(id, classroom_id, type, actor_kind, payload, created_at) VALUES (1, ?, 'x', 'system', '{}', ?)",
        (cid, NOW),
    )
    with pytest.raises(sqlite3.DatabaseError):
        db.execute(
            "INSERT OR REPLACE INTO events(id, classroom_id, type, actor_kind, payload, created_at) "
            "VALUES (1, ?, 'forged', 'system', '{}', ?)",
            (cid, NOW),
        )
    assert db.execute("SELECT type FROM events WHERE id = 1").fetchone()["type"] == "x"


@pytest.mark.constitution
def test_c5_every_table_is_classified_and_classroom_tables_carry_classroom_id(db):
    classified = ACCOUNT_LAYER | CLASSROOM_SCOPED | {"classrooms"}
    unclassified = tables(db) - classified
    assert unclassified == set(), f"계정층인지 강좌 소속인지 분류되지 않은 표: {unclassified}"
    missing = tables(db) & classified
    assert missing == classified, f"plan에 있는 표가 없다: {classified - missing}"
    for table in sorted(CLASSROOM_SCOPED):
        cols = {r["name"]: r for r in db.execute(f"PRAGMA table_info({table})")}
        assert "classroom_id" in cols, f"{table}에 classroom_id가 없다"
        assert cols["classroom_id"]["notnull"] == 1, f"{table}.classroom_id가 비어 있을 수 있다"
    for table in sorted(ACCOUNT_LAYER):
        assert "classroom_id" not in columns(db, table), f"{table}은 계정층이라 classroom_id가 없어야 한다"
    assert "organization_id" in columns(db, "classrooms")  # 조직 단위는 자리만(C5)


# --- 구조 테스트 --------------------------------------------------------------


def test_migration_is_applied_once_and_recorded(db):
    versions = [r["version"] for r in db.execute("SELECT version FROM schema_migrations")]
    assert versions == ["0001_core_schema", "0002_class_sessions", "0003_deck_visibility"]


def test_login_challenges_do_not_store_the_code(db):
    # 코드는 서버 비밀값과 챌린지 번호에서 계산한다. 저장하는 열이 있으면 안 된다
    assert not [c for c in columns(db, "login_challenges") if "code" in c]
    assert "nonce" in columns(db, "login_challenges")


def test_cross_classroom_identity_link_is_refused(db):
    a, b = make_classroom(db, name="A"), make_classroom(db, name="B")
    membership_in_a = make_membership(db, a)
    roster_in_a = make_roster(db, a)
    account = make_account(db)
    with pytest.raises(sqlite3.IntegrityError, match="FOREIGN KEY"):
        db.execute(
            "INSERT INTO member_identities(membership_id, classroom_id, account_id, roster_entry_id) VALUES (?, ?, ?, ?)",
            (membership_in_a, b, account, roster_in_a),
        )
    db.execute(  # 같은 강좌끼리는 연결된다
        "INSERT INTO member_identities(membership_id, classroom_id, account_id, roster_entry_id) VALUES (?, ?, ?, ?)",
        (membership_in_a, a, account, roster_in_a),
    )


def test_one_membership_per_account_per_classroom(db):
    a = make_classroom(db, name="A")
    account = make_account(db)
    r1, r2 = make_roster(db, a, "1", "a@x.kr"), make_roster(db, a, "2", "b@x.kr")
    m1, m2 = make_membership(db, a, "수달"), make_membership(db, a, "너구리")
    sql = "INSERT INTO member_identities(membership_id, classroom_id, account_id, roster_entry_id) VALUES (?, ?, ?, ?)"
    db.execute(sql, (m1, a, account, r1))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (m2, a, account, r2))


def test_roster_email_and_student_number_are_unique_among_live_entries_only(db):
    c = make_classroom(db)
    first = make_roster(db, c, "100", "kim@x.kr")
    with pytest.raises(sqlite3.IntegrityError):
        make_roster(db, c, "101", "kim@x.kr")
    with pytest.raises(sqlite3.IntegrityError):
        make_roster(db, c, "100", "other@x.kr")
    db.execute("UPDATE roster_entries SET removed_at = ? WHERE id = ?", (NOW, first))
    make_roster(db, c, "100", "kim@x.kr")  # 뺀 뒤에는 같은 이메일·학번을 다시 등록할 수 있다
    other = make_classroom(db, name="다른강좌")
    make_roster(db, other, "100", "kim@x.kr")  # 다른 강좌는 따로 센다


def test_only_one_pending_join_request_per_email_per_classroom(db):
    c = make_classroom(db)
    sql = "INSERT INTO join_requests(classroom_id, email_norm, name, student_no, created_at) VALUES (?, ?, '이름', '1', ?)"
    db.execute(sql, (c, "new@x.kr", NOW))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(sql, (c, "new@x.kr", NOW))
    db.execute("UPDATE join_requests SET status = 'rejected', decided_at = ?", (NOW,))
    db.execute(sql, (c, "new@x.kr", NOW))  # 처리된 뒤에는 다시 요청할 수 있다


def test_nickname_is_unique_per_classroom_but_may_repeat_across_classrooms(db):
    a, b = make_classroom(db, name="A"), make_classroom(db, name="B")
    make_membership(db, a, "수달")
    with pytest.raises(sqlite3.IntegrityError):
        make_membership(db, a, "수달")
    make_membership(db, b, "수달")


def test_invite_token_is_unique_and_classroom_name_cannot_be_blank(db):
    make_classroom(db, name="A", token="same")
    with pytest.raises(sqlite3.IntegrityError):
        make_classroom(db, name="B", token="same")
    with pytest.raises(sqlite3.IntegrityError):
        make_classroom(db, name="   ", token="t3")


def test_status_columns_only_accept_known_values(db):
    c = make_classroom(db)
    with pytest.raises(sqlite3.IntegrityError):
        db.execute("UPDATE classrooms SET status = 'deleted' WHERE id = ?", (c,))
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO events(classroom_id, type, actor_kind, payload, created_at) VALUES (?, 'x', 'robot', '{}', ?)",
            (c, NOW),
        )
    with pytest.raises(sqlite3.IntegrityError):
        db.execute(
            "INSERT INTO events(classroom_id, type, actor_kind, payload, created_at) VALUES (?, 'x', 'system', 'not json', ?)",
            (c, NOW),
        )


def test_purging_personal_data_does_not_touch_memberships_or_events(db):
    # C11: 정리 작업은 개인정보 표만 비우고 가명(memberships)과 events는 남긴다. 순서대로 지울 수 있어야 한다
    c = make_classroom(db)
    roster, account = make_roster(db, c), make_account(db)
    m = make_membership(db, c)
    db.execute(
        "INSERT INTO member_identities(membership_id, classroom_id, account_id, roster_entry_id) VALUES (?, ?, ?, ?)",
        (m, c, account, roster),
    )
    db.execute(
        "INSERT INTO events(classroom_id, type, actor_kind, subject_roster_entry_id, payload, created_at) "
        "VALUES (?, 'code_revealed', 'professor', ?, '{}', ?)",
        (c, roster, NOW),
    )
    db.execute("DELETE FROM member_identities")
    db.execute("DELETE FROM roster_entries")
    db.execute("DELETE FROM accounts")
    assert db.execute("SELECT COUNT(*) FROM memberships").fetchone()[0] == 1
    assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 1
