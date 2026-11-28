"""003 출석의 HTTP 라우트.

- 교수 전용 라우트는 `class_access.guard_class(Action.ATTENDANCE_MANAGE, …)`로 건다. `authz.guard`는 학생을 알아보지
  못해 학생에게 로그인 안내(401)가 나가므로, 다른 교수와 학생 모두에게 AC26 문구(403)가 나가도록 이쪽을 쓴다(T002 노트).
- 변경 요청의 `Origin` 검사는 앱 전체(`main.check_origin`)가 한다.
"""

import sqlite3
from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app import attendance_state, events, identity
from app.attendance_core import (
    AttendanceStatus,
    attendance_status,
    code_accepted,
    compute_attendance_code,
    slot_bounds,
    slot_of,
)
from app.authz import Action, Granted
from app.class_access import guard_class
from app.classrooms import load_classroom
from app.db import get_db, transaction
from app.realtime import publish_class
from app.sessions import load_session
from app.ws_class import MEMBER_ONLY, PROFESSOR_ONLY

router = APIRouter()

Db = Annotated[sqlite3.Connection, Depends(get_db)]
ManageGuard = Annotated[Granted, Depends(guard_class(Action.ATTENDANCE_MANAGE, load_classroom))]
# 열기·연장·마감·다시 받기는 수업 행동이다(보관된 강좌 거절). 학생도 AC26 문구를 받게 guard_class로 건다
PresentGuard = Annotated[Granted, Depends(guard_class(Action.SESSION_PRESENT, load_classroom))]

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


# --- 연장·마감·다시 받기(AC4, AC5) -----------------------------------------------------------

NOT_LIVE = "진행 중인 수업에서만 출석을 받을 수 있습니다."
NOT_OPEN = "출석 시간이 이미 끝났습니다. 다시 받으려면 '출석 다시 받기'를 눌러 주세요."
ALREADY_OPEN = "이미 출석을 받고 있습니다. 마감한 뒤 다시 받아 주세요."
EXTEND_BY = timedelta(minutes=5)

_CONTROL = "/api/classrooms/{classroom_id}/sessions/{session_id}/attendance/"


def _control(request: Request, db: sqlite3.Connection, granted: Granted, session_id: int, apply) -> dict:
    """진행 중인 회차에서 `apply(window, now)`로 창을 바꾸고, `version`을 올려 기록과 함께 커밋한 뒤 알린다.

    `apply`는 바꿀 수 없으면 409를 낸다. 그러면 아무것도 쓰지 않고 발행하지 않는다.
    """
    classroom_id = granted.resource.id
    with transaction(db):
        now = request.app.state.clock.now()  # 쓰기 잠금을 잡은 뒤의 시각(기다린 요청이 지난 시각으로 쓰지 않게)
        if load_session(db, classroom_id, session_id)["status"] != "live":
            raise HTTPException(status_code=409, detail=NOT_LIVE)
        apply(attendance_state.unclosed_window(db, classroom_id, session_id), now)
        db.execute(
            "UPDATE class_sessions SET version = version + 1 WHERE id = ? AND classroom_id = ?",
            (session_id, classroom_id),
        )
        (version,) = db.execute(
            "SELECT version FROM class_sessions WHERE id = ? AND classroom_id = ?", (session_id, classroom_id)
        ).fetchone()
        window = attendance_state.window_summary(db, classroom_id, session_id, now)
    # 기록이 끝난 뒤에 알린다(C13). 학생 화면은 이것으로 출석코드 단계를 열고 닫는다(AC11, AC14)
    publish_class(request, classroom_id, "attendance.updated", session_id=session_id, window=window, version=version)
    # 화면은 server_now로 남은 시간을 다시 맞춘다(연장 뒤 카운트다운)
    return {"window": window, "version": version, "server_now": now.isoformat()}


@router.post(_CONTROL + "extend")
def extend_attendance(session_id: int, granted: PresentGuard, db: Db, request: Request):
    """마감 시각을 5분 늦춘다(AC4). 누를 때마다 5분이다."""

    def apply(window, now):
        if not attendance_state.is_open(window, now):
            raise HTTPException(status_code=409, detail=NOT_OPEN)
        closes_at = (datetime.fromisoformat(window["closes_at"]) + EXTEND_BY).isoformat()
        db.execute("UPDATE attendance_windows SET closes_at = ? WHERE id = ?", (closes_at, window["id"]))
        events.record_event(
            db, granted.resource.id, "attendance_extended", "professor", granted.actor.github_id, None,
            {"session_id": session_id, "window_id": window["id"], "closes_at": closes_at}, now,
        )

    return _control(request, db, granted, session_id, apply)


@router.post(_CONTROL + "close")
def close_attendance(session_id: int, granted: PresentGuard, db: Db, request: Request):
    """출석 마감(AC4). 이후에는 수기 보정으로만 출석한다. 확인 대화상자는 화면 몫이다."""

    def apply(window, now):
        if not attendance_state.is_open(window, now):
            raise HTTPException(status_code=409, detail=NOT_OPEN)
        attendance_state.close_window(db, granted.resource.id, session_id, "professor", granted.actor.github_id, now)

    return _control(request, db, granted, session_id, apply)


@router.post(_CONTROL + "reopen")
def reopen_attendance(session_id: int, granted: PresentGuard, db: Db, request: Request):
    """출석 다시 받기(AC5, AC7). 강좌의 출석 받는 시간만큼 새 창(새 코드)을 연다. 이미 출석한 학생은 그대로다."""

    def apply(window, now):
        if attendance_state.is_open(window, now):
            raise HTTPException(status_code=409, detail=ALREADY_OPEN)
        # 시간이 지나 닫힌 창이 남아 있으면 마감 시각으로 닫고 새 창을 연다(회차마다 닫지 않은 창은 하나)
        attendance_state.close_window(db, granted.resource.id, session_id, "reopen", granted.actor.github_id, now)
        attendance_state.open_window(db, granted.resource.id, session_id, "reopen", granted.actor.github_id, now)

    return _control(request, db, granted, session_id, apply)


# --- 교수·프로젝터용 코드(AC3) ----------------------------------------------------------------

NO_WINDOW = "지금은 출석을 받고 있지 않습니다."
NO_STORE = {"Cache-Control": "no-store"}


@router.get("/api/classrooms/{classroom_id}/sessions/{session_id}/attendance/code")
def attendance_code(session_id: int, granted: ManageGuard, db: Db, request: Request):
    """지금 코드와 다음 코드, 각 칸이 끝나는 시각, 마감 시각, 서버 시각.

    화면은 서버 시각과의 차이를 구해 경계에서 다음 코드로 바꾸고 곧바로 그다음을 받는다(plan '코드 전달').
    다음 코드는 마감 뒤의 칸일 수도 있다. 그 코드는 받지 않으므로(창이 닫힌다) 화면이 마감 시각에 숨긴다.
    """
    classroom_id = granted.resource.id
    load_session(db, classroom_id, session_id)  # 다른 강좌의 회차는 404
    now = request.app.state.clock.now()
    window = attendance_state.unclosed_window(db, classroom_id, session_id)
    if not attendance_state.is_open(window, now):
        return JSONResponse(status_code=409, content={"detail": NO_WINDOW}, headers=NO_STORE)
    secret = request.app.state.settings.server_secret
    slot = slot_of(now)

    def at(s: int) -> dict:
        return {
            "code": compute_attendance_code(secret, window["id"], window["nonce"], s),
            "ends_at": slot_bounds(s)[1].isoformat(),
        }

    body = {"current": at(slot), "next": at(slot + 1), "closes_at": window["closes_at"], "server_now": now.isoformat()}
    return JSONResponse(body, headers=NO_STORE)


# --- 학생 코드 출석(AC12~AC16, AC27) ------------------------------------------------------------

SelfGuard = Annotated[Granted, Depends(guard_class(Action.ATTENDANCE_SELF, load_classroom))]

WRONG_CODE = "코드가 맞지 않습니다. 교실 화면의 숫자를 다시 확인해 주세요."  # AC13
LOCKED = "잠시 뒤에 다시 입력해 주세요. ({seconds}초)"  # AC13
CLOSED = "출석 시간이 끝났습니다. 교수님께 수기 출석을 요청하세요."  # AC14
BAD_KEY = "요청이 올바르지 않습니다. 화면을 새로 고친 뒤 다시 눌러 주세요."
NOT_ON_ROSTER = "이 강좌에 입장한 학생만 출석할 수 있습니다. 강좌 링크를 다시 열어 입장해 주세요."
CLIENT_KEY_MAX = 64


class CheckIn(BaseModel):
    code: object = None
    client_key: object = None


def _clean_key(value: object) -> str:
    if not isinstance(value, str) or not 1 <= len(value) <= CLIENT_KEY_MAX:
        raise HTTPException(status_code=422, detail=BAD_KEY)
    return value


def publish_attendance_change(
    request: Request, db: sqlite3.Connection, classroom_id: int, session_id: int, membership_id: int | None
) -> None:
    """출석이 바뀐 뒤(커밋 뒤) 교수 화면에 수를, 그 학생의 화면에 자기 상태를 알린다(AC6, AC18, AC19)."""
    tally = attendance_state.professor_tally(db, classroom_id, session_id)
    publish_class(request, classroom_id, "attendance.tally", session_id=session_id, **tally, to=PROFESSOR_ONLY)
    if membership_id is not None:
        mine = attendance_state.student_view(db, classroom_id, session_id, membership_id)
        publish_class(
            request, classroom_id, "attendance.mine", session_id=session_id, **mine,
            membership_id=membership_id, to=MEMBER_ONLY,
        )


@router.post("/api/class/{classroom_id}/sessions/{session_id}/attendance")
def check_in(session_id: int, body: CheckIn, granted: SelfGuard, db: Db, request: Request):
    """학생 본인의 코드 출석. 순서가 중요하다.

    1. 같은 누름의 재전송(같은 `client_key`)이면 처음과 같은 답(마감 뒤라도). 이미 출석이면 `already`(AC16).
    2. 출석 받는 중이 아니면 409(AC14).
    3. 틀린 코드 제한기로 막힘 확인 → 코드 확인 → 틀림 세기를 한 번에(T003 `attempt`). 막혔으면 429.
    4. 맞으면 기록하고 커밋한 뒤 알린다(C13).
    """
    classroom_id = granted.resource.id
    membership_id = granted.actor.membership_id
    client_key = _clean_key(body.client_key)
    limiter = request.app.state.attendance_limiter
    secret = request.app.state.settings.server_secret
    with transaction(db):
        now = request.app.state.clock.now()
        load_session(db, classroom_id, session_id)
        # 권한 판단(입장한 학생) 뒤 쓰기 잠금 안에서 지금 명단의 항목을 다시 찾는다. 그사이 명단에서 빠졌으면
        # 출석을 남기지 않는다. 권한 판단이 아니라 기록할 대상(명단 항목)을 정하는 일이다(notes/T008.md)
        entry = identity.roster_entry_of(db, classroom_id, membership_id)
        if entry is None:
            raise HTTPException(status_code=403, detail=NOT_ON_ROSTER)
        code_mark = db.execute(
            "SELECT client_key FROM attendance_marks WHERE classroom_id = ? AND session_id = ? AND roster_entry_id = ? "
            "AND kind = 'code'",
            (classroom_id, session_id, entry),
        ).fetchone()
        last = db.execute(
            "SELECT kind FROM attendance_marks WHERE classroom_id = ? AND session_id = ? AND roster_entry_id = ? "
            "ORDER BY id DESC LIMIT 1",
            (classroom_id, session_id, entry),
        ).fetchone()
        status = attendance_status([last["kind"]] if last else [])
        if code_mark is not None and code_mark["client_key"] == client_key:
            return {"status": AttendanceStatus.PRESENT.value, "already": False}  # 같은 누름: 처음 답 그대로
        if code_mark is not None or status is not AttendanceStatus.ABSENT:
            return {"status": status.value, "already": True}
        window = attendance_state.unclosed_window(db, classroom_id, session_id)
        if not attendance_state.is_open(window, now):
            raise HTTPException(status_code=409, detail=CLOSED)
        attempt = limiter.attempt(
            (classroom_id, membership_id), now,
            lambda: code_accepted(secret, window["id"], window["nonce"], body.code, now),
        )
        if attempt.seconds:
            return JSONResponse(
                status_code=429,
                content={"detail": LOCKED.format(seconds=attempt.seconds), "retry_after": attempt.seconds},
                headers={"Retry-After": str(attempt.seconds)},
            )
        if not attempt.ok:
            raise HTTPException(status_code=422, detail=WRONG_CODE)
        db.execute(
            "INSERT INTO attendance_marks(classroom_id, session_id, roster_entry_id, membership_id, kind, actor_kind, "
            "actor_ref, client_key, created_at) VALUES (?, ?, ?, ?, 'code', 'student', ?, ?, ?)",
            (classroom_id, session_id, entry, membership_id, membership_id, client_key, now.isoformat()),
        )
    publish_attendance_change(request, db, classroom_id, session_id, membership_id)
    return {"status": AttendanceStatus.PRESENT.value, "already": False}
