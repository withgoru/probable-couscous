"""교수 로그인 라우트: GitHub 로그인 시작·콜백, 로그아웃, 내 정보.

로그인 이름이 아니라 숫자 ID가 허용 목록에 있어야 로그인된다. 허용되지 않은 계정은 DB에 아무것도 남기지 않는다.
실패는 오류 화면이 아니라 `/login?error=코드`로 돌려보낸다(화면 문구는 클라이언트가 보여 준다).
"""

import hmac
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse, Response

from app.auth import (
    SESSION_COOKIE,
    SESSION_LIFETIME,
    STATE_COOKIE,
    STATE_MAX_AGE_SECONDS,
    AuthError,
    hash_token,
    new_token,
)
from app.authz import Action, Granted, guard_account
from app.config import Settings
from app.db import get_db, transaction

router = APIRouter()
STATE_PATH = "/api/auth"
NOT_CONFIGURED = (
    "GitHub 로그인이 설정되지 않았습니다. .env에 GITHUB_CLIENT_ID와 GITHUB_CLIENT_SECRET을 넣고 "
    "서버를 다시 시작해 주세요."
)


def _is_https(settings: Settings) -> bool:
    return settings.base_url.lower().startswith("https://")


def _callback_url(settings: Settings) -> str:
    return settings.base_url.rstrip("/") + "/api/auth/github/callback"


def _provider(request: Request):
    provider = request.app.state.auth_provider
    if provider is None:
        raise HTTPException(status_code=503, detail=NOT_CONFIGURED)
    return provider


@router.get("/api/auth/github/login")
def github_login(request: Request):
    settings: Settings = request.app.state.settings
    state = new_token()
    response = RedirectResponse(
        _provider(request).authorize_url(state, _callback_url(settings)), status_code=302
    )
    response.set_cookie(
        STATE_COOKIE, state, max_age=STATE_MAX_AGE_SECONDS, httponly=True,
        secure=_is_https(settings), samesite="lax", path=STATE_PATH,
    )
    return response


@router.get("/api/auth/github/callback")
def github_callback(
    request: Request,
    db: Annotated[sqlite3.Connection, Depends(get_db)],
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
):
    settings: Settings = request.app.state.settings

    def back(reason: str) -> RedirectResponse:
        response = RedirectResponse(f"/login?error={reason}", status_code=302)
        response.delete_cookie(STATE_COOKIE, path=STATE_PATH)  # state는 한 번만 쓴다
        return response

    expected = request.cookies.get(STATE_COOKIE)
    if not expected or not state or not hmac.compare_digest(expected, state):
        return back("state")
    if error:
        return back("cancelled" if error == "access_denied" else "github")
    if not code:
        return back("github")

    try:
        profile = _provider(request).exchange(code, _callback_url(settings))
    except AuthError:
        return back("github")
    if profile.github_id not in settings.professor_github_ids:
        return back("not_allowed")

    now = request.app.state.clock.now()
    token = new_token()
    with transaction(db):
        db.execute(
            "INSERT INTO professors(github_id, login, created_at) VALUES (?, ?, ?) "
            "ON CONFLICT(github_id) DO UPDATE SET login = excluded.login",
            (profile.github_id, profile.login, now.isoformat()),
        )
        db.execute(
            "INSERT INTO professor_sessions(token_hash, github_id, created_at, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (hash_token(token), profile.github_id, now.isoformat(), (now + SESSION_LIFETIME).isoformat()),
        )
    response = RedirectResponse("/courses", status_code=302)
    response.set_cookie(
        SESSION_COOKIE, token, max_age=int(SESSION_LIFETIME.total_seconds()), httponly=True,
        secure=_is_https(settings), samesite="lax", path="/",
    )
    response.delete_cookie(STATE_COOKIE, path=STATE_PATH)
    return response


@router.post("/api/auth/logout", status_code=204)
def logout(request: Request, db: Annotated[sqlite3.Connection, Depends(get_db)]):
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        with transaction(db):
            db.execute(
                "UPDATE professor_sessions SET revoked_at = ? WHERE token_hash = ? AND revoked_at IS NULL",
                (request.app.state.clock.now().isoformat(), hash_token(token)),
            )
    response = Response(status_code=204)
    response.delete_cookie(SESSION_COOKIE, path="/")
    return response


@router.get("/api/me")
def me(
    granted: Annotated[Granted, Depends(guard_account(Action.ME_READ))],
    db: Annotated[sqlite3.Connection, Depends(get_db)],
):
    row = db.execute(
        "SELECT github_id, login FROM professors WHERE github_id = ?", (granted.actor.github_id,)
    ).fetchone()
    return JSONResponse(
        {"github_id": row["github_id"], "login": row["login"]},
        headers={"Cache-Control": "no-store"},  # 로그아웃 뒤 뒤로 가기에서 내용이 남지 않게
    )
