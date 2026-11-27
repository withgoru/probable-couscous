"""003 T006: 연장·마감·다시 받기 서버(AC4, AC5, AC26, C6, C13).

모두 진행 중인 회차에서만 된다. 바뀔 때마다 회차 `version`을 1 올리고, 기록과 함께 커밋한 뒤 `attendance.updated`를
발행한다. 시작·종료는 002의 `session.updated`로 알린다(T005).
"""

import json
from datetime import timedelta

import pytest
from attendance_world import act, entered_student, live, make_classroom, make_session
from conftest import ORIGIN
from fastapi.testclient import TestClient
from test_attendance_open import attendance_events, class_with, iso, mark, windows
from test_session_lifecycle import bus

from app import events
from app.attendance_core import compute_attendance_code, slot_of
from app.db import connect

NOT_LIVE = "진행 중인 수업에서만 출석을 받을 수 있습니다."
NOT_OPEN = "출석 시간이 이미 끝났습니다. 다시 받으려면 '출석 다시 받기'를 눌러 주세요."
ARCHIVED = "보관된 강좌는 수업을 시작할 수 없습니다."
ALREADY_OPEN = "이미 출석을 받고 있습니다. 마감한 뒤 다시 받아 주세요."
NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."


def control(client, cid, sid, what):
    return client.post(f"/api/classrooms/{cid}/sessions/{sid}/attendance/{what}", headers=ORIGIN)


def started(world, minutes=None):
    prof, cid = make_classroom(world)
    if minutes:
        prof.put(f"/api/classrooms/{cid}/attendance-settings", json={"minutes": minutes}, headers=ORIGIN)
    sid = make_session(prof, cid)
    assert act(prof, cid, sid, "start").status_code == 200
    return prof, cid, sid


def version(prof, cid, sid):
    return live(prof, cid, sid)["session"]["version"]


# --- 연장 -------------------------------------------------------------------------------


def test_extend_pushes_the_close_time_back_five_minutes(world):
    prof, cid, sid = started(world)
    [before] = windows(world, sid)
    v = version(prof, cid, sid)
    world.clock.advance(minutes=4)
    res = control(prof, cid, sid, "extend")
    assert res.status_code == 200, res.text
    expected = iso(world.clock.now() - timedelta(minutes=4) + timedelta(minutes=15))
    assert res.json()["window"]["closes_at"] == expected
    assert res.json()["version"] == v + 1
    [after] = windows(world, sid)
    assert (after["id"], after["nonce"], after["closes_at"]) == (before["id"], before["nonce"], expected)
    control(prof, cid, sid, "extend")  # 누를 때마다 5분
    assert windows(world, sid)[0]["closes_at"] == iso(world.clock.now() + timedelta(minutes=16))


def test_extend_needs_an_open_window(world):
    prof, cid, sid = started(world)
    world.clock.advance(minutes=10)  # 시간이 지나 닫혔다
    res = control(prof, cid, sid, "extend")
    assert (res.status_code, res.json()["detail"]) == (409, NOT_OPEN)
    control(prof, cid, sid, "reopen")
    control(prof, cid, sid, "close")
    res = control(prof, cid, sid, "extend")
    assert (res.status_code, res.json()["detail"]) == (409, NOT_OPEN)


# --- 마감 -------------------------------------------------------------------------------


def test_close_records_the_close_time(world):
    prof, cid, sid = started(world)
    world.clock.advance(minutes=2)
    res = control(prof, cid, sid, "close")
    assert res.status_code == 200, res.text
    [w] = windows(world, sid)
    assert w["closed_at"] == iso(world.clock.now())
    assert res.json()["window"]["open"] is False
    assert live(prof, cid, sid)["attendance"]["window"]["closed_at"] == iso(world.clock.now())


def test_close_needs_an_open_window(world):
    prof, cid, sid = started(world)
    control(prof, cid, sid, "close")
    res = control(prof, cid, sid, "close")  # 두 번 누름
    assert (res.status_code, res.json()["detail"]) == (409, NOT_OPEN)
    assert [e[0] for e in attendance_events(world, cid)].count("attendance_closed") == 1


# --- 다시 받기 ------------------------------------------------------------------------------


def test_reopen_opens_a_new_window_with_new_codes_for_the_classroom_minutes(world):
    prof, cid, sid = started(world)
    control(prof, cid, sid, "close")
    prof.put(f"/api/classrooms/{cid}/attendance-settings", json={"minutes": 5}, headers=ORIGIN)
    world.clock.advance(minutes=1)
    res = control(prof, cid, sid, "reopen")
    assert res.status_code == 200, res.text
    old, new = windows(world, sid)
    assert new["opened_by"] == "reopen"
    assert new["opened_at"] == iso(world.clock.now())
    assert new["closes_at"] == iso(world.clock.now() + timedelta(minutes=5))
    assert old["closed_at"] is not None
    slot = slot_of(world.clock.now())
    secret = world.settings.server_secret
    assert compute_attendance_code(secret, new["id"], new["nonce"], slot) != compute_attendance_code(
        secret, old["id"], old["nonce"], slot
    )
    assert res.json()["window"]["open"] is True


def test_reopen_after_timeout_closes_the_old_window_at_its_close_time(world):
    prof, cid, sid = started(world)
    world.clock.advance(minutes=30)
    assert control(prof, cid, sid, "reopen").status_code == 200
    old, new = windows(world, sid)
    assert old["closed_at"] == old["closes_at"]
    assert new["closed_at"] is None


def test_reopen_keeps_students_who_already_attended(world):
    prof, cid, sid, (s1, s2), (e1, _) = class_with(world, 2)
    mark(world, cid, sid, e1, "code")
    control(prof, cid, sid, "close")
    control(prof, cid, sid, "reopen")
    assert live(prof, cid, sid)["attendance"]["present"] == 1
    assert live(s1, cid, sid)["attendance"]["status"] == "present"
    assert live(s2, cid, sid)["attendance"]["status"] == "absent"


def test_reopen_while_open_is_refused(world):
    prof, cid, sid = started(world)
    res = control(prof, cid, sid, "reopen")
    assert (res.status_code, res.json()["detail"]) == (409, ALREADY_OPEN)
    assert len(windows(world, sid)) == 1


def test_resumed_class_can_reopen_attendance(world):
    # AC7: 이어서 하기 뒤에는 교수가 '출석 다시 받기'로 연다
    prof, cid, sid = started(world)
    act(prof, cid, sid, "end")
    act(prof, cid, sid, "resume")
    assert control(prof, cid, sid, "reopen").status_code == 200
    assert live(prof, cid, sid)["attendance"]["window"]["open"] is True


# --- 진행 중인 회차만 ---------------------------------------------------------------------------


@pytest.mark.parametrize("what", ["extend", "close", "reopen"])
def test_controls_need_a_live_session(world, what):
    prof, cid = make_classroom(world)
    scheduled = make_session(prof, cid, "예정")
    res = control(prof, cid, scheduled, what)
    assert (res.status_code, res.json()["detail"]) == (409, NOT_LIVE)
    ended = make_session(prof, cid, "종료")
    act(prof, cid, ended, "start")
    act(prof, cid, ended, "end")
    res = control(prof, cid, ended, what)
    assert (res.status_code, res.json()["detail"]) == (409, NOT_LIVE)


@pytest.mark.parametrize("what", ["extend", "close", "reopen"])
def test_unknown_or_other_classrooms_session_is_not_found(world, what):
    prof, cid, _ = started(world)
    _, other_cid = make_classroom(world, name="다른 강좌")
    assert control(prof, cid, 9999, what).status_code == 404
    other_sid = make_session(prof, other_cid)
    assert control(prof, cid, other_sid, what).status_code == 404


@pytest.mark.parametrize("what", ["extend", "close", "reopen"])
def test_archived_classroom_is_refused(world, what):
    prof, cid = make_classroom(world)
    sid = make_session(prof, cid)
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    res = control(prof, cid, sid, what)
    assert (res.status_code, res.json()["detail"]) == (409, ARCHIVED)  # session.present가 막는다
    assert windows(world, sid) == []


def test_archived_classroom_is_refused_even_if_a_session_is_somehow_live(world):
    # 수업 중에는 보관할 수 없지만(002 AC46), 권한 판단이 먼저 막는지 DB를 직접 바꿔 확인한다
    prof, cid, sid = started(world)
    with world.db() as db:
        db.execute("UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ?", (iso(world.clock.now()), cid))
    for what in ("extend", "close"):
        res = control(prof, cid, sid, what)
        assert (res.status_code, res.json()["detail"]) == (409, ARCHIVED)
    assert windows(world, sid)[0]["closed_at"] is None


@pytest.mark.parametrize("what", ["extend", "close", "reopen"])
def test_other_professor_and_students_are_refused(world, what):
    # AC26: 다른 교수나 학생에게는 "이 강좌에 대한 권한이 없습니다."
    prof, cid, sid = started(world)
    student = entered_student(world, prof, cid, "s1@x.kr")
    for client in (world.client("lee"), student):
        res = control(client, cid, sid, what)
        assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert len(windows(world, sid)) == 1


# --- 기록과 발행 -------------------------------------------------------------------------------


def test_each_control_is_recorded(world):
    prof, cid, sid = started(world)
    control(prof, cid, sid, "extend")
    control(prof, cid, sid, "close")
    control(prof, cid, sid, "reopen")
    first, second = windows(world, sid)
    assert attendance_events(world, cid) == [
        ("attendance_opened", "professor", 101, {"session_id": sid, "window_id": first["id"], "minutes": 10}),
        ("attendance_extended", "professor", 101,
         {"session_id": sid, "window_id": first["id"], "closes_at": windows(world, sid)[0]["closes_at"]}),
        ("attendance_closed", "professor", 101, {"session_id": sid, "window_id": first["id"], "by": "professor"}),
        ("attendance_opened", "professor", 101, {"session_id": sid, "window_id": second["id"], "minutes": 10}),
    ]


class CommitCheckingBus:
    """발행하는 순간 다른 연결로 DB를 읽어, 발행한 version과 창이 이미 커밋됐는지 적는다."""

    def __init__(self, database_path):
        self.database_path = database_path
        self.seen = []

    def publish(self, room, event):
        with connect(self.database_path) as db:
            (v,) = db.execute("SELECT version FROM class_sessions WHERE id = ?", (event["session_id"],)).fetchone()
            last = db.execute(
                "SELECT closes_at, closed_at FROM attendance_windows WHERE session_id = ? ORDER BY id DESC LIMIT 1",
                (event["session_id"],),
            ).fetchone()
        self.seen.append((event, v, dict(last)))

    def subscribe(self, room):  # pragma: no cover
        raise NotImplementedError


def test_published_version_and_window_are_already_committed(world):
    prof, cid, sid = started(world)
    checking = CommitCheckingBus(world.settings.database_path)
    world.app.state.bus = checking
    control(prof, cid, sid, "extend")
    world.clock.advance(minutes=1)
    control(prof, cid, sid, "close")
    for event, committed_version, window in checking.seen:
        assert event["version"] == committed_version
        assert event["window"]["closes_at"] == window["closes_at"]
    assert checking.seen[1][2]["closed_at"] == iso(world.clock.now())


def test_version_is_this_sessions_own(world):
    # 같은 강좌의 다른 회차 version과 섞이지 않는다
    prof, cid = make_classroom(world)
    busy, sid = make_session(prof, cid, "앞 회차"), make_session(prof, cid, "오늘")
    act(prof, cid, busy, "start")
    act(prof, cid, busy, "end")
    for _ in range(3):
        act(prof, cid, busy, "resume")
        act(prof, cid, busy, "end")
    assert version(prof, cid, busy) == 8
    act(prof, cid, sid, "start")
    v = version(prof, cid, sid)
    assert control(prof, cid, sid, "close").json()["version"] == v + 1


def test_response_carries_server_time(world):
    prof, cid, sid = started(world)
    world.clock.advance(seconds=30)
    assert control(prof, cid, sid, "extend").json()["server_now"] == iso(world.clock.now())


def test_each_control_publishes_attendance_updated_after_commit(world):
    prof, cid, sid = started(world)
    v = version(prof, cid, sid)
    recording = bus(world)
    control(prof, cid, sid, "extend")
    control(prof, cid, sid, "close")
    control(prof, cid, sid, "reopen")
    published = [e for _, e, _ in recording.published]
    assert [(e["type"], e["session_id"], e["version"]) for e in published] == [
        ("attendance.updated", sid, v + 1),
        ("attendance.updated", sid, v + 2),
        ("attendance.updated", sid, v + 3),
    ]
    assert [e["window"]["open"] for e in published] == [True, False, True]
    assert published[-1]["window"] == live(prof, cid, sid)["attendance"]["window"]
    assert all(status == "live" for _, _, status in recording.published)  # 발행 순간 DB에 이미 있다


def test_refused_control_changes_nothing_and_publishes_nothing(world):
    prof, cid, sid = started(world)
    v = version(prof, cid, sid)
    recording = bus(world)
    control(prof, cid, sid, "reopen")  # 열려 있어 거절
    assert recording.published == []
    assert version(prof, cid, sid) == v


def test_failure_while_recording_leaves_the_window_unchanged(world, monkeypatch):
    prof, cid, sid = started(world)
    [before] = windows(world, sid)
    v = version(prof, cid, sid)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(events, "record_event", boom)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    for what in ("extend", "close"):
        assert control(safe, cid, sid, what).status_code == 500
    assert windows(world, sid) == [before]
    monkeypatch.undo()
    assert version(prof, cid, sid) == v


def test_events_payloads_hold_no_personal_data(world):
    prof, cid, sid = started(world)
    control(prof, cid, sid, "extend")
    for _, _, _, payload in attendance_events(world, cid):
        assert not any(k in json.dumps(payload, ensure_ascii=False) for k in ("@", "email", "name", "student_no"))
