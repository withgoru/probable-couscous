"""데이터 접근은 이 모듈 한 곳에 모은다(C15). 연결, 쓰기 트랜잭션, 마이그레이션 실행기를 둔다.

저장소가 진실이다(C13): 쓰기는 `synchronous=FULL`로 디스크에 반영된 뒤에야 성공으로 본다.
"""

from __future__ import annotations

import hashlib
import re
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from fastapi import Request

from app.clock import Clock

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_MIGRATION_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")


class MigrationError(RuntimeError):
    """마이그레이션을 적용할 수 없을 때. 어느 파일이 왜 문제인지 메시지에 담는다."""


def connect(path: str | Path, busy_timeout_ms: int = 5000) -> sqlite3.Connection:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    # 같은 요청의 의존성과 처리 함수가 서로 다른 스레드에서 실행될 수 있어 check_same_thread를 푼다.
    # 연결은 요청 하나가 차례로만 쓰고 동시에 쓰지 않는다.
    conn = sqlite3.connect(
        path, isolation_level=None, timeout=busy_timeout_ms / 1000, check_same_thread=False
    )
    conn.row_factory = sqlite3.Row
    conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """쓰기 트랜잭션. 시작할 때 쓰기 잠금을 잡아 다른 쓰기와 직렬로 처리한다."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def _statements(sql: str) -> Iterator[str]:
    """SQL을 문장 단위로 나눈다. 트리거처럼 안에 `;`가 있는 문장도 하나로 본다."""
    start = 0
    for i, ch in enumerate(sql):
        if ch == ";" and sqlite3.complete_statement(sql[start : i + 1]):
            yield sql[start : i + 1].strip()
            start = i + 1
    tail = sql[start:].strip()
    if tail:
        yield tail


def _checksum(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _list_migrations(directory: Path) -> dict[str, Path]:
    found: dict[str, Path] = {}
    numbers: dict[str, str] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.sql")):
        match = _MIGRATION_NAME.match(path.name)
        if not match:
            raise MigrationError(
                f"{path.name}: 파일 이름은 0001_이름.sql 형식(숫자 4자리, 영문 소문자·숫자·밑줄)이어야 합니다."
            )
        number = match.group(1)
        if number in numbers:
            raise MigrationError(
                f"번호 {number}가 겹칩니다: {numbers[number]}, {path.name}. 번호를 하나씩 올려 주세요."
            )
        numbers[number] = path.name
        found[path.stem] = path
    return found


def migrate(conn: sqlite3.Connection, directory: str | Path, clock: Clock) -> list[str]:
    """아직 적용하지 않은 마이그레이션을 번호 순서로 적용하고 적용한 이름 목록을 돌려준다."""
    directory = Path(directory)
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations("
        "version TEXT PRIMARY KEY, checksum TEXT NOT NULL, applied_at TEXT NOT NULL)"
    )
    files = _list_migrations(directory)
    applied = {r["version"]: r["checksum"] for r in conn.execute("SELECT * FROM schema_migrations")}

    for version, checksum in applied.items():
        if version not in files:
            raise MigrationError(
                f"{version}: 이미 적용된 마이그레이션 파일이 없습니다. "
                "코드보다 새로운 DB이거나 파일이 지워졌습니다."
            )
        if _checksum(files[version]) != checksum:
            raise MigrationError(
                f"{version}: 적용된 뒤 파일 내용이 바뀌었습니다. "
                "적용된 마이그레이션은 고치지 말고 새 번호의 파일을 추가해 주세요."
            )

    done: list[str] = []
    for version in sorted(v for v in files if v not in applied):
        path = files[version]
        try:
            with transaction(conn):
                for statement in _statements(path.read_text(encoding="utf-8")):
                    conn.execute(statement)
                conn.execute(
                    "INSERT INTO schema_migrations(version, checksum, applied_at) VALUES (?, ?, ?)",
                    (version, _checksum(path), clock.now().isoformat()),
                )
        except sqlite3.Error as err:
            raise MigrationError(f"{version}: 적용하지 못했습니다. {err}") from err
        done.append(version)
    return done


def get_db(request: Request) -> Iterator[sqlite3.Connection]:
    """요청마다 연결을 하나 열고 끝나면 닫는다. 같은 요청 안에서는 같은 연결을 쓴다."""
    conn = connect(request.app.state.settings.database_path)
    try:
        yield conn
    finally:
        conn.close()
