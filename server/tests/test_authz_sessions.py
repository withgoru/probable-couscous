"""002 T003: 회차·수업 행동의 권한 판단 표(C8)와, 슬라이드 묶음·수업 연결 경로가 검사 없이 열리지 않는지.

행동
- session.manage  회차와 슬라이드 묶음 관리(소유 교수. 보관된 강좌도 관리는 된다)
- session.present 수업 시작·종료·이어서·넘기기·보내기·거두기(소유 교수, 진행 중인 강좌만. AC11)
- class.view      회차 목록, 현재 상태, 묶음 파일(소유 교수 또는 그 강좌에 입장한 학생. AC44)
- deck.notes      발표자 노트(소유 교수만. AC30)
"""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.authz import PUBLIC_ROUTES, Action, Actor, ClassroomRef, decide, routes_without_authz
from app.config import Settings
from app.main import create_app

OWN = ClassroomRef(id=1, owner_github_id=100, status="active")
OWN_ARCHIVED = ClassroomRef(id=1, owner_github_id=100, status="archived")

OWNER = Actor.professor(100)
STRANGER = Actor.professor(999)
MEMBER = Actor.student(membership_id=7, classroom_id=1)
MEMBER_OF_OTHER = Actor.student(membership_id=8, classroom_id=2)
ANON = Actor.anonymous()

NO_PERMISSION = "no_class_permission"  # AC43 "이 강좌에 대한 권한이 없습니다."


def reasons(action, classroom):
    return {
        name: decide(actor, action, classroom).reason
        for name, actor in [
            ("owner", OWNER),
            ("stranger", STRANGER),
            ("member", MEMBER),
            ("member_of_other", MEMBER_OF_OTHER),
            ("anon", ANON),
        ]
    }


def test_session_manage_is_for_the_owner_even_when_archived():
    expected = {
        "owner": "ok",
        "stranger": NO_PERMISSION,
        "member": NO_PERMISSION,
        "member_of_other": NO_PERMISSION,
        "anon": "not_logged_in",
    }
    assert reasons(Action.SESSION_MANAGE, OWN) == expected
    assert reasons(Action.SESSION_MANAGE, OWN_ARCHIVED) == expected


def test_session_present_is_for_the_owner_of_an_active_classroom():
    assert reasons(Action.SESSION_PRESENT, OWN) == {
        "owner": "ok",
        "stranger": NO_PERMISSION,
        "member": NO_PERMISSION,
        "member_of_other": NO_PERMISSION,
        "anon": "not_logged_in",
    }
    # AC11: 보관된 강좌에서는 수업을 시작할 수 없다. 권한이 없는 사람에게는 보관 여부를 먼저 알리지 않는다
    assert reasons(Action.SESSION_PRESENT, OWN_ARCHIVED) == {
        "owner": "archived_no_class",
        "stranger": NO_PERMISSION,
        "member": NO_PERMISSION,
        "member_of_other": NO_PERMISSION,
        "anon": "not_logged_in",
    }


def test_class_view_is_for_the_owner_and_students_who_entered_this_classroom():
    assert reasons(Action.CLASS_VIEW, OWN) == {
        "owner": "ok",
        "stranger": NO_PERMISSION,
        "member": "ok",
        "member_of_other": "not_member",
        "anon": "not_logged_in",
    }
    # 보관된 강좌: 교수는 기록을 보고, 학생은 입장이 닫혀 있다(001 AC10과 같다)
    assert reasons(Action.CLASS_VIEW, OWN_ARCHIVED) == {
        "owner": "ok",
        "stranger": NO_PERMISSION,
        "member": "archived",
        "member_of_other": "not_member",
        "anon": "not_logged_in",
    }


@pytest.mark.parametrize("classroom", [OWN, OWN_ARCHIVED])
def test_deck_notes_are_only_for_the_owner(classroom):
    assert reasons(Action.DECK_NOTES, classroom) == {
        "owner": "ok",
        "stranger": NO_PERMISSION,
        "member": NO_PERMISSION,
        "member_of_other": NO_PERMISSION,
        "anon": "not_logged_in",
    }


@pytest.mark.parametrize("action", [Action.SESSION_MANAGE, Action.SESSION_PRESENT, Action.CLASS_VIEW, Action.DECK_NOTES])
def test_session_actions_need_a_classroom(action):
    assert decide(OWNER, action, None).reason == "unknown_action"


def test_denial_messages_match_the_spec():
    from app.authz import Decision, _deny

    assert _deny(Decision(False, NO_PERMISSION)).detail == "이 강좌에 대한 권한이 없습니다."  # AC43
    assert _deny(Decision(False, NO_PERMISSION)).status_code == 403
    assert _deny(Decision(False, "archived_no_class")).detail == "보관된 강좌는 수업을 시작할 수 없습니다."  # AC11
    assert _deny(Decision(False, "archived_no_class")).status_code == 409


# --- 경로 검사(C8 넓히기) ------------------------------------------------------------


def app_with_client(tmp_path: Path) -> TestClient:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<!doctype html><title>client</title>")
    (tmp_path / "decks").mkdir()
    return TestClient(create_app(Settings(client_dist=dist, database_path=tmp_path / "app.db"), start_mail_worker=False))


@pytest.mark.constitution
@pytest.mark.parametrize("path", ["/decks/1/index.html", "/decks/1/classroom-deck.json", "/decks", "/ws/class/1"])
def test_c8_deck_and_class_paths_are_never_served_by_the_public_client_fallback(tmp_path, path):
    # 화면(SPA) 대체 경로는 검사 없이 열려 있다. 슬라이드 묶음이나 수업 연결 주소가 그쪽으로 빠지면
    # 권한 판단 없이 응답하게 된다. 전용 라우트가 없으면 404여야 한다(fail closed)
    with app_with_client(tmp_path) as client:
        res = client.get(path)
    assert res.status_code == 404
    assert "client" not in res.text


@pytest.mark.constitution
def test_c8_deck_and_class_paths_cannot_be_listed_as_public():
    leaked = [(m, p) for m, p in PUBLIC_ROUTES if p.startswith(("/decks", "/ws", "/api/class"))]
    assert leaked == []


@pytest.mark.constitution
def test_c8_check_flags_an_unguarded_deck_route_and_class_socket():
    app = create_app(Settings(client_dist=Path("/nonexistent")))

    @app.get("/decks/{deck_id}/{path:path}")
    def leak_deck(deck_id: int, path: str):
        return {}

    @app.websocket("/ws/class/{classroom_id}")
    async def leak_socket(websocket):
        await websocket.close()

    flagged = routes_without_authz(app)
    assert ("GET", "/decks/{deck_id}/{path:path}") in flagged
    assert ("WEBSOCKET", "/ws/class/{classroom_id}") in flagged
