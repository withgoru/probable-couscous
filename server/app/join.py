"""학생이 초대 링크로 들어오는 단계: 링크 열기, 이메일 확인, 코드 확인, 다시 받기(AC10, AC22~AC27, AC29~AC34, AC38).

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

from app import identity, student_login
from app.authz import Action, ClassroomRef, Granted, guard
from app.challenges import (
    DEVICE_COOKIE,
    RESEND_INTERVAL,
    Outcome,
    ResendTooSoon,
    ensure_device,
    find_device,
    issue_challenge_unlocked,
    verify_code_unlocked,
)
from app.db import get_db, transaction
from app.invites import resolve_token
from app.mail import enqueue_code_mail
from app.roster import find_live_by_email, is_valid_email, normalize_email
from app.student_login import LOGIN_COOKIE, PERSISTENT_MAX_AGE, create_device_login, current_login

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


def _clean_email(value: object) -> str:
    raw = value.strip() if isinstance(value, str) else ""
    if not raw:
        raise _problem(422, "email", "이메일을 입력해 주세요.")
    if not is_valid_email(raw):
        raise _problem(422, "email", "이메일 형식을 확인해 주세요.")
    return normalize_email(raw)


def _request_code(request: Request, db: sqlite3.Connection, classroom_id: int, email: str):
    """명단에 있으면 코드 메일을 요청하고, 없으면 입장 요청 안내를 준다(메일은 보내지 않는다). 첫 요청과 다시 받기가 같다."""
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


@router.post("/api/join/{token}/email")
def check_email(body: EmailBody, granted: EnterGuard, request: Request, db: Db):
    """이메일을 확인한다. 명단에 있으면 코드 메일을 요청하고, 없으면 입장 요청 안내를 준다."""
    return _request_code(request, db, granted.resource.id, _clean_email(body.email))


@router.post("/api/join/{token}/resend")
def resend_code(body: EmailBody, granted: EnterGuard, request: Request, db: Db):
    """코드 다시 받기. 직전 요청 60초 뒤부터 새 코드를 보내고 이전 코드는 쓸 수 없게 한다(AC32)."""
    return _request_code(request, db, granted.resource.id, _clean_email(body.email))


class CodeBody(BaseModel):
    email: object = None
    code: object = None
    keep_login: object = True  # '이 기기에서 로그인 유지'는 처음부터 켜져 있다(AC26)


@router.post("/api/join/{token}/code")
def check_code(body: CodeBody, granted: EnterGuard, request: Request, db: Db):
    """코드를 확인한다. 맞으면 계정·멤버십·닉네임을 만들고(이미 있으면 그대로) 이 기기의 로그인 상태를 심는다.

    코드 확인, 계정과 멤버십 만들기, 로그인 만들기는 한 트랜잭션이다. 중간에 실패하면 코드는 쓰이지 않은 채로 남는다.
    """
    email = _clean_email(body.email)
    if not isinstance(body.code, str):
        raise _problem(422, "code", "코드는 6자리 숫자입니다. 메일의 코드를 확인해 주세요.", outcome="bad_format", remaining=None)
    keep_login = body.keep_login if isinstance(body.keep_login, bool) else True
    classroom_id = granted.resource.id
    now = request.app.state.clock.now()
    device_id = find_device(db, request.cookies.get(DEVICE_COOKIE))
    if device_id is None:  # 이 기기는 코드를 요청한 적이 없다. 새 기기를 만들지도 않고 다른 기기와 같은 응답을 준다
        raise _problem(422, "code", "코드가 맞지 않습니다.", outcome="wrong", remaining=None)

    with transaction(db):
        entry = find_live_by_email(db, classroom_id, email)
        if entry is None:  # 코드를 받은 뒤 명단에서 빠졌다
            return {"next": "request_access", "message": NOT_IN_ROSTER}
        result = verify_code_unlocked(
            db, request.app.state.settings.server_secret, classroom_id, email, device_id, body.code, now
        )
        if result.outcome is not Outcome.OK:
            failure = _problem(
                422, "code", result.message, outcome=result.outcome.value, remaining=result.remaining
            )
        else:
            failure = None
            account_id = identity.get_or_create_account(db, email, now)
            membership = identity.membership_for(db, classroom_id, account_id, entry["id"], now)
            login = create_device_login(db, account_id, device_id, keep_login, now)
    if failure is not None:
        raise failure  # 틀린 횟수 등의 기록은 위에서 이미 저장됐다
    response = JSONResponse({"next": "notice", "nickname": membership.nickname})
    secure = request.app.state.settings.base_url.lower().startswith("https://")
    response.set_cookie(
        LOGIN_COOKIE,
        login.token,
        max_age=PERSISTENT_MAX_AGE if keep_login else None,  # 끄면 브라우저를 닫을 때 사라지는 쿠키
        httponly=True,
        secure=secure,
        samesite="lax",
        path="/",
    )
    return response


# --- 입장 확정과 내 상태 (AC28, AC35~AC37) -----------------------------------------------------------------------

NOT_LOGGED_IN = "입장 인증이 끝나지 않았습니다. 이메일과 코드로 먼저 인증해 주세요."
NOT_ON_ROSTER = "이 강좌의 수강생 명단에 없습니다. 교수님께 문의해 주세요."


def _classroom_name(db: sqlite3.Connection, classroom_id: int) -> str:
    return db.execute("SELECT name FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()["name"]


def _fresh_login(request: Request, db: sqlite3.Connection, classroom_id: int):
    """이 강좌에서 쓸 수 있는 기기 로그인과 그 계정의 명단 항목. 쓸 수 없으면 None.

    로그인이 유효해야 하고, 계정의 이메일이 이 강좌의 살아 있는 명단에 있어야 하며,
    교수가 로그인을 끊은 뒤(`reverify_after`)에 인증한 로그인이어야 한다.
    """
    now = request.app.state.clock.now()
    login = current_login(db, request.cookies.get(LOGIN_COOKIE), request.cookies.get(DEVICE_COOKIE), now)
    if login is None:
        return None, None, "login"
    entry = find_live_by_email(db, classroom_id, student_login.account_email(db, login.account_id))
    if entry is None:
        return login, None, "not_on_roster"
    existing = identity.find_membership(db, classroom_id, login.account_id)
    if existing and existing.reverify_after and login.created_at <= existing.reverify_after:
        return login, entry, "login"  # 끊긴 뒤에는 이메일 인증부터 다시 한다(AC20)
    return login, entry, "ok"


@router.get("/api/join/{token}/me")
def my_state(granted: EnterGuard, request: Request, db: Db):
    """이 기기의 이 강좌 상태: login(이메일 인증 필요), notice(인증됨, 안내 확인 전), entered(입장함).

    인증된 기기로 다른 강좌 링크를 열면 그 강좌 명단에 있을 때 코드 없이 notice가 된다(AC37). 이때 그 강좌의
    멤버십(닉네임)을 처음 만든다. 같은 요청을 되풀이해도 결과가 같다(멱등).
    """
    classroom_id = granted.resource.id
    login, entry, status = _fresh_login(request, db, classroom_id)
    if status != "ok":
        return {"state": "login"}
    now = request.app.state.clock.now()
    with transaction(db):
        membership = identity.membership_for(db, classroom_id, login.account_id, entry["id"], now)
        # 이 로그인은 끊긴 뒤에 만들어진 것이 확인됐으므로(_fresh_login) 그 로그인의 입장 기록이면 유효하다
        entered = student_login.verified_at(db, login.id, classroom_id) is not None
    return {
        "state": "entered" if entered else "notice",
        "nickname": membership.nickname,
        "classroom": _classroom_name(db, classroom_id),
    }


@router.post("/api/join/{token}/enter")
def enter_classroom(granted: EnterGuard, request: Request, db: Db):
    """'확인하고 입장'. 채팅 이용 안내를 확인한 것으로 기록하고 이 기기를 이 강좌에서 인증된 기기로 남긴다(AC28)."""
    classroom_id = granted.resource.id
    login, entry, status = _fresh_login(request, db, classroom_id)
    if status == "not_on_roster":
        raise HTTPException(status_code=403, detail=NOT_ON_ROSTER)
    if status != "ok":
        raise HTTPException(status_code=401, detail=NOT_LOGGED_IN)
    now = request.app.state.clock.now()
    with transaction(db):
        membership = identity.membership_for(db, classroom_id, login.account_id, entry["id"], now)
        identity.acknowledge_notice(db, membership.id, now)
        student_login.record_verification(db, login.id, classroom_id, membership.id, now)
    return {"next": "entered", "nickname": membership.nickname, "classroom": _classroom_name(db, classroom_id)}
