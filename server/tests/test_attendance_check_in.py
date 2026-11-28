"""003 T008: 학생 코드 출석 서버(AC6, AC12, AC13, AC14, AC16, AC27, 오류 표의 '학생 연결이 끊김').

- 받는 코드는 받은 순간의 칸과 바로 앞 칸(T003). 틀리면 422, 1분 안에 5번째 틀림부터 429와 남은 초.
- 같은 `client_key`로 다시 보내면 처음과 같은 200이고 기록은 하나다. 다른 기기로 다시 넣으면 `already: true`.
- 출석하면 교수 화면에 `attendance.tally`, 그 학생의 화면에만 `attendance.mine`이 간다(DB 기록 뒤).
"""

import pytest
from attendance_world import (
    act,
    enroll,
    entered_student,
    invite_token,
    live,
    make_classroom,
    make_session,
)
from conftest import ORIGIN
from test_attendance_controls import control
from test_attendance_open import mark, roster_ids, windows
from test_class_ws import connect, hang_guard  # noqa: F401  (hang_guard는 autouse 고정)
from test_session_lifecycle import bus

from app.attendance_core import compute_attendance_code, slot_of
from app.realtime import class_room

WRONG = "코드가 맞지 않습니다. 교실 화면의 숫자를 다시 확인해 주세요."
CLOSED = "출석 시간이 끝났습니다. 교수님께 수기 출석을 요청하세요."
NOT_MEMBER = "이 강좌에 입장한 학생만 출석할 수 있습니다. 강좌 링크를 다시 열어 입장해 주세요."
BAD_KEY = "요청이 올바르지 않습니다. 화면을 새로 고친 뒤 다시 눌러 주세요."


def code_at(world, sid, when, back=0):
    w = windows(world, sid)[-1]
    return compute_attendance_code(world.settings.server_secret, w["id"], w["nonce"], slot_of(when) - back)


def wrong_code(world, sid):
    right = {code_at(world, sid, world.clock.now()), code_at(world, sid, world.clock.now(), 1)}
    return next(c for c in ("000000", "111111", "222222") if c not in right)


def check_in(client, cid, sid, code, key="k1"):
    return client.post(
        f"/api/class/{cid}/sessions/{sid}/attendance", json={"code": code, "client_key": key}, headers=ORIGIN
    )


def class_of(world, n=1):
    prof, cid = make_classroom(world)
    students = [entered_student(world, prof, cid, f"s{i}@x.kr") for i in range(1, n + 1)]
    sid = make_session(prof, cid)
    assert act(prof, cid, sid, "start").status_code == 200
    return prof, cid, sid, students


def marks(world, sid):
    with world.db() as db:
        return [dict(r) for r in db.execute(
            "SELECT roster_entry_id, membership_id, kind, actor_kind, actor_ref, client_key FROM attendance_marks "
            "WHERE session_id = ? ORDER BY id", (sid,)
        )]


# --- 맞는 코드 -----------------------------------------------------------------------------


def test_current_code_marks_the_student_present(world):
    prof, cid = make_classroom(world)
    enroll(prof, cid, "first@x.kr", no="first")  # 명단 항목 번호와 멤버십 번호가 같지 않게 한 명을 먼저 넣는다
    s1 = entered_student(world, prof, cid, "s1@x.kr")
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "present", "already": False}
    [m] = marks(world, sid)
    assert (m["kind"], m["actor_kind"], m["client_key"]) == ("code", "student", "k1")
    assert m["roster_entry_id"] == roster_ids(prof, cid)["s1@x.kr"]
    assert m["actor_ref"] == m["membership_id"] != m["roster_entry_id"]
    assert live(s1, cid, sid)["attendance"]["status"] == "present"
    assert live(prof, cid, sid)["attendance"]["present"] == 1


def test_previous_code_is_accepted_after_the_boundary(world):
    # 입력하는 사이에 코드가 바뀌어도 된다(AC12)
    _, cid, sid, (s1,) = class_of(world)
    shown = code_at(world, sid, world.clock.now())
    world.clock.advance(seconds=15)
    assert check_in(s1, cid, sid, shown).status_code == 200


def test_code_two_slots_old_is_wrong(world):
    _, cid, sid, (s1,) = class_of(world)
    shown = code_at(world, sid, world.clock.now())
    world.clock.advance(seconds=30)
    if shown in {code_at(world, sid, world.clock.now()), code_at(world, sid, world.clock.now(), 1)}:
        pytest.skip("우연히 같은 코드(100만분의 1)")
    res = check_in(s1, cid, sid, shown)
    assert (res.status_code, res.json()["detail"]) == (422, WRONG)


# --- 틀린 코드와 잠금 ---------------------------------------------------------------------------


def test_wrong_code_is_422_and_records_nothing(world):
    _, cid, sid, (s1,) = class_of(world)
    res = check_in(s1, cid, sid, wrong_code(world, sid))
    assert (res.status_code, res.json()["detail"]) == (422, WRONG)
    assert marks(world, sid) == []


@pytest.mark.parametrize("bad", ["12345", "1234567", "abcdef", "", None, 123456])
def test_malformed_code_counts_as_wrong(world, bad):
    _, cid, sid, (s1,) = class_of(world)
    res = check_in(s1, cid, sid, bad)
    assert (res.status_code, res.json()["detail"]) == (422, WRONG)


def test_fifth_wrong_code_in_a_minute_locks_with_remaining_seconds(world):
    _, cid, sid, (s1, s2) = class_of(world, 2)
    bad = wrong_code(world, sid)
    for _ in range(4):
        assert check_in(s1, cid, sid, bad).status_code == 422
        world.clock.advance(seconds=1)
    res = check_in(s1, cid, sid, bad)  # 4초 시점 5번째: 첫 틀림 + 60초까지
    assert res.status_code == 429
    assert res.json() == {"detail": "잠시 뒤에 다시 입력해 주세요. (56초)", "retry_after": 56}
    assert res.headers["Retry-After"] == "56"
    world.clock.advance(seconds=10)
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))  # 잠긴 동안은 맞는 코드도 보지 않는다
    assert res.json() == {"detail": "잠시 뒤에 다시 입력해 주세요. (46초)", "retry_after": 46}
    assert marks(world, sid) == []
    assert check_in(s2, cid, sid, code_at(world, sid, world.clock.now())).status_code == 200  # 다른 학생은 따로
    world.clock.advance(seconds=46)
    assert check_in(s1, cid, sid, code_at(world, sid, world.clock.now())).status_code == 200


# --- 마감 ---------------------------------------------------------------------------------------


def test_after_close_time_check_in_is_refused(world):
    _, cid, sid, (s1,) = class_of(world)
    world.clock.advance(minutes=10)
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert (res.status_code, res.json()["detail"]) == (409, CLOSED)


def test_after_professor_closes_check_in_is_refused(world):
    prof, cid, sid, (s1,) = class_of(world)
    code = code_at(world, sid, world.clock.now())
    control(prof, cid, sid, "close")
    res = check_in(s1, cid, sid, code)
    assert (res.status_code, res.json()["detail"]) == (409, CLOSED)


def test_ended_or_scheduled_session_is_refused(world):
    prof, cid, sid, (s1,) = class_of(world)
    code = code_at(world, sid, world.clock.now())
    act(prof, cid, sid, "end")
    assert check_in(s1, cid, sid, code).json()["detail"] == CLOSED
    scheduled = make_session(prof, cid, "예정")
    res = check_in(s1, cid, scheduled, "123456")
    assert (res.status_code, res.json()["detail"]) == (409, CLOSED)


def test_reopened_window_takes_the_new_code_only(world):
    prof, cid, sid, (s1,) = class_of(world)
    old = code_at(world, sid, world.clock.now())
    control(prof, cid, sid, "close")
    control(prof, cid, sid, "reopen")
    new = code_at(world, sid, world.clock.now())
    if old != new:
        assert check_in(s1, cid, sid, old).status_code == 422
    assert check_in(s1, cid, sid, new, key="k2").status_code == 200


# --- 한 번만 -------------------------------------------------------------------------------


def test_resending_the_same_press_gives_the_same_answer_once(world):
    # 오류 표: 한 번 누른 출석은 두 번 기록되지 않는다. 그사이 마감돼도 처음 답을 준다
    prof, cid, sid, (s1,) = class_of(world)
    code = code_at(world, sid, world.clock.now())
    first = check_in(s1, cid, sid, code, key="press-1")
    control(prof, cid, sid, "close")
    again = check_in(s1, cid, sid, code, key="press-1")
    assert again.status_code == 200
    assert again.json() == first.json() == {"status": "present", "already": False}
    assert len(marks(world, sid)) == 1


def test_second_device_gets_already_attended(world):
    # AC16: 다른 기기(같은 학생, 다른 화면 난수)로 다시 넣어도 상태는 그대로, "이미 출석했습니다."
    _, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()), key="phone")
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()), key="laptop")
    assert res.json() == {"status": "present", "already": True}
    assert len(marks(world, sid)) == 1


def test_already_present_student_gets_already_even_with_a_wrong_code_or_after_close(world):
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert check_in(s1, cid, sid, wrong_code(world, sid), key="k2").json() == {"status": "present", "already": True}
    control(prof, cid, sid, "close")
    assert check_in(s1, cid, sid, "000000", key="k3").json()["already"] is True


def test_manually_present_student_gets_already(world):
    prof, cid, sid, (s1,) = class_of(world)
    mark(world, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "manual_present")
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert res.json() == {"status": "manual", "already": True}
    assert [m["kind"] for m in marks(world, sid)] == ["manual_present"]


def test_student_the_professor_marked_absent_can_attend_by_code(world):
    # 교수가 결석으로 둔 학생(코드 출석 전)은 열려 있는 동안 코드로 출석할 수 있다
    prof, cid, sid, (s1,) = class_of(world)
    mark(world, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "manual_absent")
    assert check_in(s1, cid, sid, code_at(world, sid, world.clock.now())).json() == {
        "status": "present", "already": False,
    }


def test_code_attendance_overridden_to_absent_is_not_reattended(world):
    # 교수가 코드 출석을 결석으로 바꿨으면(AC21) 다시 넣어도 바뀌지 않는다. 회차마다 코드 출석은 한 번이다
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()), key="a")
    mark(world, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "manual_absent")
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()), key="b")
    assert res.json() == {"status": "absent", "already": True}
    assert live(s1, cid, sid)["attendance"]["status"] == "absent"


# --- 누가 --------------------------------------------------------------------------------------


def test_client_key_up_to_64_chars_is_accepted(world):
    _, cid, sid, (s1,) = class_of(world)
    assert check_in(s1, cid, sid, code_at(world, sid, world.clock.now()), key="k" * 64).status_code == 200


@pytest.mark.parametrize("key", [None, "", 7, "k" * 65])
def test_client_key_is_required(world, key):
    _, cid, sid, (s1,) = class_of(world)
    res = s1.post(
        f"/api/class/{cid}/sessions/{sid}/attendance",
        json={"code": code_at(world, sid, world.clock.now()), "client_key": key},
        headers=ORIGIN,
    )
    assert (res.status_code, res.json()["detail"]) == (422, BAD_KEY)
    assert marks(world, sid) == []


def test_professors_and_strangers_cannot_check_in(world):
    prof, cid, sid, _ = class_of(world)
    code = code_at(world, sid, world.clock.now())
    for client in (prof, world.client("lee")):
        assert check_in(client, cid, sid, code).status_code == 403
    assert check_in(world.client(), cid, sid, code).status_code == 401
    _, other_cid = make_classroom(world, name="다른 강좌")
    outsider = entered_student(world, prof, other_cid, "x@x.kr")
    res = check_in(outsider, cid, sid, code)
    assert (res.status_code, res.json()["detail"]) == (403, NOT_MEMBER)
    assert marks(world, sid) == []


def test_removed_or_signed_out_student_cannot_check_in(world):
    # AC27: 명단에서 빠졌거나 로그인이 끊긴 학생(001)은 출석할 수 없다
    prof, cid, sid, (s1, s2) = class_of(world, 2)
    ids = roster_ids(prof, cid)
    assert prof.delete(f"/api/classrooms/{cid}/roster/{ids['s1@x.kr']}", headers=ORIGIN).status_code == 200
    assert prof.post(f"/api/classrooms/{cid}/roster/{ids['s2@x.kr']}/revoke-login", headers=ORIGIN).status_code == 200
    code = code_at(world, sid, world.clock.now())
    for s in (s1, s2):
        res = check_in(s, cid, sid, code)
        assert res.status_code in (401, 403)
    assert marks(world, sid) == []


def test_half_entered_student_cannot_check_in(world):
    prof, cid, sid, _ = class_of(world)
    enroll(prof, cid, "late@x.kr", no="late")
    half = world.client()
    half.post(f"/api/join/{invite_token(prof, cid)}/email", json={"email": "late@x.kr"}, headers=ORIGIN)
    assert check_in(half, cid, sid, code_at(world, sid, world.clock.now())).status_code == 401


def test_other_classrooms_session_is_not_found(world):
    prof, cid, _, (s1,) = class_of(world)
    _, other_cid = make_classroom(world, name="다른 강좌")
    other = make_session(prof, other_cid)
    act(prof, other_cid, other, "start")
    assert check_in(s1, cid, other, "123456").status_code == 404
    assert check_in(s1, cid, 9999, "123456").status_code == 404


def test_request_from_another_site_is_refused(world):
    _, cid, sid, (s1,) = class_of(world)
    res = s1.post(
        f"/api/class/{cid}/sessions/{sid}/attendance",
        json={"code": code_at(world, sid, world.clock.now()), "client_key": "k"},
        headers={"Origin": "https://evil.example"},
    )
    assert res.status_code == 403
    assert marks(world, sid) == []


# --- 알림 ----------------------------------------------------------------------------------


def test_tally_and_mine_are_published_after_the_record(world):
    _, cid, sid, (s1,) = class_of(world)
    recording = bus(world)
    check_in(s1, cid, sid, wrong_code(world, sid))  # 틀린 코드는 알리지 않는다
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))  # 같은 누름의 재전송도 알리지 않는다
    membership = marks(world, sid)[0]["membership_id"]
    assert [e for _, e, _ in recording.published] == [
        {"type": "attendance.tally", "session_id": sid, "present": 1, "roster": 1, "pending": 0, "to": "professor"},
        {"type": "attendance.mine", "session_id": sid, "status": "present", "request": "none",
         "membership_id": membership, "to": "member"},
    ]
    assert all(status == "live" for _, _, status in recording.published)


def drain_all(world, cid, sockets):
    """여러 연결을 함께 비운다. 끝 표시 하나를 발행하고 연결마다 그 앞까지 읽는다(drain을 연결마다 부르면
    한 연결의 끝 표시가 다른 연결에 남는다)."""
    world.app.state.bus.publish(class_room(cid), {"type": "sentinel"})
    got = []
    for ws in sockets:
        mine = []
        while (message := ws.receive_json())["type"] != "sentinel":
            mine.append(message)
        got.append([m for m in mine if m["type"].startswith("attendance")])
    return got


def test_tally_goes_to_professor_screens_and_mine_only_to_that_student(world):
    prof, cid, sid, (s1, s2) = class_of(world, 2)
    with connect(prof, cid) as pws, connect(prof, cid, role="projector") as jws, \
            connect(s1, cid) as ws1, connect(s2, cid) as ws2:
        sockets = (pws, jws, ws1, ws2)
        drain_all(world, cid, sockets)
        assert check_in(s1, cid, sid, code_at(world, sid, world.clock.now())).status_code == 200
        prof_got, projector_got, s1_got, s2_got = drain_all(world, cid, sockets)
        assert prof_got == [{"type": "attendance.tally", "session_id": sid, "present": 1, "roster": 2, "pending": 0}]
        assert projector_got == []  # 프로젝터에는 출석 수를 띄우지 않는다
        assert s1_got == [{"type": "attendance.mine", "session_id": sid, "status": "present", "request": "none"}]
        assert s2_got == []  # 다른 학생은 누가 출석했는지 모른다(AC27)


def test_a_burst_of_check_ins_is_all_recorded(world):
    # 오류 표 '많은 학생이 한꺼번에 출석'의 기능 확인(시간 측정은 T028). 몇 명으로 줄여 같은 경로를 본다
    prof, cid, sid, students = class_of(world, 6)  # 메일 발송이 초당 8통이라 그 아래로
    code = code_at(world, sid, world.clock.now())
    assert all(check_in(s, cid, sid, code).status_code == 200 for s in students)
    assert len(marks(world, sid)) == 6
    assert live(prof, cid, sid)["attendance"]["present"] == 6


def test_wrong_codes_after_a_minute_do_not_stay_locked(world):
    _, cid, sid, (s1,) = class_of(world)
    bad = wrong_code(world, sid)
    for _ in range(5):
        check_in(s1, cid, sid, bad)
    world.clock.advance(seconds=61)
    assert check_in(s1, cid, sid, code_at(world, sid, world.clock.now())).status_code == 200


def test_student_removed_after_the_permission_check_is_not_recorded(world, monkeypatch):
    # 권한 판단과 쓰기 사이에 명단에서 빠진 경우: 쓰기 잠금 안에서 지금 명단 항목을 다시 찾는다
    from app import identity

    _, cid, sid, (s1,) = class_of(world)
    monkeypatch.setattr(identity, "roster_entry_of", lambda *_a: None)
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert (res.status_code, res.json()["detail"]) == (403, NOT_MEMBER)
    assert marks(world, sid) == []


def test_mark_on_a_removed_roster_entry_is_not_made(world):
    # 빠진 명단 항목에 이어진 멤버십은 출석 대상이 아니다(다시 넣으면 다시 입장할 때 새 항목에 이어진다)
    prof, cid, sid, (s1,) = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    with world.db() as db:
        db.execute("UPDATE roster_entries SET removed_at = ? WHERE id = ?", ("2026-03-01T09:00:00+00:00", entry))
    res = check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert res.status_code == 403
    assert marks(world, sid) == []


class CommitCheckingBus:
    """발행하는 순간 다른 연결로 읽어, 출석 기록이 이미 커밋됐는지 적는다(C13)."""

    def __init__(self, database_path):
        self.database_path = database_path
        self.seen = []

    def publish(self, room, event):
        from app.db import connect as db_connect

        with db_connect(self.database_path) as db:
            n = db.execute("SELECT COUNT(*) FROM attendance_marks WHERE session_id = ?", (event["session_id"],))
            self.seen.append((event["type"], n.fetchone()[0]))

    def subscribe(self, room):  # pragma: no cover
        raise NotImplementedError


def test_notices_go_out_after_the_mark_is_committed(world):
    _, cid, sid, (s1,) = class_of(world)
    checking = CommitCheckingBus(world.settings.database_path)
    world.app.state.bus = checking
    assert check_in(s1, cid, sid, code_at(world, sid, world.clock.now())).status_code == 200
    assert checking.seen == [("attendance.tally", 1), ("attendance.mine", 1)]
