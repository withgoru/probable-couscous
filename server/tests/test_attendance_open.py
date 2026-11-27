"""003 T005: 수업 시작에 출석 열기, 이어서 하기·종료와의 관계, `live`의 출석 상태(AC2, AC5, AC7, C13).

시작·종료는 002의 `session.updated`만 발행한다(화면은 이것을 받으면 `live`를 통째로 다시 받고, 거기에 출석 창이
들어 있다). 연장·마감·다시 받기의 `attendance.updated`는 T006이 만든다.
"""

import json
from datetime import timedelta

from attendance_world import act, entered_student, live, make_classroom, make_session
from conftest import ORIGIN
from fastapi.testclient import TestClient
from test_session_lifecycle import bus

from app import events
from app.db import connect


def windows(world, session_id):
    with world.db() as db:
        return [
            dict(r)
            for r in db.execute(
                "SELECT id, nonce, opened_at, closes_at, closed_at, opened_by FROM attendance_windows "
                "WHERE session_id = ? ORDER BY id",
                (session_id,),
            )
        ]


def attendance_events(world, cid):
    with world.db() as db:
        rows = db.execute(
            "SELECT type, actor_kind, actor_ref, payload FROM events WHERE classroom_id = ? AND type LIKE 'attendance_%' "
            "AND type <> 'attendance_minutes_changed' ORDER BY id",
            (cid,),
        )
        return [(r["type"], r["actor_kind"], r["actor_ref"], json.loads(r["payload"])) for r in rows]


def iso(dt):
    return dt.isoformat()


# --- 시작 -------------------------------------------------------------------------------


def test_starting_a_class_opens_attendance_for_the_classroom_minutes(world):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    start = world.clock.now()
    assert act(prof, cid, sid, "start").status_code == 200
    [w] = windows(world, sid)
    assert w["opened_at"] == iso(start)
    assert w["closes_at"] == iso(start + timedelta(minutes=10))
    assert w["closed_at"] is None
    assert w["opened_by"] == "start"
    assert len(w["nonce"]) == 32
    assert attendance_events(world, cid) == [
        ("attendance_opened", "professor", 101, {"session_id": sid, "window_id": w["id"], "minutes": 10}),
    ]


def test_changed_minutes_apply_from_the_next_start(world):
    prof, cid = make_classroom(world)
    first, second = make_session(prof, cid, "1회차"), make_session(prof, cid, "2회차")
    act(prof, cid, first, "start")
    prof.put(f"/api/classrooms/{cid}/attendance-settings", json={"minutes": 15}, headers=ORIGIN)
    [w1] = windows(world, first)
    assert w1["closes_at"] == iso(world.clock.now() + timedelta(minutes=10))  # 이미 연 출석은 그대로
    act(prof, cid, first, "end")
    world.clock.advance(minutes=1)
    act(prof, cid, second, "start")
    [w2] = windows(world, second)
    assert w2["closes_at"] == iso(world.clock.now() + timedelta(minutes=15))


def test_pressing_start_twice_opens_one_window(world):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "start")
    assert len(windows(world, sid)) == 1


def test_each_window_gets_its_own_nonce(world):
    prof, cid = make_classroom(world)
    a, b = make_session(prof, cid, "1회차"), make_session(prof, cid, "2회차")
    act(prof, cid, a, "start")
    act(prof, cid, a, "end")
    act(prof, cid, b, "start")
    assert windows(world, a)[0]["nonce"] != windows(world, b)[0]["nonce"]


def test_start_failure_while_recording_opens_nothing(world, monkeypatch):
    # 시작과 출석 열기는 한 트랜잭션이다: 기록이 실패하면 수업도 출석도 열리지 않는다(C13)
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    real = events.record_event

    def boom(db, classroom_id, type_, *args, **kwargs):
        if type_ == "attendance_opened":
            raise RuntimeError("디스크 오류")
        return real(db, classroom_id, type_, *args, **kwargs)

    monkeypatch.setattr(events, "record_event", boom)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    assert act(safe, cid, sid, "start").status_code == 500
    assert windows(world, sid) == []
    with connect(world.settings.database_path) as db:
        assert db.execute("SELECT status FROM class_sessions WHERE id = ?", (sid,)).fetchone()[0] == "scheduled"


# --- 종료와 이어서 하기 ---------------------------------------------------------------------


def test_ending_the_class_closes_open_attendance(world):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    world.clock.advance(minutes=3)
    act(prof, cid, sid, "end")
    [w] = windows(world, sid)
    assert w["closed_at"] == iso(world.clock.now())
    assert [e[0] for e in attendance_events(world, cid)] == ["attendance_opened", "attendance_closed"]
    assert attendance_events(world, cid)[1][3] == {"session_id": sid, "window_id": w["id"], "by": "session_end"}


def test_ending_after_attendance_already_timed_out_keeps_the_timeout_as_the_close(world):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    [w] = windows(world, sid)
    world.clock.advance(minutes=30)
    act(prof, cid, sid, "end")
    [w] = windows(world, sid)
    assert w["closed_at"] == w["closes_at"]  # 시간이 지나 닫힌 시각 그대로
    assert [e[0] for e in attendance_events(world, cid)] == ["attendance_opened"]  # 열려 있지 않았으니 마감 기록 없음


def test_resuming_does_not_reopen_attendance(world):
    # AC7: 이어서 하기로 다시 열어도 출석은 저절로 열리지 않는다
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    world.clock.advance(minutes=1)
    assert act(prof, cid, sid, "resume").status_code == 200
    assert len(windows(world, sid)) == 1
    assert live(prof, cid, sid)["attendance"]["window"]["open"] is False


def test_start_and_end_publish_only_session_updated(world):
    # 화면은 session.updated를 받으면 live를 다시 받는다. 출석 창은 그 안에 있다(002 발행 순서 그대로)
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    recording = bus(world)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    assert [(e["type"], e["version"]) for _, e, _ in recording.published] == [
        ("session.updated", 1),
        ("session.updated", 2),
    ]


# --- live의 출석 상태 -----------------------------------------------------------------------


def test_professor_live_state_has_the_window_and_counts(world):
    prof, cid = make_classroom(world)
    entered_student(world, prof, cid, "s1@x.kr")
    entered_student(world, prof, cid, "s2@x.kr")
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    now = world.clock.now()
    world.clock.advance(seconds=20)
    att = live(prof, cid, sid)["attendance"]
    assert att == {
        "window": {"open": True, "opened_at": iso(now), "closes_at": iso(now + timedelta(minutes=10)), "closed_at": None},
        "present": 0,
        "roster": 2,
        "pending": 0,
        "server_now": iso(world.clock.now()),
    }


def test_window_reads_as_closed_once_its_time_passes(world):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    world.clock.advance(minutes=10)  # 마감 시각과 같으면 닫혔다
    w = live(prof, cid, sid)["attendance"]["window"]
    assert w["open"] is False
    assert w["closed_at"] == w["closes_at"]


def test_scheduled_session_has_no_window(world):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    att = live(prof, cid, sid)["attendance"]
    assert att["window"] is None
    assert (att["present"], att["roster"], att["pending"]) == (0, 0, 0)


def test_roster_count_skips_removed_students(world):
    prof, cid = make_classroom(world)
    entered_student(world, prof, cid, "s1@x.kr")
    entered_student(world, prof, cid, "s2@x.kr")
    entry = prof.get(f"/api/classrooms/{cid}/roster").json()["entries"][0]["id"]
    assert prof.delete(f"/api/classrooms/{cid}/roster/{entry}", headers=ORIGIN).status_code == 200
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    assert live(prof, cid, sid)["attendance"]["roster"] == 1


def test_student_live_state_has_only_their_own_attendance(world):
    # AC27: 학생은 다른 학생의 출석을 볼 수 없다(수도 없다)
    prof, cid = make_classroom(world)
    student = entered_student(world, prof, cid, "s1@x.kr")
    entered_student(world, prof, cid, "s2@x.kr")
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    att = live(student, cid, sid)["attendance"]
    assert set(att) == {"window", "status", "request", "server_now"}
    assert att["window"]["open"] is True
    assert (att["status"], att["request"]) == ("absent", "none")


# --- 기록이 있을 때의 수와 학생 상태(기록을 만드는 라우트는 T008~T010. 여기서는 DB에 직접 넣는다) -----------------


def roster_ids(prof, cid):
    return {e["email"]: e["id"] for e in prof.get(f"/api/classrooms/{cid}/roster").json()["entries"]}


def membership_of(world, cid, roster_entry_id):
    with world.db() as db:
        return db.execute(
            "SELECT membership_id FROM member_identities WHERE classroom_id = ? AND roster_entry_id = ?",
            (cid, roster_entry_id),
        ).fetchone()[0]


def mark(world, cid, sid, entry, kind, request_id=None):
    with world.db() as db:
        if kind == "code":
            m = membership_of(world, cid, entry)
            db.execute(
                "INSERT INTO attendance_marks(classroom_id, session_id, roster_entry_id, membership_id, kind, "
                "actor_kind, actor_ref, client_key, created_at) VALUES (?, ?, ?, ?, 'code', 'student', ?, 'k', ?)",
                (cid, sid, entry, m, m, NOW_TEXT),
            )
        else:
            db.execute(
                "INSERT INTO attendance_marks(classroom_id, session_id, roster_entry_id, kind, actor_kind, actor_ref, "
                "request_id, created_at) VALUES (?, ?, ?, ?, 'professor', 101, ?, ?)",
                (cid, sid, entry, kind, request_id, NOW_TEXT),
            )


def request(world, cid, sid, entry, decision=None):
    with world.db() as db:
        rid = db.execute(
            "INSERT INTO attendance_requests(classroom_id, session_id, roster_entry_id, membership_id, reason, "
            "created_at) VALUES (?, ?, ?, ?, '배터리가 없었습니다', ?)",
            (cid, sid, entry, membership_of(world, cid, entry), NOW_TEXT),
        ).lastrowid
        if decision:
            db.execute(
                "INSERT INTO attendance_decisions(request_id, classroom_id, decision, github_id, decided_at) "
                "VALUES (?, ?, ?, 101, ?)",
                (rid, cid, decision, NOW_TEXT),
            )
    return rid


NOW_TEXT = "2026-03-01T09:00:00+00:00"


def class_with(world, n):
    prof, cid = make_classroom(world)
    students = [entered_student(world, prof, cid, f"s{i}@x.kr") for i in range(1, n + 1)]
    ids = roster_ids(prof, cid)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    return prof, cid, sid, students, [ids[f"s{i}@x.kr"] for i in range(1, n + 1)]


def test_counts_and_statuses_follow_the_last_record(world):
    prof, cid, sid, (s1, s2), (e1, e2) = class_with(world, 2)
    mark(world, cid, sid, e1, "code")
    mark(world, cid, sid, e1, "manual_absent")  # 교수가 결석으로 바꿨다
    mark(world, cid, sid, e2, "manual_present")
    assert live(prof, cid, sid)["attendance"]["present"] == 1
    assert live(s1, cid, sid)["attendance"]["status"] == "absent"
    assert live(s2, cid, sid)["attendance"]["status"] == "manual"
    mark(world, cid, sid, e1, "manual_present")
    assert live(prof, cid, sid)["attendance"]["present"] == 2
    assert live(s1, cid, sid)["attendance"]["status"] == "manual"


def test_a_student_sees_only_their_own_record(world):
    # AC27: 다른 학생의 출석이 내 화면에 섞이지 않는다
    _, cid, sid, (s1, s2), (_, e2) = class_with(world, 2)
    mark(world, cid, sid, e2, "code")
    assert live(s1, cid, sid)["attendance"]["status"] == "absent"
    assert live(s2, cid, sid)["attendance"]["status"] == "present"


def test_pending_requests_and_each_students_request_state(world):
    prof, cid, sid, (s1, s2, _s3, s4), (e1, e2, e3, _) = class_with(world, 4)
    request(world, cid, sid, e1)
    request(world, cid, sid, e2, "rejected")
    request(world, cid, sid, e3)
    assert prof.delete(f"/api/classrooms/{cid}/roster/{e3}", headers=ORIGIN).status_code == 200
    att = live(prof, cid, sid)["attendance"]
    assert (att["pending"], att["roster"]) == (1, 3)  # 처리한 요청과 명단에서 빠진 학생의 요청은 세지 않는다
    assert live(s1, cid, sid)["attendance"]["request"] == "pending"
    assert live(s2, cid, sid)["attendance"]["request"] == "rejected"
    assert live(s4, cid, sid)["attendance"]["request"] == "none"
    r = request(world, cid, sid, roster_ids(prof, cid)["s4@x.kr"], "approved")
    mark(world, cid, sid, roster_ids(prof, cid)["s4@x.kr"], "request_approved", r)
    att = live(s4, cid, sid)["attendance"]
    assert (att["request"], att["status"]) == ("approved", "manual")


def test_live_reports_the_latest_window(world):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    act(prof, cid, sid, "start")
    world.clock.advance(minutes=20)
    later = world.clock.now()
    with world.db() as db:  # 다시 받기(T006)를 흉내 낸다: 이전 창을 닫고 새 창
        db.execute("UPDATE attendance_windows SET closed_at = closes_at WHERE session_id = ?", (sid,))
        db.execute(
            "INSERT INTO attendance_windows(classroom_id, session_id, nonce, opened_at, closes_at, opened_by) "
            "VALUES (?, ?, ?, ?, ?, 'reopen')",
            (cid, sid, "f" * 32, iso(later), iso(later + timedelta(minutes=10))),
        )
    w = live(prof, cid, sid)["attendance"]["window"]
    assert (w["open"], w["opened_at"]) == (True, iso(later))


def test_ending_one_session_leaves_other_sessions_windows_alone(world):
    prof, cid = make_classroom(world)
    a, b = make_session(prof, cid, "1회차"), make_session(prof, cid, "2회차")
    act(prof, cid, a, "start")
    act(prof, cid, a, "end")
    with world.db() as db:  # 예전 데이터처럼 닫지 않은 창이 남아 있다고 하자
        db.execute(
            "INSERT INTO attendance_windows(classroom_id, session_id, nonce, opened_at, closes_at, opened_by) "
            "SELECT classroom_id, session_id, ?, opened_at, closes_at, 'reopen' FROM attendance_windows WHERE session_id = ?",
            ("e" * 32, a),
        )
    act(prof, cid, b, "start")
    act(prof, cid, b, "end")
    assert windows(world, a)[1]["closed_at"] is None  # 다른 회차의 창은 건드리지 않는다
