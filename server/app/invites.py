"""강좌의 초대 링크 보기와 다시 만들기(AC21, AC22), 그리고 토큰을 강좌로 바꾸는 규칙.

링크는 강좌마다 하나다. '다시 만들기'는 토큰을 새 값으로 바꾸므로 이전 토큰은 어디에도 남지 않는다.
따라서 폐기된 토큰과 처음부터 없던 토큰은 구별되지 않고, 강좌가 있는지 알려 주지 않는다(AC22).
링크를 열었다고 입장되지는 않는다(AC23). 이 모듈은 링크를 만들고 해석할 뿐이다.
"""

import secrets
import sqlite3
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from app.authz import Action, ClassroomRef, Granted, guard
from app.classrooms import TOKEN_ATTEMPTS, load_classroom
from app.db import get_db, transaction

router = APIRouter()

Db = Annotated[sqlite3.Connection, Depends(get_db)]
ManageGuard = Annotated[Granted, Depends(guard(Action.CLASSROOM_MANAGE, load_classroom))]


def resolve_token(db: sqlite3.Connection, token: str) -> ClassroomRef | None:
    """초대 토큰이 가리키는 강좌. 없거나 폐기된 토큰은 모두 None이다."""
    row = db.execute(
        "SELECT id, owner_github_id, status FROM classrooms WHERE invite_token = ?", (token,)
    ).fetchone()
    if row is None:
        return None
    return ClassroomRef(id=row["id"], owner_github_id=row["owner_github_id"], status=row["status"])


def _link(request: Request, token: str) -> JSONResponse:
    base = request.app.state.settings.base_url.rstrip("/")
    # 로그아웃 뒤 뒤로 가기나 중간 저장소에 링크가 남지 않게 한다
    return JSONResponse({"token": token, "url": f"{base}/join/{token}"}, headers={"Cache-Control": "no-store"})


@router.get("/api/classrooms/{classroom_id}/invite")
def get_invite(granted: ManageGuard, db: Db, request: Request):
    row = db.execute("SELECT invite_token FROM classrooms WHERE id = ?", (granted.resource.id,)).fetchone()
    return _link(request, row["invite_token"])


@router.post("/api/classrooms/{classroom_id}/invite/regenerate")
def regenerate_invite(granted: ManageGuard, db: Db, request: Request):
    """새 토큰으로 바꾼다. 이전 링크는 바로 쓸 수 없게 된다(AC22). 토큰이 겹치면 다시 시도한다."""
    for _ in range(TOKEN_ATTEMPTS):
        token = secrets.token_urlsafe(16)
        try:
            with transaction(db):
                db.execute("UPDATE classrooms SET invite_token = ? WHERE id = ?", (token, granted.resource.id))
        except sqlite3.IntegrityError as err:
            if "invite_token" not in str(err):
                raise
            continue
        return _link(request, token)
    raise HTTPException(status_code=503, detail="링크를 만들지 못했습니다. 잠시 뒤 다시 시도해 주세요.")
