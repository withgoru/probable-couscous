"""003 출석의 HTTP 라우트.

- 교수 전용 라우트는 `class_access.guard_class(Action.ATTENDANCE_MANAGE, …)`로 건다. `authz.guard`는 학생을 알아보지
  못해 학생에게 로그인 안내(401)가 나가므로, 다른 교수와 학생 모두에게 AC26 문구(403)가 나가도록 이쪽을 쓴다(T002 노트).
- 변경 요청의 `Origin` 검사는 앱 전체(`main.check_origin`)가 한다.
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from app import events
from app.authz import Action, Granted
from app.class_access import guard_class
from app.classrooms import load_classroom
from app.db import get_db, transaction

router = APIRouter()

Db = Annotated[sqlite3.Connection, Depends(get_db)]
ManageGuard = Annotated[Granted, Depends(guard_class(Action.ATTENDANCE_MANAGE, load_classroom))]

MINUTES_CHOICES = (5, 10, 15)
BAD_MINUTES = "출석 받는 시간은 5분, 10분, 15분 중에서 골라 주세요."


class AttendanceSettings(BaseModel):
    # 형식 검사는 직접 해서 한국어 안내를 준다
    minutes: object = None


def _clean_minutes(value: object) -> int:
    # bool은 int의 하위형이라 따로 막는다. 10.0 같은 실수와 "10" 같은 글자도 받지 않는다
    if type(value) is not int or value not in MINUTES_CHOICES:
        raise HTTPException(status_code=422, detail=BAD_MINUTES)
    return value


@router.put("/api/classrooms/{classroom_id}/attendance-settings")
def set_attendance_settings(body: AttendanceSettings, granted: ManageGuard, db: Db, request: Request):
    """강좌의 출석 받는 시간(AC1). 다음에 시작하는 수업부터 쓰인다. 바뀌었을 때만 기록한다(C6)."""
    minutes = _clean_minutes(body.minutes)
    classroom_id = granted.resource.id
    now = request.app.state.clock.now()
    with transaction(db):
        before = db.execute("SELECT attendance_minutes FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()[0]
        if before != minutes:
            db.execute("UPDATE classrooms SET attendance_minutes = ? WHERE id = ?", (minutes, classroom_id))
            events.record_event(
                db,
                classroom_id,
                "attendance_minutes_changed",
                "professor",
                granted.actor.github_id,
                None,
                {"from": before, "to": minutes},
                now,
            )
    return {"attendance_minutes": minutes}
