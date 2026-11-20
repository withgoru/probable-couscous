"""학생이 초대 링크로 들어오는 첫 단계: 링크 열기와 이메일 확인(AC10, AC22~AC25, AC38).

- 링크를 열기만 해서는 입장되지 않는다. 기기 쿠키만 심고 로그인 상태는 만들지 않는다(AC23).
- 틀린 토큰과 폐기된 토큰은 같은 응답이다. 강좌가 있는지 알려 주지 않는다(AC22).
- 명단에 있는 이메일이면 챌린지를 만들고 같은 쓰기 트랜잭션에서 메일 발송 요청을 쌓는다(C13). 코드는 응답에 싣지 않는다.
- 권한은 `student.enter`를 `authz.decide`로 판단한다. 보관된 강좌만 막는다(C8).
"""

import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from app.authz import Action, ClassroomRef, Granted, guard
from app.challenges import (
    DEVICE_COOKIE,
    RESEND_INTERVAL,
    ResendTooSoon,
    ensure_device,
    issue_challenge_unlocked,
)
from app.db import get_db, transaction
from app.invites import resolve_token
from app.mail import enqueue_code_mail
from app.roster import find_live_by_email, is_valid_email, normalize_email

router = APIRouter()

REVOKED = "이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요."
NOT_IN_ROSTER = (
    "수강생 명단에 없는 이메일입니다. 수강신청에 쓴 이메일인지 확인하고, 계속 안 되면 교수님께 입장을 요청해 주세요."
)
DEVICE_MAX_AGE = 60 * 60 * 24 * 365  # 기기 쿠키는 1년. 지우면 새 기기다
Db = Annotated[sqlite3.Connection, Depends(get_db)]


def load_by_token(token: str, db: Db) -> ClassroomRef:
    """초대 토큰으로 강좌를 찾는다. 없거나 폐기된 토큰은 구별하지 않고 같은 404다(AC22)."""
    classroom = resolve_token(db, token)
    if classroom is None:
        raise HTTPException(status_code=404, detail=REVOKED)
    return classroom


EnterGuard = Annotated[Granted, Depends(guard(Action.STUDENT_ENTER, load_by_token))]


def _set_device_cookie(request: Request, response: JSONResponse, token: str) -> None:
    secure = request.app.state.settings.base_url.lower().startswith("https://")
    response.set_cookie(
        DEVICE_COOKIE, token, max_age=DEVICE_MAX_AGE, httponly=True, secure=secure, samesite="lax", path="/"
    )


def _device(request: Request, db: sqlite3.Connection):
    return ensure_device(db, request.cookies.get(DEVICE_COOKIE), request.app.state.clock.now())


def _problem(status: int, field: str | None, message: str, **extra: object) -> HTTPException:
    return HTTPException(status_code=status, detail={"field": field, "message": message, **extra})


@router.get("/api/join/{token}")
def open_link(granted: EnterGuard, request: Request, db: Db):
    """초대 링크를 연다. 강좌 이름만 알려 주고, 이 기기에 기기 쿠키를 심는다(없을 때만)."""
    row = db.execute("SELECT name, section_name FROM classrooms WHERE id = ?", (granted.resource.id,)).fetchone()
    response = JSONResponse({"name": row["name"], "section_name": row["section_name"]})
    device = _device(request, db)
    if device.is_new:
        _set_device_cookie(request, response, device.token)
    return response


class EmailBody(BaseModel):
    email: object = None


@router.post("/api/join/{token}/email")
def check_email(body: EmailBody, granted: EnterGuard, request: Request, db: Db):
    """이메일을 확인한다. 명단에 있으면 코드 메일을 요청하고, 없으면 입장 요청 안내를 준다(메일은 보내지 않는다)."""
    raw = body.email.strip() if isinstance(body.email, str) else ""
    if not raw:
        raise _problem(422, "email", "이메일을 입력해 주세요.")
    if not is_valid_email(raw):
        raise _problem(422, "email", "이메일 형식을 확인해 주세요.")
    email = normalize_email(raw)
    classroom_id = granted.resource.id
    entry = find_live_by_email(db, classroom_id, email)
    if entry is None:
        return {"next": "request_access", "message": NOT_IN_ROSTER}

    device = _device(request, db)
    now = request.app.state.clock.now()
    try:
        # 챌린지와 메일 발송 요청은 함께 저장되거나 함께 사라진다. 메일 없는 챌린지가 남지 않게 한다
        with transaction(db):
            challenge_id = issue_challenge_unlocked(
                db, request.app.state.settings.server_secret, classroom_id, email, device.device_id, now
            )
            enqueue_code_mail(db, classroom_id, challenge_id, entry["email_norm"], now)
    except ResendTooSoon as err:
        raise _problem(429, None, str(err), wait_seconds=err.seconds) from err
    response = JSONResponse({"next": "code", "wait_seconds": int(RESEND_INTERVAL.total_seconds())})
    if device.is_new:
        _set_device_cookie(request, response, device.token)
    return response
