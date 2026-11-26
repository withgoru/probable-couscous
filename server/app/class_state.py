"""회차 목록과 회차 현재 상태(002 AC16, AC23, AC29, AC39, AC49).

교수와 그 강좌에 입장한 학생이 쓴다(`class.view`, `guard_class`). 학생에게는 진행 중·종료 회차와 공개 묶음이 있는
예정 회차(미리 보기, AC49)만 있고, 나머지 예정 회차와 다른 강좌의 회차는 없는 것과 같다(404, C5).

`…/live`는 화면이 연결하거나 다시 연결할 때, `resync`를 받았을 때 받는 상태 전체다(plan '놓친 것 채우기').
위치·항목은 DB가 진실이다(C13). `version`은 회차가 바뀔 때마다 1 오르고, 화면은 이보다 큰 발행만 적용한다.

학생이 넘겨 볼 수 있는지는 묶음의 공개 여부(`deck.public`)로 정한다. 공개 묶음은 처음부터 끝까지, 비공개 묶음은
수업 중 따라가기만이다(AC26, AC27). 가장 멀리 간 위치는 없다(2026-11-26 스펙 변경).
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.authz import Action, Granted
from app.class_access import guard_class
from app.classrooms import load_classroom
from app.db import get_db
from app.deck_store import DeckStore

router = APIRouter()

NOT_FOUND = "찾을 수 없는 회차입니다."
NO_STORE = {"Cache-Control": "no-store"}

Db = Annotated[sqlite3.Connection, Depends(get_db)]
ViewGuard = Annotated[Granted, Depends(guard_class(Action.CLASS_VIEW, load_classroom))]

_SESSION_SQL = """
SELECT s.id, s.title, s.status, s.sort_order, s.version, s.current_slide, s.current_click,
       s.started_at, s.ended_at,
       d.id AS deck_id, d.slide_count, d.uploaded_at, d.public
  FROM class_sessions s
  LEFT JOIN decks d ON d.session_id = s.id AND d.classroom_id = s.classroom_id AND d.removed_at IS NULL
 WHERE s.classroom_id = ?
"""


def _is_student(granted: Granted) -> bool:
    return granted.actor.kind == "student"


def _deck(row: sqlite3.Row, store: DeckStore, classroom_id: int) -> dict | None:
    if row["deck_id"] is None:
        return None
    return {
        "id": row["deck_id"],
        "slide_count": row["slide_count"],
        "available": store.exists(classroom_id, row["deck_id"]),
        "public": bool(row["public"]),
    }


def _student_sees(row: sqlite3.Row) -> bool:
    """학생에게 보이는 회차: 진행 중, 종료, 공개 묶음이 있는 예정 회차(AC23, AC39, AC49)."""
    return row["status"] in ("live", "ended") or bool(row["deck_id"] is not None and row["public"])


@router.get("/api/class/{classroom_id}/sessions")
def list_class_sessions(granted: ViewGuard, db: Db, request: Request):
    classroom_id = granted.resource.id
    store: DeckStore = request.app.state.deck_store
    if _is_student(granted):
        # 진행 중 → 미리 볼 수 있는 예정 회차(회차 순서) → 종료 회차(최근에 끝난 것부터)(AC23, AC39, AC49)
        rows = db.execute(
            _SESSION_SQL + " AND (s.status IN ('live', 'ended') OR (d.id IS NOT NULL AND d.public = 1)) "
            "ORDER BY CASE s.status WHEN 'live' THEN 0 WHEN 'scheduled' THEN 1 ELSE 2 END, "
            "CASE WHEN s.status = 'scheduled' THEN s.sort_order END, s.ended_at DESC, s.id DESC",
            (classroom_id,),
        ).fetchall()
    else:
        rows = db.execute(_SESSION_SQL + " ORDER BY s.sort_order, s.id", (classroom_id,)).fetchall()
    items = [
        {
            "id": r["id"],
            "title": r["title"],
            "status": r["status"],
            "started_at": r["started_at"],
            "ended_at": r["ended_at"],
            "deck": _deck(r, store, classroom_id),
        }
        for r in rows
    ]
    live_id = next((r["id"] for r in rows if r["status"] == "live"), None)
    return JSONResponse({"items": items, "live_session_id": live_id}, headers=NO_STORE)


def _items(db: sqlite3.Connection, classroom_id: int, session_id: int, student: bool) -> list[dict]:
    rows = db.execute(
        "SELECT id, body, url, created_at, retracted_at FROM session_items "
        "WHERE session_id = ? AND classroom_id = ? ORDER BY id",
        (session_id, classroom_id),
    ).fetchall()
    if student:  # 거둔 항목은 학생에게 보내지 않는다(AC35)
        return [{"id": r["id"], "body": r["body"], "url": r["url"], "created_at": r["created_at"]}
                for r in rows if r["retracted_at"] is None]
    return [dict(r) for r in rows]


@router.get("/api/class/{classroom_id}/sessions/{session_id}/live")
def session_live_state(session_id: int, granted: ViewGuard, db: Db, request: Request):
    classroom_id = granted.resource.id
    student = _is_student(granted)
    row = db.execute(_SESSION_SQL + " AND s.id = ?", (classroom_id, session_id)).fetchone()
    if row is None or (student and not _student_sees(row)):
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    body = {
        "session": {
            "id": row["id"],
            "title": row["title"],
            "status": row["status"],
            "version": row["version"],
            "started_at": row["started_at"],  # 마지막으로 시작(또는 이어서)한 시각. 교수 화면의 경과 시간(AC12)
        },
        "deck": _deck(row, request.app.state.deck_store, classroom_id),
        "current": {"slide": row["current_slide"], "click": row["current_click"]},
        "items": _items(db, classroom_id, session_id, student),
    }
    return JSONResponse(body, headers=NO_STORE)
