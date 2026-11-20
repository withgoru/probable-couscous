"""권한 판단은 이 모듈의 `decide` 한 곳에서만 한다(C8).

화면이나 개별 라우트에 권한 판단을 흩어 놓지 않는다. 라우트는 `guard(...)` 의존성으로 이 함수를 부르고,
부르지 않는 라우트는 `PUBLIC_ROUTES`에 이름이 있어야 한다. 테스트가 라우트를 전수 검사한다.
"""

import sqlite3
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Annotated, Any, Literal

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.dependencies.models import Dependant
from fastapi.routing import APIWebSocketRoute

from app.auth import SESSION_COOKIE, hash_token
from app.db import get_db


class Action(StrEnum):
    CLASSROOM_READ = "classroom.read"
    CLASSROOM_MANAGE = "classroom.manage"
    ROSTER_MANAGE = "roster.manage"
    JOINREQUEST_DECIDE = "joinrequest.decide"
    PENDINGAUTH_VIEW = "pendingauth.view"
    STUDENT_ENTER = "student.enter"
    # 강좌와 무관한 계정 단계 행동. 로그인한 교수만 할 수 있다
    ME_READ = "me.read"
    CLASSROOM_CREATE = "classroom.create"
    CLASSROOM_LIST = "classroom.list"


@dataclass(frozen=True)
class Actor:
    kind: Literal["anonymous", "professor", "student"]
    github_id: int | None = None
    membership_id: int | None = None
    classroom_id: int | None = None

    @classmethod
    def anonymous(cls) -> "Actor":
        return cls("anonymous")

    @classmethod
    def professor(cls, github_id: int) -> "Actor":
        return cls("professor", github_id=github_id)

    @classmethod
    def student(cls, membership_id: int, classroom_id: int) -> "Actor":
        return cls("student", membership_id=membership_id, classroom_id=classroom_id)


@dataclass(frozen=True)
class ClassroomRef:
    id: int
    owner_github_id: int
    status: Literal["active", "archived"]


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason: str = "ok"

    def __bool__(self) -> bool:
        return self.allowed


_OWNER_ONLY = {
    Action.CLASSROOM_MANAGE,
    Action.ROSTER_MANAGE,
    Action.JOINREQUEST_DECIDE,
    Action.PENDINGAUTH_VIEW,
}


_ACCOUNT_LEVEL = {Action.ME_READ, Action.CLASSROOM_CREATE, Action.CLASSROOM_LIST}


def decide(actor: Actor, action: Action | str, classroom: ClassroomRef | None = None) -> Decision:
    """이 행위자가 이 강좌에서 이 행동을 할 수 있는가. 기본은 거부다."""
    try:
        action = Action(action)
    except ValueError:
        return Decision(False, "unknown_action")

    if action in _ACCOUNT_LEVEL:  # 강좌와 무관하다
        if actor.kind == "anonymous":
            return Decision(False, "not_logged_in")
        return Decision(True) if actor.kind == "professor" else Decision(False, "forbidden")

    if classroom is None:  # 강좌 단위 행동인데 대상이 없다
        return Decision(False, "unknown_action")

    if action is Action.STUDENT_ENTER:
        # 초대 링크로 들어오는 사람은 아직 로그인하지 않았다. 보관된 강좌만 막는다
        return Decision(True) if classroom.status == "active" else Decision(False, "archived")

    if actor.kind == "anonymous":
        return Decision(False, "not_logged_in")

    if action in _OWNER_ONLY:
        if actor.kind != "professor":
            return Decision(False, "forbidden")
        return Decision(True) if actor.github_id == classroom.owner_github_id else Decision(False, "not_owner")

    if action is Action.CLASSROOM_READ:
        if actor.kind == "professor":
            return Decision(True) if actor.github_id == classroom.owner_github_id else Decision(False, "not_owner")
        if actor.classroom_id != classroom.id:
            return Decision(False, "not_member")
        return Decision(True) if classroom.status == "active" else Decision(False, "archived")

    return Decision(False, "unknown_action")


# --- 라우트에 거는 의존성 ---------------------------------------------------------

_DENIAL: dict[str, tuple[int, str]] = {
    "not_logged_in": (401, "로그인이 필요합니다. 로그인한 뒤 다시 시도해 주세요."),
    "not_owner": (403, "이 강좌를 볼 권한이 없습니다."),
    "forbidden": (403, "이 작업을 할 권한이 없습니다."),
    "not_member": (403, "이 강좌에 입장한 학생만 볼 수 있습니다."),
    "archived": (403, "이 강좌는 보관되었습니다. 교수님께 문의해 주세요."),
    "unknown_action": (403, "허용되지 않은 요청입니다."),
}
_NOT_FOUND = "찾을 수 없는 강좌입니다."


@dataclass(frozen=True)
class Granted:
    actor: Actor
    resource: ClassroomRef | None = None


def get_actor(request: Request, db: Annotated[sqlite3.Connection, Depends(get_db)]) -> Actor:
    """요청한 사람이 누구인가. 유효한 교수 로그인 상태가 있으면 교수, 아니면 익명이다.

    학생의 로그인 상태(기기 로그인)는 학생 입장 작업(T020)에서 여기에 더한다.
    """
    token = request.cookies.get(SESSION_COOKIE)
    if token:
        now = request.app.state.clock.now().isoformat()
        row = db.execute(
            "SELECT github_id FROM professor_sessions "
            "WHERE token_hash = ? AND revoked_at IS NULL AND expires_at > ?",
            (hash_token(token), now),
        ).fetchone()
        if row is not None:
            return Actor.professor(row["github_id"])
    return Actor.anonymous()


def _deny(decision: Decision) -> HTTPException:
    status, message = _DENIAL.get(decision.reason, _DENIAL["unknown_action"])
    return HTTPException(status_code=status, detail=message)


def guard(action: Action, load: Callable[..., ClassroomRef | None]) -> Callable[..., Granted]:
    """라우트에 `Depends(guard(행동, 강좌 불러오기))`로 건다. 허용되면 행위자와 강좌를 돌려준다."""

    def check(
        actor: Annotated[Actor, Depends(get_actor)],
        classroom: Annotated[ClassroomRef | None, Depends(load)],
    ) -> Granted:
        if classroom is None:
            # 로그인하지 않은 사람에게는 강좌가 있는지 없는지 알려 주지 않는다
            if actor.kind == "anonymous" and action is not Action.STUDENT_ENTER:
                status, message = _DENIAL["not_logged_in"]
                raise HTTPException(status_code=status, detail=message)
            raise HTTPException(status_code=404, detail=_NOT_FOUND)
        decision = decide(actor, action, classroom)
        if not decision:
            raise _deny(decision)
        return Granted(actor=actor, resource=classroom)

    check.__authz_guard__ = True  # type: ignore[attr-defined]
    check.__authz_action__ = action  # type: ignore[attr-defined]
    return check


def guard_account(action: Action) -> Callable[..., Granted]:
    """강좌와 무관한 행동(예: 내 정보 보기)에 거는 의존성."""

    def check(actor: Annotated[Actor, Depends(get_actor)]) -> Granted:
        decision = decide(actor, action, None)
        if not decision:
            raise _deny(decision)
        return Granted(actor=actor)

    check.__authz_guard__ = True  # type: ignore[attr-defined]
    check.__authz_action__ = action  # type: ignore[attr-defined]
    return check


# 권한 판단 없이 열려 있는 라우트. 로그인 전에도 열려야 하는 것만 여기에 이름을 올린다.
# 라우트를 추가할 때 이 목록을 고치게 되므로 리뷰에서 보인다.
PUBLIC_ROUTES: frozenset[tuple[str, str]] = frozenset(
    {
        ("GET", "/api/health"),
        ("GET", "/api/auth/github/login"),  # 로그인 전에 열려야 한다
        ("GET", "/api/auth/github/callback"),
        ("POST", "/api/auth/logout"),  # 자기 로그인 상태를 지울 뿐이라 별도 판단이 없다
        ("GET", "/api/docs"),
        ("GET", "/api/openapi.json"),
        ("GET", "/{full_path:path}"),  # 클라이언트 화면(SPA)과 정적 파일
    }
)


def _has_guard(dependant: Dependant) -> bool:
    for dep in dependant.dependencies:
        if getattr(dep.call, "__authz_guard__", False) or _has_guard(dep):
            return True
    return False


def _flatten(routes: Any) -> Any:
    """include_router로 붙인 라우터를 풀어 라우트를 하나씩 돌려준다.

    FastAPI는 포함된 라우터를 app.routes에 풀어 두지 않고 `effective_route_contexts()`로만 보여 준다.
    풀린 항목도 path, methods, dependant를 가져서 같은 방식으로 검사할 수 있다.
    """
    for route in routes:
        expand = getattr(route, "effective_route_contexts", None)
        if callable(expand):
            yield from expand()
        else:
            yield route


def _methods_of(route: Any) -> set[str]:
    original = getattr(route, "original_route", route)
    if isinstance(original, APIWebSocketRoute):
        return {"WEBSOCKET"}
    return set(getattr(route, "methods", None) or {"GET"}) - {"HEAD", "OPTIONS"}


def registered_routes(app: FastAPI) -> list[tuple[str, str]]:
    """앱에 등록된 모든 (메서드, 경로). 모르는 종류의 라우트는 ("UNKNOWN", 종류)로 보인다."""
    found: list[tuple[str, str]] = []
    for route in _flatten(app.routes):
        path = getattr(route, "path", None)
        if path is None:
            found.append(("UNKNOWN", type(route).__name__))
            continue
        found.extend((method, path) for method in sorted(_methods_of(route)))
    return found


def routes_without_authz(app: FastAPI) -> list[tuple[str, str]]:
    """`guard`도 없고 `PUBLIC_ROUTES`에도 없는 라우트를 (메서드, 경로)로 돌려준다.

    모르는 종류의 라우트는 통과시키지 않고 ("UNKNOWN", 종류)로 돌려준다(fail closed).
    """
    missing: list[tuple[str, str]] = []
    for route in _flatten(app.routes):
        path = getattr(route, "path", None)
        if path is None:
            missing.append(("UNKNOWN", type(route).__name__))
            continue
        dependant = getattr(route, "dependant", None)
        guarded = dependant is not None and _has_guard(dependant)
        for method in sorted(_methods_of(route)):
            if not guarded and (method, path) not in PUBLIC_ROUTES:
                missing.append((method, path))
    return missing
