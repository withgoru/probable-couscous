"""C13: 서버를 다시 시작해도 상태를 잃지 않는다. 앱이 뜰 때 DB를 열고 마이그레이션을 적용한다."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from app.clock import ManualClock
from app.config import Settings
from app.db import connect
from app.main import create_app


def settings_for(tmp_path) -> Settings:
    return Settings(database_path=tmp_path / "data" / "app.db", client_dist=tmp_path / "none")


def test_startup_opens_db_applies_migrations_and_exposes_clock(tmp_path):
    clock = ManualClock(datetime(2026, 5, 1, tzinfo=UTC))
    with TestClient(create_app(settings_for(tmp_path), clock=clock)) as client:
        assert client.app.state.clock is clock
        assert client.get("/api/health").status_code == 200
    db = connect(tmp_path / "data" / "app.db")
    assert db.execute("SELECT name FROM sqlite_master WHERE name='schema_migrations'").fetchone()
    assert db.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    db.close()


def test_restart_keeps_data_and_does_not_reapply_migrations(tmp_path):
    s = settings_for(tmp_path)
    with TestClient(create_app(s)):
        pass
    db = connect(s.database_path)
    db.execute("CREATE TABLE IF NOT EXISTS kept(x INTEGER)")
    db.execute("INSERT INTO kept VALUES (42)")
    before = db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0]
    db.close()

    with TestClient(create_app(s)):  # 서버 재시작
        pass

    db = connect(s.database_path)
    assert db.execute("SELECT x FROM kept").fetchone()["x"] == 42
    assert db.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == before
    db.close()
