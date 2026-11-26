"""002 T009: 수업 WebSocket `/ws/class/{강좌}`(AC13, AC15, AC17, AC20, AC25, C7, C8, C13).

- 연결 때 권한을 확인한다(`class.view`). 교수·프로젝터(교수 연결에 `role=projector`)·학생을 구분하고 그 밖은 거절한다.
- 교수 `goto`: 범위 검사 → DB 기록 → 보낸 화면에 `ack{req, version}` → 방에 `position` 발행. 되돌아가도 가장 멀리 간
  위치는 줄지 않는다. 학생과 프로젝터의 `goto`는 거절한다.
- 학생 `mode{follow|browse}`에 따라 교수에게만 `presence{follow, browse}`(숫자만, C7). 학생 한 명은 한 번만 센다.
- 느린 화면은 `resync`를 받는다. 교수 연결 두 개는 같은 `position`을 받는다.
"""

import signal
import time

import pytest
from conftest import ORIGIN
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect
from test_deck_serving import classroom_with_deck, enroll, entered_student

from app.db import connect as db_connect
from app.realtime import InMemoryRoomBus, class_room

WS_ORIGIN = {"origin": "http://localhost:8000"}


@pytest.fixture(autouse=True)
def hang_guard():
    """실시간 테스트가 메시지를 기다리며 영원히 멈추지 않게 한다."""

    def boom(*_a):
        raise TimeoutError("메시지를 기다리다 10초가 지났습니다")

    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(10)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def connect(client, cid, role=None, headers=None):
    query = f"?role={role}" if role else ""
    return client.websocket_connect(
        f"ws://localhost:8000/ws/class/{cid}{query}", headers=WS_ORIGIN if headers is None else headers
    )


def start(prof, cid, sid):
    assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/start", headers=ORIGIN).status_code == 200


def live_class(world):
    """진행 중인 회차(슬라이드 4장)와 그 강좌에 입장한 학생 한 명."""
    prof, cid, sid, _, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    start(prof, cid, sid)
    return prof, cid, sid, token, student


def position_row(world, sid):
    with world.db() as db:
        r = db.execute("SELECT * FROM class_sessions WHERE id = ?", (sid,)).fetchone()
    return (r["current_slide"], r["current_click"]), r["version"]


def drain(world, ws, cid):
    """지금까지 쌓인 메시지를 모두 받는다. 끝 표시를 한 번 발행해 그 앞까지 읽는다."""
    world.app.state.bus.publish(class_room(cid), {"type": "sentinel"})
    got = []
    while True:
        message = ws.receive_json()
        if message["type"] == "sentinel":
            return got
        got.append(message)


def until(ws, type_):
    while True:
        message = ws.receive_json()
        if message["type"] == type_:
            return message


def settle(ws):
    """이 연결이 앞서 보낸 메시지를 서버가 다 처리할 때까지 기다린다(받는 쪽은 차례로 처리한다)."""
    ws.send_json({"type": "ping?", "req": "settle"})
    while True:
        message = ws.receive_json()
        if message["type"] == "error" and message["req"] == "settle":
            return


def goto(ws, sid, slide, click=0, req="r1"):
    ws.send_json({"type": "goto", "session_id": sid, "slide": slide, "click": click, "req": req})


# --- 연결 (C8) -------------------------------------------------------------------------------


def test_professor_connects_and_gets_presence(world):
    prof, cid, _, _, _ = live_class(world)
    with connect(prof, cid) as ws:
        assert ws.receive_json() == {"type": "ready", "role": "professor"}
        assert ws.receive_json() == {"type": "presence", "follow": 0, "browse": 0}


def test_projector_and_student_connect_with_their_roles(world):
    prof, cid, _, _, student = live_class(world)
    with connect(prof, cid, role="projector") as ws:
        assert ws.receive_json() == {"type": "ready", "role": "projector"}
        assert drain(world, ws, cid) == []  # 현황은 받지 않는다
    with connect(student, cid) as ws:
        assert ws.receive_json() == {"type": "ready", "role": "student"}
        assert drain(world, ws, cid) == []
    with connect(student, cid, role="projector") as ws:  # 학생이 프로젝터라고 해도 학생이다
        assert ws.receive_json() == {"type": "ready", "role": "student"}


@pytest.mark.parametrize("who", ["anonymous", "other_professor", "other_student"])
def test_nobody_else_can_connect(world, who):
    prof, cid, _, _, _ = live_class(world)
    if who == "anonymous":
        client = world.client()
    elif who == "other_professor":
        client = world.client("lee")
    else:
        _, other_cid, _, _, other_token = classroom_with_deck(world, name="다른 강좌")
        enroll(prof, other_cid, "lee@x.kr")
        client = entered_student(world, other_token, "lee@x.kr")
    with pytest.raises(WebSocketDenialResponse) as err, connect(client, cid):
        pass
    assert err.value.status_code in (401, 403)


def test_a_missing_classroom_is_refused(world):
    prof, _, _, _, _ = live_class(world)
    with pytest.raises(WebSocketDenialResponse) as err, connect(prof, 999):
        pass
    assert err.value.status_code == 404


@pytest.mark.parametrize("origin", [None, "https://evil.example"])
def test_a_page_from_another_origin_cannot_connect(world, origin):
    prof, cid, _, _, _ = live_class(world)
    headers = {} if origin is None else {"origin": origin}
    with pytest.raises(WebSocketDisconnect) as err, connect(prof, cid, headers=headers):
        pass
    assert err.value.code == 1008


# --- 넘기기 (AC13, AC17, AC20, AC25, C13) --------------------------------------------------------


class CheckingBus(InMemoryRoomBus):
    """`position`을 발행하는 순간 DB에 이미 그 버전이 기록됐는지 적는다."""

    def __init__(self, database_path):
        super().__init__()
        self.database_path = database_path
        self.checked = []

    def publish(self, room, event):
        if event.get("type") == "position":
            with db_connect(self.database_path) as db:
                (version,) = db.execute(
                    "SELECT version FROM class_sessions WHERE id = ?", (event["session_id"],)
                ).fetchone()
            self.checked.append((event["version"], version))
        super().publish(room, event)


def test_professor_goto_is_recorded_acked_then_published(world):
    world.app.state.bus = bus = CheckingBus(world.settings.database_path)
    prof, cid, sid, _, student = live_class(world)
    with connect(prof, cid) as teacher, connect(prof, cid, role="projector") as projector, connect(student, cid) as phone:
        until(teacher, "presence")
        until(projector, "ready")
        until(phone, "ready")
        goto(teacher, sid, 2, 1, req="a1")
        assert until(teacher, "ack") == {"type": "ack", "req": "a1", "version": 2}
        expected = {
            "type": "position",
            "session_id": sid,
            "current": {"slide": 2, "click": 1},
            "version": 2,
        }
        assert until(teacher, "position") == expected  # ack 다음에 발행이 온다
        assert until(projector, "position") == expected  # AC20
        assert until(phone, "position") == expected  # AC25
    assert position_row(world, sid) == ((2, 1), 2)
    assert bus.checked == [(2, 2)]  # 발행하는 순간 DB에는 이미 그 버전이 있었다


def test_going_back_is_recorded_as_the_new_position(world):
    prof, cid, sid, _, _ = live_class(world)
    with connect(prof, cid) as ws:
        until(ws, "presence")
        goto(ws, sid, 3, 2, req="a")
        until(ws, "position")
        goto(ws, sid, 1, 0, req="b")
        assert until(ws, "ack")["version"] == 3
        moved = until(ws, "position")
    assert moved == {"type": "position", "session_id": sid, "current": {"slide": 1, "click": 0}, "version": 3}
    assert position_row(world, sid) == ((1, 0), 3)


def test_two_professor_screens_get_the_same_position(world):
    # AC17: 어느 쪽에서 넘겨도 다른 쪽이 따라온다
    prof, cid, sid, _, _ = live_class(world)
    other_tab = world.client("kim")
    with connect(prof, cid) as first, connect(other_tab, cid) as second:
        until(first, "presence")
        until(second, "presence")
        goto(second, sid, 4, 0, req="x")
        assert until(first, "position")["current"] == {"slide": 4, "click": 0}
        assert until(second, "position")["current"] == {"slide": 4, "click": 0}
        assert [m["type"] for m in drain(world, first, cid)] == []  # 다른 탭은 ack를 받지 않는다


def test_going_to_the_same_place_is_acked_without_a_new_version(world):
    prof, cid, sid, _, _ = live_class(world)
    with connect(prof, cid) as ws:
        until(ws, "presence")
        goto(ws, sid, 1, 0, req="same")
        assert until(ws, "ack") == {"type": "ack", "req": "same", "version": 1}
        assert drain(world, ws, cid) == []
    assert position_row(world, sid) == ((1, 0), 1)


@pytest.mark.parametrize(
    ("slide", "click"),
    [(5, 0), (0, 0), (2, -1), ("2", 0), (2, 1.5), (True, 0), (2, 1000)],
)
def test_positions_outside_the_deck_are_refused(world, slide, click):
    prof, cid, sid, _, _ = live_class(world)
    with connect(prof, cid) as ws:
        until(ws, "presence")
        goto(ws, sid, slide, click, req="bad")
        message = until(ws, "error")
        assert message["req"] == "bad" and message["reason"] == "out_of_range"
        assert message["message"] == "그 위치로 넘길 수 없습니다. 슬라이드 범위를 확인해 주세요."
        assert drain(world, ws, cid) == []
    assert position_row(world, sid) == ((1, 0), 1)


def test_a_session_without_a_deck_stays_on_the_first_slide(world):
    prof = world.client("kim")
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "슬라이드 없음"}, headers=ORIGIN).json()["id"]
    start(prof, cid, sid)
    with connect(prof, cid) as ws:
        until(ws, "presence")
        goto(ws, sid, 2, 0, req="a")
        assert until(ws, "error")["reason"] == "out_of_range"


def test_only_the_live_session_of_this_classroom_moves(world):
    prof, cid, _sid, _, _ = live_class(world)
    scheduled = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "예정"}, headers=ORIGIN).json()["id"]
    _, other_cid, other_sid, _, _ = classroom_with_deck(world, name="다른 강좌")
    start(prof, other_cid, other_sid)
    with connect(prof, cid) as ws:
        until(ws, "presence")
        for target in (scheduled, other_sid, 9999):
            goto(ws, target, 2, 0, req=f"s{target}")
            message = until(ws, "error")
            assert (message["req"], message["reason"]) == (f"s{target}", "not_live")
            assert message["message"] == "진행 중인 수업이 아닙니다. 화면을 새로 고쳐 주세요."
    assert position_row(world, other_sid)[1] == 1
    assert position_row(world, scheduled)[1] == 0


def test_after_the_class_ends_goto_is_refused(world):
    prof, cid, sid, _, _ = live_class(world)
    with connect(prof, cid) as ws:
        until(ws, "presence")
        assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/end", headers=ORIGIN).status_code == 200
        assert until(ws, "session.updated")["status"] == "ended"  # T007의 발행도 이 연결로 온다
        goto(ws, sid, 2, 0)
        assert until(ws, "error")["reason"] == "not_live"


@pytest.mark.parametrize("role", ["student", "projector"])
def test_students_and_projectors_cannot_move_the_class(world, role):
    prof, cid, sid, _, student = live_class(world)
    client = student if role == "student" else prof
    with connect(client, cid, role="projector" if role == "projector" else None) as ws:
        until(ws, "ready")
        goto(ws, sid, 3, 0, req="no")
        message = until(ws, "error")
        assert (message["req"], message["reason"]) == ("no", "not_allowed")
        assert message["message"] == "교수 수업 화면에서만 넘길 수 있습니다."
    assert position_row(world, sid) == ((1, 0), 1)


@pytest.mark.parametrize("message", ["not json", '{"type": "dance"}', "[1, 2]", '{"type": "goto"}'])
def test_unknown_messages_are_answered_not_crashed(world, message):
    prof, cid, sid, _, _ = live_class(world)
    with connect(prof, cid) as ws:
        until(ws, "presence")
        ws.send_text(message)
        reply = until(ws, "error")
        assert reply["reason"] in ("bad_message", "out_of_range", "not_live")
        goto(ws, sid, 2, 0, req="after")  # 연결은 그대로 쓸 수 있다
        assert until(ws, "ack")["req"] == "after"


# --- 동기화 현황 (AC15, C7) ----------------------------------------------------------------------


def test_presence_counts_students_by_mode_for_professors_only(world):
    prof, cid, _, token, student = live_class(world)
    enroll(prof, cid, "lee@x.kr", "2")
    lee = entered_student(world, token, "lee@x.kr")
    with connect(prof, cid) as teacher:
        assert until(teacher, "presence") == {"type": "presence", "follow": 0, "browse": 0}
        with connect(student, cid) as kim_phone:
            until(kim_phone, "ready")
            assert until(teacher, "presence") == {"type": "presence", "follow": 1, "browse": 0}  # 처음에는 따라가는 중
            with connect(lee, cid) as lee_phone:
                until(lee_phone, "ready")
                assert until(teacher, "presence") == {"type": "presence", "follow": 2, "browse": 0}
                kim_phone.send_json({"type": "mode", "mode": "browse"})
                assert until(teacher, "presence") == {"type": "presence", "follow": 1, "browse": 1}
                assert drain(world, kim_phone, cid) == []  # 학생은 현황을 받지 않는다
            assert until(teacher, "presence") == {"type": "presence", "follow": 0, "browse": 1}
        assert until(teacher, "presence") == {"type": "presence", "follow": 0, "browse": 0}


def test_one_student_with_two_screens_counts_once(world):
    # 둘 중 하나라도 따라가면 따라가는 중이다
    prof, cid, _, _, student = live_class(world)
    with connect(prof, cid) as teacher:
        until(teacher, "presence")
        with connect(student, cid) as phone, connect(student, cid) as laptop:
            until(phone, "ready")
            until(laptop, "ready")
            laptop.send_json({"type": "mode", "mode": "browse"})
            settle(laptop)
            seen = [m for m in drain(world, teacher, cid) if m["type"] == "presence"]
            assert seen[-1] == {"type": "presence", "follow": 1, "browse": 0}
            phone.send_json({"type": "mode", "mode": "browse"})
            assert until(teacher, "presence") == {"type": "presence", "follow": 0, "browse": 1}


def test_a_new_professor_screen_gets_the_current_presence(world):
    prof, cid, _, _, student = live_class(world)
    with connect(student, cid) as phone:
        until(phone, "ready")
        phone.send_json({"type": "mode", "mode": "browse"})
        settle(phone)
        with connect(prof, cid) as teacher:
            until(teacher, "ready")
            assert teacher.receive_json() == {"type": "presence", "follow": 0, "browse": 1}


def test_a_bad_mode_is_refused(world):
    _prof, cid, _, _, student = live_class(world)
    with connect(student, cid) as phone:
        until(phone, "ready")
        phone.send_json({"type": "mode", "mode": "sleep"})
        assert until(phone, "error")["reason"] == "bad_message"


# --- 느린 화면과 정리 ---------------------------------------------------------------------------


def test_a_burst_is_either_delivered_in_full_or_replaced_by_a_resync(world):
    # test_admin_ws와 같은 확인: 넘치면 resync가 오고, 그 전까지 받은 것은 빠짐없이 순서대로다
    world.app.state.bus = InMemoryRoomBus(max_queue=3)
    _prof, cid, sid, _, student = live_class(world)
    with connect(student, cid) as phone:
        until(phone, "ready")
        bus = world.app.state.bus
        total = bus.max_queue * 5
        for i in range(total):
            bus.publish(class_room(cid), {"type": "position", "session_id": sid, "version": i})
        seen = []
        while True:
            message = phone.receive_json()
            if message["type"] == "resync":
                break
            seen.append(message["version"])
            if len(seen) == total:
                break
    assert seen == list(range(len(seen)))


def test_closing_a_screen_removes_its_subscription(world):
    _prof, cid, _, _, student = live_class(world)
    bus = world.app.state.bus
    with connect(student, cid) as phone:
        until(phone, "ready")
        assert bus.subscriber_count(class_room(cid)) == 1
    for _ in range(100):  # 서버가 끊김을 알아채는 데 잠깐 걸린다
        if bus.subscriber_count(class_room(cid)) == 0:
            break
        time.sleep(0.02)
    assert bus.subscriber_count(class_room(cid)) == 0
