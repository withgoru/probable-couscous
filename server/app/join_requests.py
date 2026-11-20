"""입장 요청: 명단에 없는 학생이 보내는 요청과, 교수의 목록·승인·거절(AC39~AC43, AC48).

- 요청은 이름·학번·이메일만 받는다(C11). 같은 이메일의 처리 전 요청은 하나로 합친다(AC43).
- 승인하면 명단에 추가될 뿐 입장되지는 않는다. 학생은 처음부터 이메일 인증을 밟는다(AC41).
- 승인·거절은 같은 트랜잭션에서 수정·삭제할 수 없는 기록(events)으로 남긴다(C6, AC48).
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app import events
from app.authz import Action, Granted, guard
from app.classrooms import load_classroom
from app.db import get_db, transaction
from app.realtime import publish_admin
from app.roster import CleanEntry, RosterError, add_entry_unlocked

router = APIRouter()
Db = Annotated[sqlite3.Connection, Depends(get_db)]
DecideGuard = Annotated[Granted, Depends(guard(Action.JOINREQUEST_DECIDE, load_classroom))]

REQUESTED = "요청을 보냈습니다. 교수님이 확인하면 이 이메일로 인증 코드를 받을 수 있습니다."
ALREADY = "이미 요청했습니다. 교수님이 확인할 때까지 기다려 주세요."
REJECTED = "입장 요청이 받아들여지지 않았습니다. 교수님께 문의해 주세요."
ALREADY_ON_ROSTER = "이미 수강생 명단에 있는 이메일입니다. 이메일을 다시 입력해 인증 코드를 받아 주세요."
DECIDED = "이미 처리한 요청입니다."
NOT_FOUND = "찾을 수 없는 입장 요청입니다."


def latest_request(db: sqlite3.Connection, classroom_id: int, email_norm: str) -> sqlite3.Row | None:
    """이 강좌에서 이 이메일의 가장 최근 요청."""
    return db.execute(
        "SELECT * FROM join_requests WHERE classroom_id = ? AND email_norm = ? ORDER BY id DESC LIMIT 1",
        (classroom_id, email_norm),
    ).fetchone()


def status_answer(db: sqlite3.Connection, classroom_id: int, email_norm: str) -> dict | None:
    """처리 전이거나 거절된 요청이 있으면 학생에게 줄 응답. 없으면(또는 승인됐으면) None."""
    row = latest_request(db, classroom_id, email_norm)
    if row is None:
        return None
    if row["status"] == "pending":
        return {"next": "already_requested", "message": ALREADY}
    if row["status"] == "rejected":
        return {"next": "rejected", "message": REJECTED}
    return None


def create_request(
    db: sqlite3.Connection, classroom_id: int, email_norm: str, name: str, student_no: str, now: str
) -> int | None:
    """요청을 저장하고 요청 번호를 돌려준다. 같은 이메일의 처리 전 요청이 이미 있으면 None(하나로 합친다)."""
    try:
        with transaction(db):
            cursor = db.execute(
                "INSERT INTO join_requests(classroom_id, email_norm, name, student_no, created_at) VALUES (?, ?, ?, ?, ?)",
                (classroom_id, email_norm, name, student_no, now),
            )
    except sqlite3.IntegrityError:  # 같은 이메일의 처리 전 요청이 동시에 들어왔다
        return None
    return cursor.lastrowid


# --- 교수 ---------------------------------------------------------------------------------------------


@router.get("/api/classrooms/{classroom_id}/join-requests")
def list_requests(granted: DecideGuard, db: Db):
    """처리 전 요청을 오래된 것부터. 이름, 학번, 이메일, 요청 시각만 준다(AC40)."""
    rows = db.execute(
        "SELECT id, name, student_no, email_norm AS email, created_at FROM join_requests "
        "WHERE classroom_id = ? AND status = 'pending' ORDER BY id",
        (granted.resource.id,),
    ).fetchall()
    return JSONResponse({"requests": [dict(r) for r in rows]}, headers={"Cache-Control": "no-store"})


def _pending(db: sqlite3.Connection, classroom_id: int, request_id: int) -> sqlite3.Row:
    row = db.execute(
        "SELECT * FROM join_requests WHERE id = ? AND classroom_id = ?", (request_id, classroom_id)
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail=NOT_FOUND)
    if row["status"] != "pending":
        raise HTTPException(status_code=409, detail={"field": None, "message": DECIDED})
    return row


def _decide(db: sqlite3.Connection, row: sqlite3.Row, status: str, now: str) -> None:
    db.execute("UPDATE join_requests SET status = ?, decided_at = ? WHERE id = ?", (status, now, row["id"]))


@router.post("/api/classrooms/{classroom_id}/join-requests/{request_id}/approve")
def approve(request_id: int, granted: DecideGuard, db: Db, request: Request):
    """승인: 명단에 추가하고 기록한다. 입장은 되지 않는다(AC41). 명단 규칙(중복, 200명)에 걸리면 그대로 두고 이유를 알린다."""
    now = request.app.state.clock.now()
    classroom_id = granted.resource.id
    with transaction(db):
        row = _pending(db, classroom_id, request_id)
        try:
            entry_id = add_entry_unlocked(
                db, classroom_id, CleanEntry(row["student_no"], row["name"], row["email_norm"]), now.isoformat()
            )
        except RosterError as err:
            raise HTTPException(status_code=409, detail={"field": None, "message": err.message}) from err
        _decide(db, row, "approved", now.isoformat())
        events.record_event(
            db, classroom_id, "join_request_approved", "professor", granted.actor.github_id, entry_id,
            {"request_id": request_id}, now,
        )
    publish_admin(request, classroom_id, "join_request.updated", id=request_id, status="approved")
    publish_admin(request, classroom_id, "roster.updated")
    return {"id": request_id, "status": "approved"}


@router.post("/api/classrooms/{classroom_id}/join-requests/{request_id}/reject")
def reject(request_id: int, granted: DecideGuard, db: Db, request: Request):
    """거절: 학생이 다시 열면 거절 안내가 보인다(AC42). 기록한다."""
    now = request.app.state.clock.now()
    classroom_id = granted.resource.id
    with transaction(db):
        row = _pending(db, classroom_id, request_id)
        _decide(db, row, "rejected", now.isoformat())
        events.record_event(
            db, classroom_id, "join_request_rejected", "professor", granted.actor.github_id, None,
            {"request_id": request_id}, now,
        )
    publish_admin(request, classroom_id, "join_request.updated", id=request_id, status="rejected")
    return {"id": request_id, "status": "rejected"}
