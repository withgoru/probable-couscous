"""003 T002: 출석 행동의 권한 판단 표(C8, AC26, AC27).

행동
- attendance.manage 출석 받는 시간 설정, 출석 현황, CSV, 요청 처리, 직접 바꾸기, 코드 받기.
                    소유 교수만, 보관된 강좌도 된다(끝난 뒤 정리용). 거절 문구는 "이 강좌에 대한 권한이 없습니다."
- attendance.self   학생 본인의 출석과 수기 요청. 그 강좌에 입장한 학생만, 보관된 강좌는 안 된다. 교수는 할 수 없다
- 열기·연장·마감·다시 받기는 002의 session.present를 쓴다(이 파일에서 다시 보지 않는다)
"""

import pytest

from app.authz import Action, Actor, ClassroomRef, Decision, _deny, decide

OWN = ClassroomRef(id=1, owner_github_id=100, status="active")
OWN_ARCHIVED = ClassroomRef(id=1, owner_github_id=100, status="archived")

OWNER = Actor.professor(100)
STRANGER = Actor.professor(999)
MEMBER = Actor.student(membership_id=7, classroom_id=1)
MEMBER_OF_OTHER = Actor.student(membership_id=8, classroom_id=2)
# 로그인했지만 이 강좌에 입장하지 않은 학생. 명단에서 빠졌거나 로그인이 끊긴 학생도 이렇게 된다(class_access.class_actor)
NOT_ENTERED = Actor("student")
ANON = Actor.anonymous()

NO_PERMISSION = "no_class_permission"


def reasons(action, classroom):
    return {
        name: decide(actor, action, classroom).reason
        for name, actor in [
            ("owner", OWNER),
            ("stranger", STRANGER),
            ("member", MEMBER),
            ("member_of_other", MEMBER_OF_OTHER),
            ("not_entered", NOT_ENTERED),
            ("anon", ANON),
        ]
    }


@pytest.mark.parametrize("classroom", [OWN, OWN_ARCHIVED])
def test_attendance_manage_is_for_the_owner_even_when_archived(classroom):
    # AC26: 다른 교수나 학생에게는 "이 강좌에 대한 권한이 없습니다."
    assert reasons(Action.ATTENDANCE_MANAGE, classroom) == {
        "owner": "ok",
        "stranger": NO_PERMISSION,
        "member": NO_PERMISSION,
        "member_of_other": NO_PERMISSION,
        "not_entered": NO_PERMISSION,
        "anon": "not_logged_in",
    }


def test_attendance_self_is_for_students_who_entered_this_active_classroom():
    # AC27: 학생은 자기 출석만. 교수는 학생 대신 코드로 출석하거나 요청을 보내지 않는다(직접 바꾸기는 manage)
    assert reasons(Action.ATTENDANCE_SELF, OWN) == {
        "owner": "forbidden",
        "stranger": "forbidden",
        "member": "ok",
        "member_of_other": "not_member",
        "not_entered": "not_member",  # AC27
        "anon": "not_logged_in",
    }
    assert reasons(Action.ATTENDANCE_SELF, OWN_ARCHIVED) == {
        "owner": "forbidden",
        "stranger": "forbidden",
        "member": "archived",
        "member_of_other": "not_member",
        "not_entered": "not_member",  # AC27
        "anon": "not_logged_in",
    }


@pytest.mark.parametrize("action", [Action.ATTENDANCE_MANAGE, Action.ATTENDANCE_SELF])
def test_attendance_actions_need_a_classroom(action):
    for actor in (OWNER, MEMBER):
        assert decide(actor, action, None).reason == "unknown_action"


def test_attendance_actions_have_stable_names():
    # 라우트와 화면이 문자열로 부를 수 있다
    assert decide(OWNER, "attendance.manage", OWN).allowed
    assert decide(MEMBER, "attendance.self", OWN).allowed


def test_attendance_denials_use_the_spec_wording():
    assert _deny(Decision(False, NO_PERMISSION)).detail == "이 강좌에 대한 권한이 없습니다."  # AC26
    assert _deny(Decision(False, NO_PERMISSION)).status_code == 403
    assert _deny(Decision(False, "forbidden")).status_code == 403
