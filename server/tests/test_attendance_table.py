"""003 T010: 출석 현황과 직접 바꾸기 서버(AC21, AC22, AC23, AC25, AC26, C5, C6, C7, C8).

- 현황(`GET …/sessions/{s}/attendance`): 지금 명단 학생마다 학번·이름·상태·시각·`source`, "출석 N / M",
  이 회차의 대기 요청. 한 번도 시작하지 않은 회차는 `{started: false}`(AC23).
- 직접 바꾸기(`PUT …/attendance/{roster_entry_id} {status}`): 결석 → 출석은 수기(`manual_present`),
  출석 → 결석은 `manual_absent`. 끝난 회차도 되고 시작하지 않은 회차는 409. 바꾼 뒤 `tally`·`mine`을 알린다.
"""

import pytest
from attendance_world import act, enroll, entered_student, live, make_classroom, make_session
from conftest import ORIGIN
from test_attendance_check_in import (
    CommitCheckingBus,
    check_in,
    class_of,
    code_at,
    drain_all,
    marks,
)
from test_attendance_open import roster_ids
from test_attendance_requests import ask, decide, requests
from test_class_ws import connect, hang_guard  # noqa: F401  (hang_guard는 autouse 고정)

NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."
NOT_STARTED = "아직 수업하지 않은 회차입니다."
BAD_STATUS = "상태는 출석 또는 결석으로 골라 주세요."
NOT_ON_ROSTER = "명단에 없는 학생입니다. 명단을 새로 고친 뒤 다시 시도해 주세요."


def table(client, cid, sid):
    return client.get(f"/api/classrooms/{cid}/sessions/{sid}/attendance")


def change(client, cid, sid, entry, status):
    return client.put(
        f"/api/classrooms/{cid}/sessions/{sid}/attendance/{entry}", json={"status": status}, headers=ORIGIN
    )


def rows_by_no(body):
    return {r["student_no"]: r for r in body["students"]}


def event_count(world):
    with world.db() as db:
        return db.execute("SELECT COUNT(*) FROM events").fetchone()[0]


# --- 출석 현황 --------------------------------------------------------------------------------


def test_never_started_session_has_no_table(world):
    # AC23: 한 번도 시작하지 않은 회차는 표가 없다
    prof, cid = make_classroom(world)
    enroll(prof, cid, "s1@x.kr", no="s1")
    sid = make_session(prof, cid)
    res = table(prof, cid, sid)
    assert res.status_code == 200, res.text
    assert res.json() == {"started": False}


def test_table_shows_every_current_student_with_status_time_and_source(world):
    # AC22: 학번, 이름, 상태(출석/출석 (수기)/결석), 출석 시각. source는 코드 출석을 결석으로 바꿀 때의 확인용(AC21)
    prof, cid = make_classroom(world)
    s1 = entered_student(world, prof, cid, "s1@x.kr", name="김일")
    s2 = entered_student(world, prof, cid, "s2@x.kr", name="이이")
    entered_student(world, prof, cid, "s3@x.kr", name="박삼")
    enroll(prof, cid, "s4@x.kr", no="s4", name="최사")  # 입장하지 않은 학생도 명단에 있으면 보인다
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    checked_at = world.clock.now()
    check_in(s1, cid, sid, code_at(world, sid, checked_at))
    world.clock.advance(seconds=30)
    rid = ask(s2, cid, sid).json()["id"]
    world.clock.advance(seconds=30)
    approved_at = world.clock.now()
    decide(prof, cid, rid, "approve")

    res = table(prof, cid, sid)
    assert res.status_code == 200, res.text
    body = res.json()
    ids = roster_ids(prof, cid)
    assert body["started"] is True
    assert body["students"] == [
        {"roster_entry_id": ids["s1@x.kr"], "student_no": "s1", "name": "김일", "status": "present",
         "at": checked_at.isoformat(), "source": "code"},
        {"roster_entry_id": ids["s2@x.kr"], "student_no": "s2", "name": "이이", "status": "manual",
         "at": approved_at.isoformat(), "source": "request"},
        {"roster_entry_id": ids["s3@x.kr"], "student_no": "s3", "name": "박삼", "status": "absent",
         "at": None, "source": None},
        {"roster_entry_id": ids["s4@x.kr"], "student_no": "s4", "name": "최사", "status": "absent",
         "at": None, "source": None},
    ]
    assert (body["present"], body["roster"], body["pending"]) == (2, 4, 0)


def test_table_lists_pending_requests_of_absent_students(world):
    # AC20: 대기 중인 요청(학번·이름·사유·시각). 처리한 요청, 그 뒤 출석한 학생의 요청, 빠진 학생의 요청은 없다
    prof, cid, sid, (s1, s2, s3, s4) = class_of(world, 4)
    asked_at = world.clock.now()
    r1 = ask(s1, cid, sid, "  배터리가 없었습니다 ").json()["id"]
    r2 = ask(s2, cid, sid).json()["id"]
    ask(s3, cid, sid)
    ask(s4, cid, sid)
    decide(prof, cid, r2, "reject")
    check_in(s3, cid, sid, code_at(world, sid, world.clock.now()))
    prof.delete(f"/api/classrooms/{cid}/roster/{roster_ids(prof, cid)['s4@x.kr']}", headers=ORIGIN)

    body = table(prof, cid, sid).json()
    assert body["requests"] == [
        {"id": r1, "roster_entry_id": roster_ids(prof, cid)["s1@x.kr"], "student_no": "s1", "name": "김철수",
         "reason": "배터리가 없었습니다", "created_at": asked_at.isoformat()},
    ]
    assert body["pending"] == 1


def test_table_reads_one_moment(world, monkeypatch):
    # 명단·기록·요청을 한 시점에서 읽는다. 읽는 도중 다른 연결이 쓴 처리는 이번 응답에 섞이지 않는다
    from app import attendance_state
    from app.db import connect as db_connect

    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    original = attendance_state.latest_marks

    def decided_meanwhile(*args):
        got = original(*args)
        with db_connect(world.settings.database_path) as other:
            other.execute(
                "INSERT INTO attendance_decisions(request_id, classroom_id, decision, github_id, decided_at) "
                "VALUES (?, ?, 'rejected', 101, '2026-03-01T09:00:00+00:00')", (rid, cid),
            )
        return got

    monkeypatch.setattr(attendance_state, "latest_marks", decided_meanwhile)
    body = table(prof, cid, sid).json()
    assert ([q["id"] for q in body["requests"]], body["pending"]) == ([rid], 1)


def test_request_shows_again_when_the_student_is_marked_absent(world):
    # 요청 뒤 코드로 출석해 빠진 요청은, 교수가 결석으로 바꾸면 다시 대기 요청이 된다(아직 처리하지 않았고 결석이다)
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert table(prof, cid, sid).json()["requests"] == []
    change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "absent")
    body = table(prof, cid, sid).json()
    assert ([q["id"] for q in body["requests"]], body["pending"]) == ([rid], 1)


def test_each_session_has_its_own_status(world):
    # 다른 회차의 기록은 이 회차의 상태·수·바꾸기 판단에 섞이지 않는다
    prof, cid, first, (s1,) = class_of(world)
    check_in(s1, cid, first, code_at(world, first, world.clock.now()))
    act(prof, cid, first, "end")
    second = make_session(prof, cid, "2회차")
    act(prof, cid, second, "start")
    entry = roster_ids(prof, cid)["s1@x.kr"]
    body = table(prof, cid, second).json()
    assert (rows_by_no(body)["s1"]["status"], body["present"]) == ("absent", 0)
    assert change(prof, cid, second, entry, "absent").json()["status"] == "absent"
    assert marks(world, second) == []
    assert change(prof, cid, second, entry, "present").json()["status"] == "manual"
    assert [m["kind"] for m in marks(world, second)] == ["manual_present"]
    row = rows_by_no(table(prof, cid, first).json())["s1"]
    assert (row["status"], row["source"]) == ("present", "code")


def test_direct_change_hides_a_pending_request(world):
    # 교수가 직접 출석으로 바꾸면 대기 요청은 목록에서 빠진다(처리 기록은 남기지 않는다, T009 노트 6번)
    prof, cid, sid, (s1,) = class_of(world)
    ask(s1, cid, sid)
    change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "present")
    body = table(prof, cid, sid).json()
    assert (body["requests"], body["pending"]) == ([], 0)
    assert requests(world, sid)[0]["decision"] is None


def test_student_added_later_is_absent_in_earlier_sessions(world):
    # AC25: 학기 중에 명단에 들어온 학생은 그 전 회차가 결석이다
    prof, cid, first, (s1,) = class_of(world)
    check_in(s1, cid, first, code_at(world, first, world.clock.now()))
    act(prof, cid, first, "end")
    enroll(prof, cid, "late@x.kr", no="late", name="늦게")
    body = table(prof, cid, first).json()
    assert rows_by_no(body)["late"]["status"] == "absent"
    assert (body["present"], body["roster"]) == (1, 2)


def test_removed_student_is_hidden_but_records_stay(world):
    # AC25: 명단에서 빠진 학생의 기록은 지워지지 않지만 보이지 않는다
    prof, cid, sid, (s1, _s2) = class_of(world, 2)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    gone = roster_ids(prof, cid)["s1@x.kr"]
    prof.delete(f"/api/classrooms/{cid}/roster/{gone}", headers=ORIGIN)
    body = table(prof, cid, sid).json()
    assert [r["student_no"] for r in body["students"]] == ["s2"]
    assert (body["present"], body["roster"]) == (0, 1)
    assert [m["roster_entry_id"] for m in marks(world, sid)] == [gone]


def test_table_works_after_class_and_in_an_archived_classroom(world):
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    act(prof, cid, sid, "end")
    assert table(prof, cid, sid).json()["present"] == 1
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    assert table(prof, cid, sid).json()["present"] == 1


def test_table_has_no_email(world):
    # C7: 출석 현황에 이메일이 없다
    prof, cid, sid, (s1,) = class_of(world)
    ask(s1, cid, sid)
    text = table(prof, cid, sid).text
    assert "@x.kr" not in text and "email" not in text


def test_only_the_owner_sees_the_table(world):
    # AC26
    _, cid, sid, (s1,) = class_of(world)
    for client in (s1, world.client("lee")):
        res = table(client, cid, sid)
        assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert table(world.client(), cid, sid).status_code == 401


def test_session_of_another_classroom_is_not_found(world):
    prof, cid, _sid, _ = class_of(world)
    _, _other_cid, other_sid, _ = class_of(world)
    assert table(prof, cid, other_sid).status_code == 404


def test_table_rows_follow_the_roster_order(world):
    prof, cid = make_classroom(world)
    for no in ("30", "4", "200"):
        enroll(prof, cid, f"{no}@x.kr", no=no)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    assert [r["student_no"] for r in table(prof, cid, sid).json()["students"]] == ["30", "4", "200"]


# --- 직접 바꾸기 ------------------------------------------------------------------------------


def test_absent_to_present_is_manual(world):
    # AC21: 결석에서 출석으로 바꾸면 "출석 (수기)"
    prof, cid, sid, _ = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    world.clock.advance(seconds=5)
    res = change(prof, cid, sid, entry, "present")
    assert res.status_code == 200, res.text
    assert res.json() == {
        "roster_entry_id": entry, "status": "manual", "at": world.clock.now().isoformat(), "source": "manual",
    }
    [m] = marks(world, sid)
    assert (m["roster_entry_id"], m["kind"], m["actor_kind"], m["actor_ref"], m["membership_id"]) == (
        entry, "manual_present", "professor", 101, None,
    )


def test_code_attendance_can_be_changed_to_absent(world):
    # AC21: 코드로 출석한 학생도 결석으로 바꿀 수 있다(확인 대화상자는 화면 몫, 서버는 source를 준다)
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    entry = roster_ids(prof, cid)["s1@x.kr"]
    assert rows_by_no(table(prof, cid, sid).json())["s1"]["source"] == "code"
    res = change(prof, cid, sid, entry, "absent")
    assert res.json() == {"roster_entry_id": entry, "status": "absent", "at": None, "source": "manual"}
    assert [m["kind"] for m in marks(world, sid)] == ["code", "manual_absent"]
    row = rows_by_no(table(prof, cid, sid).json())["s1"]
    assert (row["status"], row["at"], row["source"]) == ("absent", None, "manual")


def test_changing_back_and_forth_keeps_every_record(world):
    # C6: 상태는 마지막 기록에서 계산하고, 바꿀 때마다 기록이 남는다
    prof, cid, sid, _ = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    for status in ("present", "absent", "present"):
        change(prof, cid, sid, entry, status)
    assert [m["kind"] for m in marks(world, sid)] == ["manual_present", "manual_absent", "manual_present"]
    assert rows_by_no(table(prof, cid, sid).json())["s1"]["status"] == "manual"


@pytest.mark.parametrize(("before", "to", "expected"), [
    ("absent", "absent", "absent"), ("code", "present", "present"), ("manual", "present", "manual"),
])
def test_change_to_the_same_status_adds_no_record(world, before, to, expected):
    # 같은 상태로 바꾸면 기록을 더하지 않는다. 코드 출석을 "출석"으로 눌러도 "출석 (수기)"로 내려가지 않는다
    prof, cid, sid, (s1,) = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    if before == "code":
        check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    elif before == "manual":
        change(prof, cid, sid, entry, "present")
    kinds = [m["kind"] for m in marks(world, sid)]
    res = change(prof, cid, sid, entry, to)
    assert (res.status_code, res.json()["status"]) == (200, expected)
    assert [m["kind"] for m in marks(world, sid)] == kinds


def test_change_works_after_class_and_in_an_archived_classroom(world):
    # AC21: 끝난 회차도 바꾼다
    prof, cid, sid, _ = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    act(prof, cid, sid, "end")
    assert change(prof, cid, sid, entry, "present").status_code == 200
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    assert change(prof, cid, sid, entry, "absent").json()["status"] == "absent"


def test_change_in_a_never_started_session_is_refused(world):
    prof, cid = make_classroom(world)
    entry = enroll(prof, cid, "s1@x.kr", no="s1")
    sid = make_session(prof, cid)
    res = change(prof, cid, sid, entry, "present")
    assert (res.status_code, res.json()["detail"]) == (409, NOT_STARTED)
    # 회차를 먼저 본다: 시작하지 않은 회차면 명단에 없는 학생이어도 같은 409다
    assert change(prof, cid, sid, 999_999, "present").json()["detail"] == NOT_STARTED
    assert marks(world, sid) == []


def test_missing_status_is_refused(world):
    prof, cid, sid, _ = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    res = prof.put(f"/api/classrooms/{cid}/sessions/{sid}/attendance/{entry}", json={}, headers=ORIGIN)
    assert (res.status_code, res.json()["detail"]) == (422, BAD_STATUS)


@pytest.mark.parametrize("bad", ["manual", "PRESENT", "", None, 1, True, ["present"]])
def test_bad_status_is_refused(world, bad):
    prof, cid, sid, _ = class_of(world)
    res = change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], bad)
    assert (res.status_code, res.json()["detail"]) == (422, BAD_STATUS)
    assert marks(world, sid) == []


def test_roster_entry_of_another_classroom_or_removed_is_not_found(world):
    prof, cid, sid, _ = class_of(world)
    other_prof, other_cid, _, _ = class_of(world)
    foreign = roster_ids(other_prof, other_cid)["s1@x.kr"]
    res = change(prof, cid, sid, foreign, "present")
    assert (res.status_code, res.json()["detail"]) == (404, NOT_ON_ROSTER)
    gone = roster_ids(prof, cid)["s1@x.kr"]
    prof.delete(f"/api/classrooms/{cid}/roster/{gone}", headers=ORIGIN)
    assert change(prof, cid, sid, gone, "present").status_code == 404
    assert change(prof, cid, sid, 999_999, "present").status_code == 404
    assert marks(world, sid) == []


def test_session_of_another_classroom_cannot_be_changed(world):
    prof, cid, _sid, _ = class_of(world)
    _, _other_cid, other_sid, _ = class_of(world)
    assert change(prof, cid, other_sid, roster_ids(prof, cid)["s1@x.kr"], "present").status_code == 404
    assert marks(world, other_sid) == []


def test_only_the_owner_changes(world):
    # AC26
    prof, cid, sid, (s1,) = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    for client in (s1, world.client("lee")):
        res = change(client, cid, sid, entry, "present")
        assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert change(world.client(), cid, sid, entry, "present").status_code == 401
    assert marks(world, sid) == []


def test_change_is_not_written_to_events(world):
    # plan: 학생에 대한 일은 events에 넣지 않는다(정리 때 지워야 한다)
    prof, cid, sid, _ = class_of(world)
    before = event_count(world)
    change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "present")
    assert event_count(world) == before


def test_change_tells_professor_screens_and_that_student(world):
    # 바꾼 뒤 교수 화면에 수, 그 학생에게만 자기 상태(AC19와 같은 알림)
    prof, cid, sid, (s1, s2) = class_of(world, 2)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    with connect(prof, cid) as pws, connect(prof, cid, role="projector") as jws, \
            connect(s1, cid) as ws1, connect(s2, cid) as ws2:
        sockets = (pws, jws, ws1, ws2)
        drain_all(world, cid, sockets)
        assert change(prof, cid, sid, entry, "present").status_code == 200
        prof_got, projector_got, s1_got, s2_got = drain_all(world, cid, sockets)
    assert prof_got == [{"type": "attendance.tally", "session_id": sid, "present": 1, "roster": 2, "pending": 0}]
    assert projector_got == []
    assert s1_got == [{"type": "attendance.mine", "session_id": sid, "status": "manual", "request": "none"}]
    assert s2_got == []


def test_change_of_a_student_who_never_entered_tells_only_professors(world):
    prof, cid = make_classroom(world)
    entry = enroll(prof, cid, "s1@x.kr", no="s1")
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    checking = CommitCheckingBus(world.settings.database_path)
    world.app.state.bus = checking
    change(prof, cid, sid, entry, "present")
    assert checking.seen == [("attendance.tally", 1)]


def test_change_notices_go_out_after_commit(world):
    prof, cid, sid, _ = class_of(world)
    checking = CommitCheckingBus(world.settings.database_path)
    world.app.state.bus = checking
    change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "present")
    assert checking.seen == [("attendance.tally", 1), ("attendance.mine", 1)]


def test_same_status_change_sends_no_notice(world):
    prof, cid, sid, (s1,) = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    checking = CommitCheckingBus(world.settings.database_path)
    world.app.state.bus = checking
    change(prof, cid, sid, entry, "absent")
    assert checking.seen == []
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    checking.seen.clear()
    change(prof, cid, sid, entry, "present")  # 코드 출석을 "출석"으로: 그대로라 알리지 않는다
    assert checking.seen == []


def test_code_student_marked_absent_is_told_absent(world):
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    with connect(s1, cid) as ws1:
        drain_all(world, cid, (ws1,))
        change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "absent")
        (got,) = drain_all(world, cid, (ws1,))
    assert got == [{"type": "attendance.mine", "session_id": sid, "status": "absent", "request": "none"}]


def test_student_sees_the_change_in_live(world):
    prof, cid, sid, (s1,) = class_of(world)
    change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "present")
    assert live(s1, cid, sid)["attendance"]["status"] == "manual"
    assert live(prof, cid, sid)["attendance"]["present"] == 1
