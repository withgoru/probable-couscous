"""C8: 권한 판단은 `authz.decide` 한 곳에서만 한다.

라우트는 `guard(...)` 의존성으로 이 함수를 부르고, 부르지 않는 라우트는 공개 목록에 이름이 있어야 한다.
"""

import re
from pathlib import Path
from typing import Annotated

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from app import authz
from app.authz import (
    PUBLIC_ROUTES,
    Action,
    Actor,
    ClassroomRef,
    Decision,
    Granted,
    decide,
    get_actor,
    guard,
    guard_account,
    registered_routes,
    routes_without_authz,
)
from app.config import Settings
from app.main import create_app

APP_DIR = Path(__file__).resolve().parents[1] / "app"

OWN = ClassroomRef(id=1, owner_github_id=100, status="active")
OWN_ARCHIVED = ClassroomRef(id=1, owner_github_id=100, status="archived")
OTHER = ClassroomRef(id=2, owner_github_id=200, status="active")

OWNER = Actor.professor(100)
STRANGER = Actor.professor(999)
MEMBER = Actor.student(membership_id=7, classroom_id=1)
MEMBER_OF_OTHER = Actor.student(membership_id=8, classroom_id=2)
ANON = Actor.anonymous()

OWNER_ONLY = [
    Action.CLASSROOM_MANAGE,
    Action.CLASSROOM_CLONE,
    Action.ROSTER_MANAGE,
    Action.JOINREQUEST_DECIDE,
    Action.PENDINGAUTH_VIEW,
]


# --- 허용·거부 표 -----------------------------------------------------------


@pytest.mark.parametrize("action", OWNER_ONLY)
def test_owner_only_actions(action):
    assert decide(OWNER, action, OWN).allowed
    assert decide(OWNER, action, OWN_ARCHIVED).allowed  # 보관된 강좌도 교수는 관리·열람한다
    denied = decide(STRANGER, action, OWN)
    assert not denied.allowed and denied.reason == "not_owner"
    assert not decide(MEMBER, action, OWN).allowed  # 학생은 관리할 수 없다
    anon = decide(ANON, action, OWN)
    assert not anon.allowed and anon.reason == "not_logged_in"


def test_classroom_read_by_owner_member_and_others():
    assert decide(OWNER, Action.CLASSROOM_READ, OWN).allowed
    assert decide(OWNER, Action.CLASSROOM_READ, OWN_ARCHIVED).allowed  # 기록 보기
    assert decide(STRANGER, Action.CLASSROOM_READ, OWN).reason == "not_owner"
    assert decide(MEMBER, Action.CLASSROOM_READ, OWN).allowed
    assert decide(MEMBER, Action.CLASSROOM_READ, OWN_ARCHIVED).reason == "archived"
    assert decide(MEMBER_OF_OTHER, Action.CLASSROOM_READ, OWN).reason == "not_member"
    assert decide(ANON, Action.CLASSROOM_READ, OWN).reason == "not_logged_in"


@pytest.mark.parametrize("actor", [ANON, MEMBER, MEMBER_OF_OTHER, OWNER, STRANGER])
def test_student_enter_depends_only_on_the_classroom_being_active(actor):
    # 초대 링크로 입장하는 사람은 아직 로그인하지 않았다. 보관된 강좌만 막는다(AC10)
    assert decide(actor, Action.STUDENT_ENTER, OWN).allowed
    archived = decide(actor, Action.STUDENT_ENTER, OWN_ARCHIVED)
    assert not archived.allowed and archived.reason == "archived"


def test_account_level_action_me_read_needs_a_professor():
    assert decide(OWNER, Action.ME_READ, None).allowed
    assert decide(STRANGER, Action.ME_READ, None).allowed  # 강좌와 무관하다
    assert decide(ANON, Action.ME_READ, None).reason == "not_logged_in"
    assert decide(MEMBER, Action.ME_READ, None).reason == "forbidden"


@pytest.mark.parametrize("action", [Action.CLASSROOM_CREATE, Action.CLASSROOM_LIST])
def test_creating_and_listing_classrooms_are_professor_only_account_actions(action):
    assert decide(OWNER, action, None).allowed
    assert decide(STRANGER, action, None).allowed  # 어느 교수든 자기 강좌를 만들고 목록을 본다
    assert decide(ANON, action, None).reason == "not_logged_in"
    assert decide(MEMBER, action, None).reason == "forbidden"


def test_unknown_action_is_denied_by_default():
    d = decide(OWNER, "classroom.delete", OWN)  # type: ignore[arg-type]
    assert d == Decision(False, "unknown_action")


def test_decision_is_truthy_only_when_allowed():
    assert bool(decide(OWNER, Action.CLASSROOM_READ, OWN)) is True
    assert bool(decide(ANON, Action.CLASSROOM_READ, OWN)) is False


# --- 라우트에 거는 의존성 -----------------------------------------------------


CLASSROOMS = {1: OWN, 2: OTHER, 3: ClassroomRef(id=3, owner_github_id=100, status="archived")}


def load_classroom(classroom_id: int) -> ClassroomRef | None:
    return CLASSROOMS.get(classroom_id)


ReadGuard = Annotated[Granted, Depends(guard(Action.CLASSROOM_READ, load_classroom))]
ManageGuard = Annotated[Granted, Depends(guard(Action.ROSTER_MANAGE, load_classroom))]


def make_app(actor: Actor) -> TestClient:
    app = FastAPI()

    @app.get("/c/{classroom_id}")
    def read(granted: ReadGuard):
        return {"id": granted.resource.id, "actor": granted.actor.kind}

    @app.post("/c/{classroom_id}/roster")
    def manage(granted: ManageGuard):
        return {"ok": True}

    app.dependency_overrides[get_actor] = lambda: actor
    return TestClient(app)


def test_guard_lets_the_owner_through_and_hands_over_the_resource():
    res = make_app(OWNER).get("/c/1")
    assert res.status_code == 200
    assert res.json() == {"id": 1, "actor": "professor"}


def test_guard_gives_401_with_login_message_when_anonymous():
    res = make_app(ANON).get("/c/1")
    assert res.status_code == 401
    assert "로그인" in res.json()["detail"]


def test_guard_gives_403_with_ac8_message_for_another_professors_classroom():
    res = make_app(STRANGER).get("/c/1")
    assert res.status_code == 403
    assert res.json()["detail"] == "이 강좌를 볼 권한이 없습니다."


def test_guard_gives_archived_message_to_students_of_archived_classroom():
    archived_member = Actor.student(membership_id=7, classroom_id=3)
    res = make_app(archived_member).get("/c/3")
    assert res.status_code == 403
    assert res.json()["detail"] == "이 강좌는 보관되었습니다. 교수님께 문의해 주세요."


def test_guard_gives_404_when_the_classroom_does_not_exist():
    res = make_app(OWNER).get("/c/999")
    assert res.status_code == 404


def test_guard_does_not_reveal_whether_a_classroom_exists_to_anonymous_visitors():
    # 로그인하지 않은 사람에게는 없는 강좌든 있는 강좌든 같은 401이다
    assert make_app(ANON).get("/c/999").status_code == 401
    assert make_app(ANON).get("/c/1").status_code == 401


def test_guard_blocks_students_from_manage_actions_on_the_route():
    assert make_app(MEMBER).post("/c/1/roster").status_code == 403
    assert make_app(OWNER).post("/c/1/roster").status_code == 200


def test_guard_really_calls_decide(monkeypatch):
    calls = []
    real = authz.decide

    def spy(actor, action, classroom):
        calls.append((actor.kind, action, classroom.id))
        return real(actor, action, classroom)

    monkeypatch.setattr(authz, "decide", spy)
    make_app(OWNER).get("/c/1")
    assert calls == [("professor", Action.CLASSROOM_READ, 1)]


def test_guard_account_protects_routes_that_have_no_classroom():
    app = FastAPI()

    @app.get("/me")
    def me(granted: Annotated[Granted, Depends(guard_account(Action.ME_READ))]):
        return {"kind": granted.actor.kind}

    app.dependency_overrides[get_actor] = lambda: OWNER
    assert TestClient(app).get("/me").json() == {"kind": "professor"}
    app.dependency_overrides[get_actor] = lambda: ANON
    assert TestClient(app).get("/me").status_code == 401
    app.dependency_overrides[get_actor] = lambda: MEMBER
    assert TestClient(app).get("/me").status_code == 403
    assert ("GET", "/me") not in routes_without_authz(app)


# --- 라우트 전수 검사 -----------------------------------------------------------


def real_app():
    return create_app(Settings(client_dist=Path("/nonexistent")))


@pytest.mark.constitution
def test_c8_every_route_calls_authz_or_is_explicitly_public():
    missing = routes_without_authz(real_app())
    assert missing == [], f"권한 판단(guard)이 없고 공개 목록에도 없는 라우트: {missing}"


@pytest.mark.constitution
def test_c8_public_routes_list_has_no_stale_entries():
    stale = set(PUBLIC_ROUTES) - set(registered_routes(real_app()))
    assert stale == set(), f"더 이상 없는 라우트가 공개 목록에 남아 있다: {stale}"


@pytest.mark.constitution
def test_c8_check_sees_routes_added_with_include_router():
    # FastAPI는 include_router로 붙인 라우트를 app.routes에 풀어 두지 않는다. 검사가 그 안까지 보지 못하면
    # 포함된 라우터의 모든 라우트가 검사 없이 통과한다(헛통과). 실제 앱의 라우트가 보이는지 확인한다
    app = real_app()
    seen = set(registered_routes(app))
    assert {("GET", "/api/me"), ("POST", "/api/auth/logout"), ("GET", "/api/auth/github/login")} <= seen
    flagged = routes_without_authz(app)
    assert ("GET", "/api/me") not in flagged  # guard가 걸려 있다
    assert ("POST", "/api/auth/logout") not in flagged  # 공개 목록에 있다


@pytest.mark.constitution
def test_c8_unknown_kinds_of_routes_are_not_waved_through():
    from starlette.routing import BaseRoute

    class Mystery(BaseRoute):
        def matches(self, scope):
            return None, {}

        async def handle(self, scope, receive, send):
            pass

    app = real_app()
    app.router.routes.append(Mystery())
    assert ("UNKNOWN", "Mystery") in routes_without_authz(app)


def test_included_router_without_guard_is_flagged():
    from fastapi import APIRouter

    router = APIRouter()

    @router.get("/api/leak")
    def leak():
        return []

    app = real_app()
    app.include_router(router)
    assert ("GET", "/api/leak") in routes_without_authz(app)


@pytest.mark.constitution
def test_c8_ownership_is_compared_only_inside_authz():
    # 소유자 비교(화면이나 개별 라우트에 흩어 놓은 권한 판단)를 막는다. SQL의 WHERE 조건은 해당하지 않는다
    pattern = re.compile(r"owner_github_id\s*(==|!=)|(==|!=)\s*\w*\.?owner_github_id")
    offenders = [
        p.name for p in APP_DIR.rglob("*.py") if p.name != "authz.py" and pattern.search(p.read_text())
    ]
    assert offenders == [], f"authz.py 밖에서 소유자를 비교하는 파일: {offenders}"


def test_checker_flags_a_route_without_guard():
    app = real_app()

    @app.get("/api/secret-classrooms")
    def leak():
        return []

    assert ("GET", "/api/secret-classrooms") in routes_without_authz(app)


def test_checker_accepts_a_guarded_route_and_a_listed_public_route():
    app = real_app()

    @app.get("/api/classrooms/{classroom_id}")
    def ok(granted: ReadGuard):
        return {}

    flagged = routes_without_authz(app)
    assert ("GET", "/api/classrooms/{classroom_id}") not in flagged
    assert ("GET", "/api/health") not in flagged
