"""회차 만들기·이름 바꾸기·삭제·목록(002 AC1~AC4).

모든 라우트는 `session.manage`로 권한 판단을 거친다(C8). 보관된 강좌도 교수는 회차를 관리한다(001 결정).
회차는 언제나 경로의 강좌 안에서만 찾는다. 다른 강좌의 회차 번호는 없는 것과 같다(C5).
시작·종료·이어서 하기는 T007, 슬라이드 묶음 올리기는 T005가 맡는다.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel

from app.authz import Action, Granted, guard
from app.classrooms import load_classroom
from app.clock import Clock
from app.db import get_db, transaction
from app.events import record_event

router = APIRouter()

TITLE_MAX = 40
TITLE_REQUIRED = "회차 이름을 입력해 주세요."
TITLE_TOO_LONG = f"회차 이름은 {TITLE_MAX}자 이하로 입력해 주세요."
NOT_FOUND = "찾을 수 없는 회차입니다."
STARTED_CANNOT_DELETE = "한 번이라도 시작한 회차는 삭제할 수 없습니다."

Db = Annotated[sqlite3.Connection, Depends(get_db)]
ManageGuard = Annotated[Granted, Depends(guard(Action.SESSION_MANAGE, load_classroom))]


def _clock(request: Request) -> Clock:
    return request.app.state.clock


ClockDep = Annotated[Clock, Depends(_clock)]

_COLUMNS = "id, title, status, sort_order, first_started_at, created_at"
# 회차와 그 회차의 살아 있는 슬라이드 묶음(AC5: 업로드됨/비어 있음, 파일 이름, 시각, 슬라이드 수)
_LIST_SQL = """
SELECT s.id, s.title, s.status, s.sort_order, s.first_started_at, s.created_at,
       d.id AS deck_id, d.original_name, d.slide_count, d.size_bytes, d.uploaded_at
  FROM class_sessions s
  LEFT JOIN decks d ON d.session_id = s.id AND d.classroom_id = s.classroom_id AND d.removed_at IS NULL
 WHERE s.classroom_id = ?
"""


class SessionTitle(BaseModel):
    # 형식 검사는 직접 해서 사람이 읽을 수 있는 한국어 안내를 준다
    title: object = None


def clean_title(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise HTTPException(status_code=422, detail=TITLE_REQUIRED)
    title = value.strip()
    if len(title) > TITLE_MAX:
        raise HTTPException(status_code=422, detail=TITLE_TOO_LONG)
    return title


def deck_item(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "original_name": row["original_name"],
        "slide_count": row["slide_count"],
        "size_bytes": row["size_bytes"],
        "uploaded_at": row["uploaded_at"],
    }


def _item(row: sqlite3.Row) -> dict:
    deck = None
    if row["deck_id"] is not None:
        deck = {
            "id": row["deck_id"],
            "original_name": row["original_name"],
            "slide_count": row["slide_count"],
            "size_bytes": row["size_bytes"],
            "uploaded_at": row["uploaded_at"],
        }
    return {
        "id": row["id"],
        "title": row["title"],
        "status": row["status"],
        "sort_order": row["sort_order"],
        "created_at": row["created_at"],
        "can_delete": row["first_started_at"] is None,  # AC4: 한 번도 시작하지 않은 회차만
        "deck": deck,
    }


def _listed(db: sqlite3.Connection, classroom_id: int, session_id: int) -> dict:
    return _item(db.execute(_LIST_SQL + " AND s.id = ?", (classroom_id, session_id)).fetchone())


def load_session(db: sqlite3.Connection, classroom_id: int, session_id: int) -> sqlite3.Row:
    """경로의 강좌에 속한 회차. 없거나 다른 강좌의 회차면 404."""
    row = db.execute(
        f"SELECT {_COLUMNS} FROM class_sessions WHERE id = ? AND classroom_id = ?", (session_id, classroom_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    return row


def _record(db: sqlite3.Connection, granted: Granted, type: str, session_id: int, clock: Clock) -> None:
    # 회차 이름은 교수가 입력한 값이지만, 기록에는 번호만 남긴다(이름은 표에 있다)
    record_event(
        db, granted.resource.id, type, "professor", granted.actor.github_id, None, {"session_id": session_id}, clock.now()
    )


@router.get("/api/classrooms/{classroom_id}/sessions")
def list_sessions(granted: ManageGuard, db: Db):
    rows = db.execute(_LIST_SQL + " ORDER BY s.sort_order, s.id", (granted.resource.id,)).fetchall()
    return {"items": [_item(r) for r in rows]}


@router.post("/api/classrooms/{classroom_id}/sessions", status_code=201)
def create_session(body: SessionTitle, granted: ManageGuard, db: Db, clock: ClockDep):
    title = clean_title(body.title)
    classroom_id = granted.resource.id
    with transaction(db):
        (last,) = db.execute(
            "SELECT COALESCE(MAX(sort_order), 0) FROM class_sessions WHERE classroom_id = ?", (classroom_id,)
        ).fetchone()
        cursor = db.execute(
            "INSERT INTO class_sessions(classroom_id, title, sort_order, created_at) VALUES (?, ?, ?, ?)",
            (classroom_id, title, last + 1, clock.now().isoformat()),
        )
        _record(db, granted, "session_created", cursor.lastrowid, clock)
    return _listed(db, classroom_id, cursor.lastrowid)


@router.patch("/api/classrooms/{classroom_id}/sessions/{session_id}")
def rename_session(session_id: int, body: SessionTitle, granted: ManageGuard, db: Db, clock: ClockDep):
    title = clean_title(body.title)
    classroom_id = granted.resource.id
    with transaction(db):
        load_session(db, classroom_id, session_id)
        db.execute(
            "UPDATE class_sessions SET title = ? WHERE id = ? AND classroom_id = ?", (title, session_id, classroom_id)
        )
        _record(db, granted, "session_renamed", session_id, clock)
    return _listed(db, classroom_id, session_id)


@router.delete("/api/classrooms/{classroom_id}/sessions/{session_id}", status_code=204)
def delete_session(session_id: int, granted: ManageGuard, db: Db, clock: ClockDep, request: Request):
    """한 번도 시작하지 않은 회차만 지운다. 그 회차의 슬라이드 묶음 기록과 파일도 함께 지운다(AC4)."""
    classroom_id = granted.resource.id
    with transaction(db):
        row = load_session(db, classroom_id, session_id)
        if row["first_started_at"] is not None:
            raise HTTPException(status_code=409, detail=STARTED_CANNOT_DELETE)
        deck_ids = [
            r["id"]
            for r in db.execute("SELECT id FROM decks WHERE session_id = ? AND classroom_id = ?", (session_id, classroom_id))
        ]
        db.execute("DELETE FROM decks WHERE session_id = ? AND classroom_id = ?", (session_id, classroom_id))
        db.execute("DELETE FROM class_sessions WHERE id = ? AND classroom_id = ?", (session_id, classroom_id))
        _record(db, granted, "session_deleted", session_id, clock)
    for deck_id in deck_ids:  # 기록을 지운 뒤 파일을 지운다
        request.app.state.deck_store.remove(classroom_id, deck_id)
    return Response(status_code=204)
