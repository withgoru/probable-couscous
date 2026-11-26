"""수업 시작·종료·이어서 하기(002 AC9~AC11, AC37, AC38, AC40).

- 시작: 예정 회차 → 진행 중, 위치 1번 슬라이드·0단계. 묶음이 없어도 시작한다("슬라이드 없이" 확인은 화면 몫).
- 종료: 진행 중 → 종료. 위치는 그대로 남아 학생이 다시 볼 때 이어 보는 곳이 된다.
- 이어서 하기: 종료 → 진행 중. 마지막 위치가 그대로다.
- 이미 그 상태면(두 번 누름, 다시 보낸 요청) 아무것도 바꾸지 않고 지금 상태를 돌려준다.
- 강좌에서 진행 중인 회차는 하나다. DB 색인이 막고, 막히면 그 회차를 알려 준다(AC10).
- 바뀔 때마다 `version`을 1 올리고, 기록(C6)과 함께 커밋한 **뒤에** 수업 방에 `session.updated`를 발행한다(C13).

시작·이어서 하기는 `session.present`(보관된 강좌 거절, AC11)다. 종료는 `session.manage`다. 수업 중에 강좌를
보관해도 그 수업을 끝낼 수 있어야 진행 중으로 묶여 남지 않는다(notes/T007.md).
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.authz import Action, Granted, guard
from app.classrooms import load_classroom
from app.db import get_db, transaction
from app.events import record_event
from app.realtime import publish_class
from app.sessions import _listed, load_session

router = APIRouter()

NOT_STARTED = "아직 시작하지 않은 회차입니다."
ARCHIVED = "보관된 강좌는 수업을 시작할 수 없습니다."
ENDED_USE_RESUME = "끝난 회차입니다. '이어서 수업하기'로 다시 시작해 주세요."

Db = Annotated[sqlite3.Connection, Depends(get_db)]
PresentGuard = Annotated[Granted, Depends(guard(Action.SESSION_PRESENT, load_classroom))]
ManageGuard = Annotated[Granted, Depends(guard(Action.SESSION_MANAGE, load_classroom))]

_BASE = "/api/classrooms/{classroom_id}/sessions/{session_id}"
# 권한 판단 뒤 쓰기 전에 강좌가 보관됐을 수 있다. 쓰는 순간에도 진행 중인 강좌일 때만 진행 중으로 바꾼다(AC46)
_STILL_ACTIVE = " AND EXISTS (SELECT 1 FROM classrooms WHERE id = ? AND status = 'active')"


def _went_live(db: sqlite3.Connection) -> bool:
    (changed,) = db.execute("SELECT changes()").fetchone()
    if not changed:
        raise HTTPException(status_code=409, detail=ARCHIVED)
    return True


def live_session(db: sqlite3.Connection, classroom_id: int) -> sqlite3.Row | None:
    return db.execute(
        "SELECT id, title FROM class_sessions WHERE classroom_id = ? AND status = 'live'", (classroom_id,)
    ).fetchone()


def _conflict(db: sqlite3.Connection, classroom_id: int) -> JSONResponse | None:
    """진행 중인 다른 회차 안내(AC10). 그런 회차가 없으면 None."""
    other = live_session(db, classroom_id)
    if other is None:
        return None
    return JSONResponse(
        status_code=409,
        content={"detail": f"{other['title']} 수업이 진행 중입니다. 먼저 끝내 주세요.", "live_session_id": other["id"]},
    )


def _change(
    request: Request, db: sqlite3.Connection, granted: Granted, session_id: int, event: str, apply
) -> JSONResponse | dict:
    """`apply(row, now)`가 참을 돌려주면 바뀐 것이다. 기록하고 커밋한 뒤 발행한다."""
    classroom_id = granted.resource.id
    clock = request.app.state.clock
    try:
        with transaction(db):
            row = load_session(db, classroom_id, session_id)
            changed = apply(row, clock.now().isoformat())
            if changed:
                record_event(
                    db, classroom_id, event, "professor", granted.actor.github_id, None,
                    {"session_id": session_id}, clock.now(),
                )
    except sqlite3.IntegrityError:
        # 강좌당 진행 중 하나는 DB 색인(`class_sessions_one_live`)이 지킨다. 두 화면이 동시에 눌러도 같다
        conflict = _conflict(db, classroom_id)
        if conflict is None:
            raise
        return conflict
    state = db.execute(
        "SELECT status, version FROM class_sessions WHERE id = ? AND classroom_id = ?", (session_id, classroom_id)
    ).fetchone()
    if changed:
        publish_class(
            request, classroom_id, "session.updated", session_id=session_id, status=state["status"],
            version=state["version"],
        )
    return {**_listed(db, request.app.state.deck_store, classroom_id, session_id), "version": state["version"]}


@router.post(_BASE + "/start")
def start_session(session_id: int, granted: PresentGuard, db: Db, request: Request):
    def apply(row, now):
        if row["status"] == "live":
            return False
        if row["status"] == "ended":
            raise HTTPException(status_code=409, detail=ENDED_USE_RESUME)
        db.execute(
            # 예정 회차는 위치가 기본값(1번·0단계)이고 시작·종료 시각이 비어 있다(넘기기는 진행 중에만 된다)
            "UPDATE class_sessions SET status = 'live', first_started_at = ?, started_at = ?, version = version + 1 "
            "WHERE id = ? AND classroom_id = ?" + _STILL_ACTIVE,
            (now, now, session_id, granted.resource.id, granted.resource.id),
        )
        return _went_live(db)

    return _change(request, db, granted, session_id, "session_started", apply)


@router.post(_BASE + "/resume")
def resume_session(session_id: int, granted: PresentGuard, db: Db, request: Request):
    def apply(row, now):
        if row["status"] == "live":
            return False
        if row["status"] == "scheduled":
            raise HTTPException(status_code=409, detail=NOT_STARTED)
        db.execute(
            "UPDATE class_sessions SET status = 'live', started_at = ?, ended_at = NULL, version = version + 1 "
            "WHERE id = ? AND classroom_id = ?" + _STILL_ACTIVE,
            (now, session_id, granted.resource.id, granted.resource.id),
        )
        return _went_live(db)

    return _change(request, db, granted, session_id, "session_resumed", apply)


@router.post(_BASE + "/end")
def end_session(session_id: int, granted: ManageGuard, db: Db, request: Request):
    def apply(row, now):
        if row["status"] == "ended":
            return False
        if row["status"] == "scheduled":
            raise HTTPException(status_code=409, detail=NOT_STARTED)
        db.execute(
            "UPDATE class_sessions SET status = 'ended', ended_at = ?, version = version + 1 "
            "WHERE id = ? AND classroom_id = ?",
            (now, session_id, granted.resource.id),
        )
        return True

    return _change(request, db, granted, session_id, "session_ended", apply)
