"""003 T007: 교수·프로젝터용 출석코드 받기(AC3, AC26, C13).

화면은 지금 코드와 다음 코드, 각 칸이 끝나는 시각, 서버 시각을 받아 자기 시계를 서버에 맞춰 경계에서 바꾼다.
코드는 저장하지 않고 창의 난수와 칸 번호로 계산한다(T003). 학생에게는 주지 않는다.
"""

import json
from datetime import timedelta

from attendance_world import act, entered_student, make_classroom, make_session
from conftest import ORIGIN
from test_attendance_controls import control, started
from test_attendance_open import iso, windows
from test_session_lifecycle import bus

from app.attendance_core import compute_attendance_code, slot_bounds, slot_of

NOT_OPEN = "지금은 출석을 받고 있지 않습니다."
NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."


def get_code(client, cid, sid):
    return client.get(f"/api/classrooms/{cid}/sessions/{sid}/attendance/code")


def expected(world, sid, slot):
    w = windows(world, sid)[-1]
    return compute_attendance_code(world.settings.server_secret, w["id"], w["nonce"], slot)


def test_gives_current_and_next_codes_with_their_end_times(world):
    prof, cid, sid = started(world)
    world.clock.advance(seconds=7)
    now = world.clock.now()
    res = get_code(prof, cid, sid)
    assert res.status_code == 200, res.text
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    slot = slot_of(now)
    _, current_end = slot_bounds(slot)
    _, next_end = slot_bounds(slot + 1)
    assert body == {
        "current": {"code": expected(world, sid, slot), "ends_at": iso(current_end)},
        "next": {"code": expected(world, sid, slot + 1), "ends_at": iso(next_end)},
        "closes_at": windows(world, sid)[0]["closes_at"],
        "server_now": iso(now),
    }


def test_codes_change_at_the_slot_boundary_and_stay_within_it(world):
    prof, cid, sid = started(world)
    # 같은 칸 안에서는 같은 코드
    start, end = slot_bounds(slot_of(world.clock.now()))
    world.clock.set(start)
    a = get_code(prof, cid, sid).json()
    world.clock.set(end - timedelta(microseconds=1))
    assert get_code(prof, cid, sid).json()["current"] == a["current"]
    world.clock.set(end)
    b = get_code(prof, cid, sid).json()
    assert b["current"] == a["next"]  # 경계에서 다음 코드가 지금 코드가 된다


def test_same_moment_gives_the_same_code_to_every_screen(world):
    # AC3: 교수 화면, 프로젝터, 같은 교수가 연 다른 화면이 같은 순간에 같은 코드
    prof, cid, sid = started(world)
    projector = world.client("kim")
    assert get_code(prof, cid, sid).json() == get_code(projector, cid, sid).json()


def test_reopen_gives_new_codes(world):
    prof, cid, sid = started(world)
    old = get_code(prof, cid, sid).json()
    control(prof, cid, sid, "close")
    control(prof, cid, sid, "reopen")
    new = get_code(prof, cid, sid).json()
    assert new["current"]["ends_at"] == old["current"]["ends_at"]
    assert new["current"]["code"] != old["current"]["code"]  # 같은 칸이지만 새 창(새 난수)


def test_extend_shows_in_closes_at(world):
    prof, cid, sid = started(world)
    before = get_code(prof, cid, sid).json()["closes_at"]
    control(prof, cid, sid, "extend")
    after = get_code(prof, cid, sid).json()["closes_at"]
    assert after > before


def test_not_open_is_409(world):
    prof, cid = make_classroom(world)
    scheduled = make_session(prof, cid)
    res = get_code(prof, cid, scheduled)
    assert (res.status_code, res.json()["detail"]) == (409, NOT_OPEN)
    sid = make_session(prof, cid, "2회차")
    act(prof, cid, sid, "start")
    control(prof, cid, sid, "close")
    assert get_code(prof, cid, sid).status_code == 409
    control(prof, cid, sid, "reopen")
    world.clock.advance(minutes=10)  # 시간이 지나 닫혔다
    res = get_code(prof, cid, sid)
    assert (res.status_code, res.json()["detail"]) == (409, NOT_OPEN)
    assert res.headers["cache-control"] == "no-store"


def test_unknown_or_other_classrooms_session_is_not_found(world):
    prof, cid, _ = started(world)
    _, other_cid = make_classroom(world, name="다른 강좌")
    other = make_session(prof, other_cid)
    act(prof, other_cid, other, "start")
    assert get_code(prof, cid, 9999).status_code == 404
    assert get_code(prof, cid, other).status_code == 404


def test_students_and_other_professors_get_no_code(world):
    prof, cid, sid = started(world)
    student = entered_student(world, prof, cid, "s1@x.kr")
    for client in (student, world.client("lee")):
        res = get_code(client, cid, sid)
        assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
        assert "current" not in res.json()
    assert get_code(world.client(), cid, sid).status_code == 401


def test_nonce_never_leaves_the_server_outside_this_endpoint(world):
    # 수업 상태, attendance.updated 발행, 기록 어디에도 창의 난수가 없다(코드를 계산할 수 없다)
    prof, cid, sid = started(world)
    student = entered_student(world, prof, cid, "s1@x.kr")
    recording = bus(world)
    control(prof, cid, sid, "extend")
    control(prof, cid, sid, "close")
    control(prof, cid, sid, "reopen")
    nonces = [w["nonce"] for w in windows(world, sid)]
    published = json.dumps([e for _, e, _ in recording.published])
    with world.db() as db:
        payloads = " ".join(r[0] for r in db.execute("SELECT payload FROM events WHERE classroom_id = ?", (cid,)))
    for nonce in nonces:
        assert nonce not in published and nonce not in payloads
    nonce = nonces[-1]
    for client in (student, prof):
        res = client.get(f"/api/class/{cid}/sessions/{sid}/live")
        assert nonce not in res.text
        assert '"code"' not in res.text and '"nonce"' not in res.text
    # (6자리 숫자는 시각 문자열에 우연히 들어 있을 수 있어 값으로는 찾지 않는다)


def test_ended_session_gives_no_code(world):
    prof, cid, sid = started(world)
    act(prof, cid, sid, "end")
    assert get_code(prof, cid, sid).status_code == 409


def test_archived_classroom_owner_gets_not_open_rather_than_forbidden(world):
    # attendance.manage는 보관된 강좌도 허용한다. 보관된 강좌에는 열린 출석이 없으므로 409다
    prof, cid, sid = started(world)
    act(prof, cid, sid, "end")
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    res = get_code(prof, cid, sid)
    assert (res.status_code, res.json()["detail"]) == (409, NOT_OPEN)


def test_post_is_not_allowed(world):
    prof, cid, sid = started(world)
    res = prof.post(f"/api/classrooms/{cid}/sessions/{sid}/attendance/code", headers=ORIGIN)
    assert res.status_code == 405
