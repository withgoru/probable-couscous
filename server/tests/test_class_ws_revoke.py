"""002 T011: 명단에서 빠졌거나 로그인이 끊긴 학생의 수업 연결 닫기(AC44, C8, C9).

- 001의 빼기·로그인 끊기가 저장을 마친 뒤 수업 방에 `member_revoked{멤버십}`을 발행한다.
- 그 학생의 연결만 `goodbye{reason, message}`를 받고 닫힌다(닫힘 코드 4403). 다른 학생·교수 연결은 그대로다.
- 다시 연결하면 거절된다. 교수 화면에는 누가 빠졌는지 보내지 않는다(현황 숫자만 바뀐다).
"""

import pytest
from conftest import ORIGIN
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect
from test_class_ws import connect, drain, goto, hang_guard, settle, start, until  # noqa: F401  (hang_guard는 fixture)
from test_deck_serving import classroom_with_deck, enroll, entered_student

from app.db import connect as db_connect
from app.realtime import InMemoryRoomBus

REMOVED = {
    "type": "goodbye",
    "reason": "removed",
    "message": "수강생 명단에서 빠져 이 수업을 볼 수 없습니다. 교수님께 문의해 주세요.",
}
SIGNED_OUT = {
    "type": "goodbye",
    "reason": "signed_out",
    "message": "이 강좌에서 로그아웃되었습니다. 강좌 링크를 다시 열어 이메일 인증부터 해 주세요.",
}


def two_students(world):
    prof, cid, sid, _, token = classroom_with_deck(world)
    kim = enroll(prof, cid, "kim@x.kr", "1")
    lee = enroll(prof, cid, "lee@x.kr", "2")
    kim_client = entered_student(world, token, "kim@x.kr")
    lee_client = entered_student(world, token, "lee@x.kr")
    start(prof, cid, sid)
    return prof, cid, sid, (kim, kim_client), (lee, lee_client)


def remove(prof, cid, entry):
    assert prof.delete(f"/api/classrooms/{cid}/roster/{entry}", headers=ORIGIN).status_code == 200


def revoke(prof, cid, entry):
    return prof.post(f"/api/classrooms/{cid}/roster/{entry}/revoke-login", headers=ORIGIN)


def until_seen(ws, type_, seen):
    """`until`과 같지만 건너뛴 메시지까지 `seen`에 모은다."""
    while True:
        message = ws.receive_json()
        seen.append(message)
        if message["type"] == type_:
            return message


def closed_with_goodbye(ws, goodbye):
    assert until(ws, "goodbye") == goodbye
    with pytest.raises(WebSocketDisconnect) as err:
        ws.receive_json()
    assert err.value.code == 4403


@pytest.mark.parametrize("how", ["remove", "revoke"])
def test_only_that_students_connection_is_closed(world, how):
    prof, cid, sid, (kim, kim_client), (_, lee_client) = two_students(world)
    with connect(prof, cid) as teacher, connect(kim_client, cid) as kim_ws, connect(lee_client, cid) as lee_ws:
        until(kim_ws, "ready")
        until(lee_ws, "ready")
        assert drain(world, teacher, cid)[-1] == {"type": "presence", "follow": 2, "browse": 0}
        if how == "remove":
            remove(prof, cid, kim)
        else:
            world.clock.advance(seconds=1)
            assert revoke(prof, cid, kim).status_code == 200
        closed_with_goodbye(kim_ws, REMOVED if how == "remove" else SIGNED_OUT)
        seen = []
        assert until_seen(teacher, "presence", seen) == {"type": "presence", "follow": 1, "browse": 0}
        # 남은 학생과 교수 연결은 그대로 쓴다
        goto(teacher, sid, 2, 0, req="after")
        assert until_seen(teacher, "ack", seen)["req"] == "after"
        assert until(lee_ws, "position")["current"] == {"slide": 2, "click": 0}
        seen += drain(world, teacher, cid)
        # 교수 화면에는 누가 빠졌는지 오지 않는다(현황 숫자만 바뀐다)
        assert [m["type"] for m in seen if m["type"] not in ("presence", "ack", "position")] == []


def test_every_screen_of_that_student_is_closed(world):
    prof, cid, _, (kim, kim_client), _ = two_students(world)
    with connect(kim_client, cid) as phone, connect(kim_client, cid) as laptop:
        until(phone, "ready")
        until(laptop, "ready")
        remove(prof, cid, kim)
        closed_with_goodbye(phone, REMOVED)
        closed_with_goodbye(laptop, REMOVED)


@pytest.mark.parametrize("how", ["remove", "revoke"])
def test_reconnecting_is_refused(world, how):
    prof, cid, _, (kim, kim_client), (_, lee_client) = two_students(world)
    if how == "remove":
        remove(prof, cid, kim)
    else:
        world.clock.advance(seconds=1)
        revoke(prof, cid, kim)
    with pytest.raises(WebSocketDenialResponse) as err, connect(kim_client, cid):
        pass
    assert err.value.status_code == 403
    with connect(lee_client, cid) as ws:
        assert until(ws, "ready")["role"] == "student"


def test_a_student_in_another_classroom_is_not_touched(world):
    # 다른 강좌의 같은 멤버십 번호가 섞이지 않는다(C5): 그 강좌 방에만 발행한다
    prof, cid, _, (kim, _), _ = two_students(world)
    _, other_cid, other_sid, _, other_token = classroom_with_deck(world, name="다른 강좌")
    enroll(prof, other_cid, "park@x.kr", "9")
    park = entered_student(world, other_token, "park@x.kr")
    start(prof, other_cid, other_sid)
    with connect(park, other_cid) as ws:
        until(ws, "ready")
        remove(prof, cid, kim)
        settle(ws)
        assert drain(world, ws, other_cid) == []


def test_revoking_someone_who_never_entered_publishes_nothing(world):
    prof, cid, _, _, _ = two_students(world)
    never = enroll(prof, cid, "choi@x.kr", "3")
    bus = world.app.state.bus
    seen = []
    real = bus.publish
    bus.publish = lambda room, event: (seen.append(event), real(room, event))
    assert revoke(prof, cid, never).status_code == 409
    remove(prof, cid, never)  # 입장한 적 없는 학생을 빼도 닫을 연결이 없다
    assert [e for e in seen if e["type"] == "member_revoked"] == []


class CheckingBus(InMemoryRoomBus):
    """`member_revoked`를 발행하는 순간 DB에 이미 로그인 끊기가 기록됐는지 적는다."""

    def __init__(self, database_path):
        super().__init__()
        self.database_path = database_path
        self.checked = []

    def publish(self, room, event):
        if event.get("type") == "member_revoked":
            with db_connect(self.database_path) as db:
                row = db.execute(
                    "SELECT reverify_after FROM memberships WHERE id = ?", (event["membership_id"],)
                ).fetchone()
            self.checked.append(row["reverify_after"] is not None)
        super().publish(room, event)


def test_the_close_is_published_after_saving(world):
    world.app.state.bus = bus = CheckingBus(world.settings.database_path)
    prof, cid, _, (kim, _), (lee, _) = two_students(world)
    remove(prof, cid, kim)
    world.clock.advance(seconds=1)
    revoke(prof, cid, lee)
    assert bus.checked == [True, True]
