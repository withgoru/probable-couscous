"""AC40, AC45의 실시간(C13, C15): /ws/admin/{classroom_id}. 연결은 교수 로그인과 강좌 소유가 필요하고,
이벤트는 DB 기록이 끝난 뒤에 번호만 알린다(개인정보 없음). 화면은 이벤트를 받으면 HTTP로 목록을 다시 받는다."""

import re
import signal

import pytest
from conftest import ORIGIN
from starlette.testclient import WebSocketDenialResponse
from starlette.websockets import WebSocketDisconnect

from app.realtime import admin_room

WS_ORIGIN = {"origin": "http://localhost:8000"}


@pytest.fixture(autouse=True)
def hang_guard():
    """실시간 테스트가 이벤트를 기다리며 영원히 멈추지 않게 한다."""

    def boom(*_a):
        raise TimeoutError("이벤트를 기다리다 10초가 지났습니다")

    old = signal.signal(signal.SIGALRM, boom)
    signal.alarm(10)
    yield
    signal.alarm(0)
    signal.signal(signal.SIGALRM, old)


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def connect(client, cid, headers=None):
    return client.websocket_connect(f"ws://localhost:8000/ws/admin/{cid}", headers=WS_ORIGIN if headers is None else headers)


def drain(world, ws, cid):
    """지금까지 쌓인 이벤트를 모두 받는다. 끝 표시를 한 번 발행해 그 앞까지 읽는다."""
    world.app.state.bus.publish(admin_room(cid), {"type": "sentinel"})
    got = []
    while True:
        event = ws.receive_json()
        if event["type"] == "sentinel":
            return got
        got.append(event)


def ready(ws):
    assert ws.receive_json() == {"type": "ready"}


def ask(client, token, email="new@x.kr", name="박민수", student_no="20249999"):
    return client.post(
        f"/api/join/{token}/request-access", json={"email": email, "name": name, "student_no": student_no}, headers=ORIGIN
    )


def enroll(prof, cid, no="1", name="김철수", email="kim@x.kr"):
    assert prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN).status_code == 201


def request_code(world, client, token, email="kim@x.kr"):
    assert client.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"
    mailer = world.app.state.mailer
    before = len(mailer.sent)
    world.app.state.mail_worker.process_due()
    assert len(mailer.sent) == before + 1
    return re.search(r"\b(\d{6})\b", mailer.sent[-1].text).group(1)


# --- 연결 (C8) ----------------------------------------------------------------------------------------------------


def test_the_owner_connects_and_is_told_it_is_ready(world):
    prof, cid, _ = classroom(world)
    with connect(prof, cid) as ws:
        ready(ws)


@pytest.mark.parametrize("who", ["anonymous", "other_professor"])
def test_nobody_else_can_connect(world, who):
    _prof, cid, _ = classroom(world)
    client = world.client() if who == "anonymous" else world.client("lee")
    with pytest.raises(WebSocketDenialResponse) as err, connect(client, cid):
        pass
    assert err.value.status_code in (401, 403)


def test_a_missing_classroom_is_refused(world):
    prof, _, _ = classroom(world)
    with pytest.raises(WebSocketDenialResponse) as err, connect(prof, 999):
        pass
    assert err.value.status_code == 404


def test_a_student_with_the_invite_link_cannot_connect(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    request_code(world, student, token)
    with pytest.raises(WebSocketDenialResponse), connect(student, cid):
        pass


@pytest.mark.parametrize("origin", [None, "https://evil.example", "http://localhost:9999"])
def test_a_page_from_another_origin_cannot_use_the_professors_cookie(world, origin):
    prof, cid, _ = classroom(world)
    headers = {} if origin is None else {"origin": origin}
    # 연결을 받기 전에 닫는다(실제 서버에서는 HTTP 403, 테스트 클라이언트에서는 1008 닫힘으로 보인다)
    with pytest.raises(WebSocketDisconnect) as err, connect(prof, cid, headers):
        pass
    assert err.value.code == 1008


def test_the_route_is_judged_by_authz_not_by_hand(world, monkeypatch):
    from app import authz

    prof, cid, _ = classroom(world)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    with connect(prof, cid) as ws:
        ready(ws)
    assert calls == [authz.Action.CLASSROOM_MANAGE]


@pytest.mark.constitution
def test_c8_the_websocket_route_is_in_the_authz_check(world):
    from app.authz import registered_routes, routes_without_authz

    assert ("WEBSOCKET", "/ws/admin/{classroom_id}") in registered_routes(world.app)
    assert ("WEBSOCKET", "/ws/admin/{classroom_id}") not in routes_without_authz(world.app)


# --- 이벤트 (AC40, AC45) --------------------------------------------------------------------------------------------


def test_a_new_join_request_is_announced_by_number_only(world):
    prof, cid, token = classroom(world)
    with connect(prof, cid) as ws:
        ready(ws)
        ask(world.client(), token, "new@x.kr", "박민수", "20249999")
        (event,) = drain(world, ws, cid)
    request_id = prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"][0]["id"]
    assert event == {"type": "join_request.created", "id": request_id}
    assert all(secret not in str(event) for secret in ("new@x.kr", "박민수", "20249999"))


def test_a_duplicate_request_announces_nothing(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token)
    with connect(prof, cid) as ws:
        ready(ws)
        ask(world.client(), token)  # 같은 이메일: 합쳐졌다
        assert drain(world, ws, cid) == []


def test_approving_announces_the_decision_and_the_roster_change(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token)
    req = prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"][0]["id"]
    with connect(prof, cid) as ws:
        ready(ws)
        prof.post(f"/api/classrooms/{cid}/join-requests/{req}/approve", headers=ORIGIN)
        assert drain(world, ws, cid) == [
            {"type": "join_request.updated", "id": req, "status": "approved"},
            {"type": "roster.updated"},
        ]


def test_rejecting_announces_only_the_decision(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token)
    req = prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"][0]["id"]
    with connect(prof, cid) as ws:
        ready(ws)
        prof.post(f"/api/classrooms/{cid}/join-requests/{req}/reject", headers=ORIGIN)
        assert drain(world, ws, cid) == [{"type": "join_request.updated", "id": req, "status": "rejected"}]


def test_a_failed_decision_announces_nothing(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid, no="20249999", name="먼저", email="first@x.kr")
    ask(world.client(), token, "new@x.kr", "박민수", "20249999")  # 같은 학번이라 승인이 거절된다
    req = prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"][0]["id"]
    with connect(prof, cid) as ws:
        ready(ws)
        assert prof.post(f"/api/classrooms/{cid}/join-requests/{req}/approve", headers=ORIGIN).status_code == 409
        assert prof.post(f"/api/classrooms/{cid}/join-requests/99999/reject", headers=ORIGIN).status_code == 404
        assert drain(world, ws, cid) == []


def test_adding_a_student_and_importing_a_csv_announce_a_roster_change(world):
    prof, cid, _ = classroom(world)
    with connect(prof, cid) as ws:
        ready(ws)
        enroll(prof, cid)
        prof.post(
            f"/api/classrooms/{cid}/roster/import",
            content="학번,이름,이메일\n2,이영희,lee@x.kr\n".encode(),
            headers={**ORIGIN, "Content-Type": "text/csv"},
        )
        assert drain(world, ws, cid) == [{"type": "roster.updated"}, {"type": "roster.updated"}]


def test_a_csv_that_adds_nobody_announces_nothing(world):
    prof, cid, _ = classroom(world)
    with connect(prof, cid) as ws:
        ready(ws)
        res = prof.post(
            f"/api/classrooms/{cid}/roster/import",
            content="학번,이름,이메일\n1,김,not-an-email\n".encode(),
            headers={**ORIGIN, "Content-Type": "text/csv"},
        )
        assert res.json()["added"] == 0
        assert drain(world, ws, cid) == []


def test_a_roster_change_that_failed_announces_nothing(world):
    prof, cid, _ = classroom(world)
    enroll(prof, cid)
    with connect(prof, cid) as ws:
        ready(ws)
        dup = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": "1", "name": "김", "email": "kim@x.kr"}, headers=ORIGIN)
        assert dup.status_code == 422
        bad_csv = prof.post(
            f"/api/classrooms/{cid}/roster/import", content=b"\xff\xfe", headers={**ORIGIN, "Content-Type": "text/csv"}
        )
        assert bad_csv.status_code == 422
        assert drain(world, ws, cid) == []


def test_notifying_the_professor_announces_a_pending_auth_once(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    request_code(world, student, token)
    with connect(prof, cid) as ws:
        ready(ws)
        student.post(f"/api/join/{token}/notify-professor", json={"email": "kim@x.kr"}, headers=ORIGIN)
        student.post(f"/api/join/{token}/notify-professor", json={"email": "kim@x.kr"}, headers=ORIGIN)  # 반복
        events = drain(world, ws, cid)
    pending_id = prof.get(f"/api/classrooms/{cid}/pending-auth").json()["items"][0]["id"]
    assert events == [{"type": "pending_auth.created", "id": pending_id}]  # 반복해도 한 번만 알린다
    assert not re.search(r"\d{6}", str(events))  # 코드는 싣지 않는다


def test_a_failed_notify_announces_nothing(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    with connect(prof, cid) as ws:
        ready(ws)
        stranger = world.client()
        stranger.get(f"/api/join/{token}")
        assert stranger.post(f"/api/join/{token}/notify-professor", json={"email": "kim@x.kr"}, headers=ORIGIN).status_code == 422
        assert drain(world, ws, cid) == []


def test_using_a_notified_code_announces_an_update(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    student.post(f"/api/join/{token}/notify-professor", json={"email": "kim@x.kr"}, headers=ORIGIN)
    pending_id = prof.get(f"/api/classrooms/{cid}/pending-auth").json()["items"][0]["id"]
    with connect(prof, cid) as ws:
        ready(ws)
        student.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": code}, headers=ORIGIN)
        assert drain(world, ws, cid) == [{"type": "pending_auth.updated", "id": pending_id}]


def test_a_code_that_was_not_notified_announces_nothing_when_used(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    with connect(prof, cid) as ws:
        ready(ws)
        student.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": code}, headers=ORIGIN)
        assert drain(world, ws, cid) == []  # 알리지 않은 인증은 교수 목록에 없으니 알릴 것도 없다


def test_a_wrong_code_announces_nothing(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    student.post(f"/api/join/{token}/notify-professor", json={"email": "kim@x.kr"}, headers=ORIGIN)
    with connect(prof, cid) as ws:
        ready(ws)
        wrong = "000000" if code != "000000" else "111111"
        student.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": wrong}, headers=ORIGIN)
        assert drain(world, ws, cid) == []


def test_getting_a_new_code_after_notifying_announces_that_the_old_one_is_gone(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    request_code(world, student, token)
    student.post(f"/api/join/{token}/notify-professor", json={"email": "kim@x.kr"}, headers=ORIGIN)
    pending_id = prof.get(f"/api/classrooms/{cid}/pending-auth").json()["items"][0]["id"]
    world.clock.advance(minutes=1)
    with connect(prof, cid) as ws:
        ready(ws)
        student.post(f"/api/join/{token}/resend", json={"email": "kim@x.kr"}, headers=ORIGIN)
        assert drain(world, ws, cid) == [{"type": "pending_auth.updated", "id": pending_id}]


def test_a_new_code_when_nothing_was_notified_announces_nothing(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    with connect(prof, cid) as ws:
        ready(ws)
        request_code(world, student, token)
        assert drain(world, ws, cid) == []


# --- 사실은 DB에 있다 (C13) ---------------------------------------------------------------------------------------------


def test_the_change_is_already_saved_when_it_is_announced(world, monkeypatch):
    prof, cid, token = classroom(world)
    ask(world.client(), token)
    req = prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"][0]["id"]
    seen = []
    bus = world.app.state.bus
    real = bus.publish

    def spy(room, event):
        # 발행하는 순간 새 연결로 읽어도 이미 저장되어 있어야 한다
        status = world.db().execute("SELECT status FROM join_requests WHERE id = ?", (req,)).fetchone()["status"]
        seen.append((event["type"], status))
        real(room, event)

    monkeypatch.setattr(bus, "publish", spy)
    prof.post(f"/api/classrooms/{cid}/join-requests/{req}/approve", headers=ORIGIN)
    assert seen[0] == ("join_request.updated", "approved")


def test_events_only_go_to_the_classroom_they_belong_to(world):
    prof, a, _token_a = classroom(world, "웹")
    lee, b, token_b = classroom(world, "DB", owner="lee")
    with connect(prof, a) as ws_a, connect(lee, b) as ws_b:
        ready(ws_a)
        ready(ws_b)
        ask(world.client(), token_b)
        assert drain(world, ws_a, a) == []
        assert [e["type"] for e in drain(world, ws_b, b)] == ["join_request.created"]


def test_two_screens_of_the_same_classroom_both_get_the_event(world):
    prof, cid, token = classroom(world)
    with connect(prof, cid) as one, connect(prof, cid) as two:
        ready(one)
        ready(two)
        ask(world.client(), token)
        assert len(drain(world, one, cid)) == 1 and len(drain(world, two, cid)) == 1


def test_after_reconnecting_the_lists_are_read_again_over_http(world):
    prof, cid, token = classroom(world)
    with connect(prof, cid) as ws:
        ready(ws)
    ask(world.client(), token)  # 연결이 끊긴 사이에 생긴 요청
    with connect(prof, cid) as ws:
        ready(ws)  # 이어 붙을 때마다 ready를 받고, 그 뒤에 목록을 받으면 놓친 것이 없다
        assert len(prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"]) == 1


def test_events_that_happen_between_ready_and_the_list_are_not_lost(world):
    prof, cid, token = classroom(world)
    with connect(prof, cid) as ws:
        ready(ws)
        ask(world.client(), token)  # ready 직후, 화면이 목록을 받기 전에 생긴 일
        listed = prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"]
        assert len(listed) == 1
        assert [e["type"] for e in drain(world, ws, cid)] == ["join_request.created"]  # 이벤트도 남아 있다(다시 불러올 뿐)


def test_a_slow_screen_is_told_to_reload_everything(world):
    prof, cid, _token = classroom(world)
    with connect(prof, cid) as ws:
        ready(ws)
        bus = world.app.state.bus
        for i in range(bus.max_queue + 20):
            bus.publish(admin_room(cid), {"type": "roster.updated", "n": i})
        events = []
        while True:
            events.append(ws.receive_json())
            if events[-1]["type"] == "resync":
                break
        assert events[-1] == {"type": "resync"}


def test_closing_the_screen_removes_its_subscription(world):
    prof, cid, _ = classroom(world)
    bus = world.app.state.bus
    with connect(prof, cid) as ws:
        ready(ws)
        assert bus.subscriber_count(admin_room(cid)) == 1
    for _ in range(100):  # 서버가 끊김을 알아채는 데 잠깐 걸린다
        if bus.subscriber_count(admin_room(cid)) == 0:
            break
        import time

        time.sleep(0.02)
    assert bus.subscriber_count(admin_room(cid)) == 0


def test_a_failing_bus_does_not_turn_a_saved_change_into_an_error(world, monkeypatch):
    prof, cid, token = classroom(world)

    def boom(*_a, **_k):
        raise RuntimeError("버스 고장")

    monkeypatch.setattr(world.app.state.bus, "publish", boom)
    res = ask(world.client(), token)
    assert res.status_code == 201  # 저장은 끝났으니 요청은 성공이다
    assert len(prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"]) == 1
