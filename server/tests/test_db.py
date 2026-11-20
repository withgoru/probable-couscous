import sqlite3
from datetime import UTC, datetime

import pytest

from app.clock import ManualClock
from app.db import MigrationError, connect, migrate, transaction

CLOCK = ManualClock(datetime(2026, 3, 1, 9, 0, tzinfo=UTC))


def write(dir_, name, sql):
    dir_.mkdir(parents=True, exist_ok=True)
    (dir_ / name).write_text(sql, encoding="utf-8")


@pytest.fixture
def conn(tmp_path):
    c = connect(tmp_path / "sub" / "app.db")
    yield c
    c.close()


# --- 연결 ---------------------------------------------------------------


def test_connect_creates_parent_dir_and_sets_pragmas(tmp_path):
    c = connect(tmp_path / "a" / "b" / "app.db")
    assert (tmp_path / "a" / "b" / "app.db").exists()
    assert c.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert c.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
    assert c.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    c.close()


def test_rows_can_be_read_by_column_name(conn):
    row = conn.execute("SELECT 1 AS one").fetchone()
    assert row["one"] == 1


# --- 트랜잭션 -------------------------------------------------------------


def test_transaction_commits_on_success_and_rolls_back_on_error(conn):
    conn.execute("CREATE TABLE t(x INTEGER)")
    with transaction(conn):
        conn.execute("INSERT INTO t VALUES (1)")
    with pytest.raises(RuntimeError), transaction(conn):
        conn.execute("INSERT INTO t VALUES (2)")
        raise RuntimeError("boom")
    assert [r["x"] for r in conn.execute("SELECT x FROM t")] == [1]


def test_second_writer_waits_then_fails_while_first_holds_the_write_lock(tmp_path):
    path = tmp_path / "app.db"
    a = connect(path)
    b = connect(path, busy_timeout_ms=50)
    a.execute("CREATE TABLE t(x INTEGER)")
    with transaction(a):
        a.execute("INSERT INTO t VALUES (1)")
        with pytest.raises(sqlite3.OperationalError, match="locked"), transaction(b):
            pass
    with transaction(b):  # 첫 쓰기가 끝나면 두 번째가 쓸 수 있다
        b.execute("INSERT INTO t VALUES (2)")
    a.close()
    b.close()


# --- 마이그레이션 ---------------------------------------------------------


def test_migrations_apply_in_number_order_and_are_recorded(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "0002_b.sql", "CREATE TABLE b(id INTEGER PRIMARY KEY, a_id INTEGER REFERENCES a(id));")
    write(d, "0001_a.sql", "CREATE TABLE a(id INTEGER PRIMARY KEY);")
    applied = migrate(conn, d, CLOCK)
    assert applied == ["0001_a", "0002_b"]
    rows = conn.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall()
    assert [r["version"] for r in rows] == ["0001_a", "0002_b"]
    assert rows[0]["applied_at"] == "2026-03-01T09:00:00+00:00"


def test_running_twice_gives_the_same_result(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "0001_a.sql", "CREATE TABLE a(id INTEGER PRIMARY KEY);")
    assert migrate(conn, d, CLOCK) == ["0001_a"]
    assert migrate(conn, d, CLOCK) == []
    assert conn.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 1


def test_new_migration_is_applied_on_next_run_only(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "0001_a.sql", "CREATE TABLE a(id INTEGER PRIMARY KEY);")
    migrate(conn, d, CLOCK)
    write(d, "0002_b.sql", "CREATE TABLE b(id INTEGER PRIMARY KEY);")
    assert migrate(conn, d, CLOCK) == ["0002_b"]


def test_trigger_with_inner_semicolons_is_one_statement(conn, tmp_path):
    d = tmp_path / "m"
    write(
        d,
        "0001_events.sql",
        """
        CREATE TABLE events(id INTEGER PRIMARY KEY, body TEXT);
        CREATE TRIGGER events_no_update BEFORE UPDATE ON events
        BEGIN
            SELECT RAISE(ABORT, 'events는 추가만 가능합니다');
        END;
        """,
    )
    migrate(conn, d, CLOCK)
    conn.execute("INSERT INTO events(body) VALUES ('x')")
    with pytest.raises(sqlite3.DatabaseError, match="추가만"):
        conn.execute("UPDATE events SET body = 'y'")


def test_failing_migration_leaves_no_trace_and_stops_later_ones(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "0001_ok.sql", "CREATE TABLE ok(id INTEGER);")
    write(d, "0002_bad.sql", "CREATE TABLE half(id INTEGER); INSERT INTO nope VALUES (1);")
    write(d, "0003_later.sql", "CREATE TABLE later(id INTEGER);")
    with pytest.raises(MigrationError, match="0002_bad"):
        migrate(conn, d, CLOCK)
    tables = {r["name"] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "ok" in tables
    assert "half" not in tables and "later" not in tables
    versions = [r["version"] for r in conn.execute("SELECT version FROM schema_migrations")]
    assert versions == ["0001_ok"]


def test_editing_an_applied_migration_is_refused(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "0001_a.sql", "CREATE TABLE a(id INTEGER);")
    migrate(conn, d, CLOCK)
    write(d, "0001_a.sql", "CREATE TABLE a(id INTEGER, extra TEXT);")
    with pytest.raises(MigrationError, match="0001_a.*바뀌었습니다"):
        migrate(conn, d, CLOCK)


def test_database_newer_than_code_is_refused(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "0001_a.sql", "CREATE TABLE a(id INTEGER);")
    write(d, "0002_b.sql", "CREATE TABLE b(id INTEGER);")
    migrate(conn, d, CLOCK)
    (d / "0002_b.sql").unlink()
    with pytest.raises(MigrationError, match="0002_b.*없습니다"):
        migrate(conn, d, CLOCK)


def test_bad_file_name_is_refused(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "create_users.sql", "CREATE TABLE u(id INTEGER);")
    with pytest.raises(MigrationError, match="create_users.sql"):
        migrate(conn, d, CLOCK)


def test_duplicate_number_is_refused(conn, tmp_path):
    d = tmp_path / "m"
    write(d, "0001_a.sql", "CREATE TABLE a(id INTEGER);")
    write(d, "0001_b.sql", "CREATE TABLE b(id INTEGER);")
    with pytest.raises(MigrationError, match="0001"):
        migrate(conn, d, CLOCK)


def test_missing_directory_means_nothing_to_apply(conn, tmp_path):
    assert migrate(conn, tmp_path / "does-not-exist", CLOCK) == []


# --- 요청마다 여는 연결 ------------------------------------------------------------


def test_get_db_gives_a_connection_per_request_and_closes_it(tmp_path):
    from types import SimpleNamespace

    from app.config import Settings
    from app.db import get_db

    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(
        settings=Settings(database_path=tmp_path / "req.db"))))
    gen = get_db(request)
    conn = next(gen)
    assert conn.execute("SELECT 1 AS one").fetchone()["one"] == 1
    with pytest.raises(StopIteration):
        next(gen)
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_connection_can_be_used_from_another_thread(tmp_path):
    # FastAPI는 같은 요청의 의존성과 처리 함수를 서로 다른 스레드에서 실행할 수 있다.
    # 연결은 요청 하나가 차례로 쓰므로 동시에 쓰이지 않는다.
    import threading

    conn = connect(tmp_path / "thread.db")
    out: list[int] = []
    t = threading.Thread(target=lambda: out.append(conn.execute("SELECT 1").fetchone()[0]))
    t.start()
    t.join()
    conn.close()
    assert out == [1]
