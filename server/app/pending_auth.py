"""교수의 '대기 중인 인증' 목록(AC45, AC47, AC48).

학생이 '교수님께 알리기'를 누른 코드만 목록에 오르고, 그 코드는 이때 서버 비밀값으로 다시 계산해 보여 준다(저장하지 않는다).
코드를 보여 줄 때마다 `code_revealed`를 같은 트랜잭션에서 기록한다. 기록하지 못하면 코드를 보여 주지 않는다(C6).
목록은 학번·이름·시각·상태·코드만 준다. 이메일과 닉네임, 멤버십과의 연결은 싣지 않는다(C9).
"""

import sqlite3
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from app import events
from app.authz import Action, Granted, guard
from app.challenges import code_for
from app.classrooms import load_classroom
from app.db import get_db, transaction

router = APIRouter()
Db = Annotated[sqlite3.Connection, Depends(get_db)]
ViewGuard = Annotated[Granted, Depends(guard(Action.PENDINGAUTH_VIEW, load_classroom))]

_ROWS_SQL = """
SELECT c.id, c.status, c.expires_at, c.used_at, c.professor_notified_at,
       r.id AS roster_id, r.student_no, r.name
  FROM login_challenges c
  JOIN roster_entries r
    ON r.classroom_id = c.classroom_id AND r.email_norm = c.email_norm AND r.removed_at IS NULL
 WHERE c.classroom_id = ? AND c.professor_notified_at IS NOT NULL AND c.status != 'superseded'
 ORDER BY c.professor_notified_at DESC, c.id DESC
"""


def _status(row: sqlite3.Row, now: datetime) -> str:
    if row["status"] == "used":
        return "used"
    if row["status"] == "expired" or now >= datetime.fromisoformat(row["expires_at"]):
        return "expired"  # 시간이 지났거나 틀린 횟수를 다 썼다
    return "waiting"


@router.get("/api/classrooms/{classroom_id}/pending-auth")
def list_pending(granted: ViewGuard, db: Db, request: Request):
    now = request.app.state.clock.now()
    secret = request.app.state.settings.server_secret
    classroom_id = granted.resource.id
    rows = db.execute(_ROWS_SQL, (classroom_id,)).fetchall()
    items = []
    with transaction(db):
        for r in rows:
            status = _status(r, now)
            item = {
                "id": r["id"],
                "student_no": r["student_no"],
                "name": r["name"],
                "notified_at": r["professor_notified_at"],
                "status": status,
            }
            if status == "waiting":
                item["code"] = code_for(db, secret, r["id"])
                events.record_event(
                    db, classroom_id, "code_revealed", "professor", granted.actor.github_id, r["roster_id"],
                    {"challenge_id": r["id"]}, now,
                )
            elif status == "used":
                item["used_at"] = r["used_at"]
            items.append(item)
    return JSONResponse({"items": items}, headers={"Cache-Control": "no-store"})
