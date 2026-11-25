"""002 T007: 수업 시작·종료·이어서 하기(AC9, AC10, AC11, AC37, AC38, AC40 서버).

- 예정 회차를 시작하면 '진행 중'이 되고 위치는 1번 슬라이드·0단계다. 묶음이 없어도 시작된다(확인은 화면 몫).
- 강좌에서 진행 중인 회차는 하나다. 다른 회차가 진행 중이면 409와 그 회차 번호·이름 안내(AC10).
- 보관된 강좌에서는 시작·이어서 하기를 거절한다(AC11).
- 종료하면 '종료'. 이어서 하면 마지막 위치와 가장 멀리 간 위치가 그대로다(AC40).
- 상태가 바뀌면 DB에 기록한 **뒤** `class:{강좌}` 방에 `session.updated`를 발행한다(C13, AC38).
- 행동마다 기록을 남긴다(C6). 다른 강좌의 회차는 찾을 수 없다(C5).
"""

import json

from conftest import ORIGIN

from app.db import connect

NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."
NOT_FOUND = "찾을 수 없는 회차입니다."
ARCHIVED = "보관된 강좌는 수업을 시작할 수 없습니다."


class RecordingBus:
    """발행을 받아 적는 버스. 발행하는 순간 DB에 이미 기록됐는지(커밋됐는지)도 함께 적는다."""

    def __init__(self, database_path):
        self.database_path = database_path
        self.published: list[tuple[str, dict, str | None]] = []

    def publish(self, room, event):
        status = None
        if "session_id" in event:
            with connect(self.database_path) as db:
                row = db.execute("SELECT status FROM class_sessions WHERE id = ?", (event["session_id"],)).fetchone()
                status = row["status"] if row else None
        self.published.append((room, event, status))

    def subscribe(self, room):  # pragma: no cover - 이 테스트는 구독하지 않는다
        raise NotImplementedError


def bus(world):
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    return recording


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    return prof, cid


def create(prof, cid, title="3주차 1회차"):
    return prof.post(f"/api/classrooms/{cid}/sessions", json={"title": title}, headers=ORIGIN).json()["id"]


def act(prof, cid, sid, what, headers=ORIGIN):
    return prof.post(f"/api/classrooms/{cid}/sessions/{sid}/{what}", headers=headers)


def row(world, sid):
    with world.db() as db:
        return dict(db.execute("SELECT * FROM class_sessions WHERE id = ?", (sid,)).fetchone())


def move(world, sid, current, furthest):
    # 넘기기는 T009의 일이다. 여기서는 위치를 DB에 직접 둔다
    with world.db() as db:
        db.execute(
            "UPDATE class_sessions SET current_slide = ?, current_click = ?, furthest_slide = ?, furthest_click = ? "
            "WHERE id = ?",
            (*current, *furthest, sid),
        )


def session_events(world, cid):
    with world.db() as db:
        rows = db.execute(
            "SELECT type, actor_kind, actor_ref, payload FROM events WHERE classroom_id = ? AND type LIKE 'session_%' "
            "AND type NOT IN ('session_created') ORDER BY id",
            (cid,),
        )
        return [(r["type"], r["actor_kind"], r["actor_ref"], json.loads(r["payload"])) for r in rows]


# --- 시작 ---------------------------------------------------------------------------------


def test_start_makes_a_scheduled_session_live_at_the_first_slide(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    world.clock.advance(minutes=5)
    res = act(prof, cid, sid, "start")
    assert res.status_code == 200
    body = res.json()
    assert body["id"] == sid and body["status"] == "live"
    assert body["can_delete"] is False  # 한 번 시작한 회차는 지울 수 없다(AC4)
    r = row(world, sid)
    assert r["status"] == "live"
    assert (r["current_slide"], r["current_click"], r["furthest_slide"], r["furthest_click"]) == (1, 0, 1, 0)
    assert r["first_started_at"] == r["started_at"] == world.clock.now().isoformat()
    assert r["ended_at"] is None
    assert r["version"] == body["version"] == 1


def test_start_works_without_a_deck(world):
    # "슬라이드 없이 시작할까요?" 확인은 화면이 한다. 서버는 묶음 없이도 시작한다(AC9)
    prof, cid = classroom(world)
    sid = create(prof, cid)
    res = act(prof, cid, sid, "start")
    assert res.status_code == 200
    assert res.json()["deck"] is None


def test_only_one_session_is_live_per_classroom(world):
    prof, cid = classroom(world)
    first = create(prof, cid, "1회차")
    second = create(prof, cid, "2회차")
    assert act(prof, cid, first, "start").status_code == 200
    res = act(prof, cid, second, "start")  # DB 색인이 막는다. 두 화면이 동시에 눌러도 같다
    assert res.status_code == 409
    assert res.json() == {"detail": "1회차 수업이 진행 중입니다. 먼저 끝내 주세요.", "live_session_id": first}
    assert row(world, second)["status"] == "scheduled"


def test_a_live_session_in_another_classroom_does_not_block(world):
    prof, cid = classroom(world)
    _, other = classroom(world, "다른 강좌")
    assert act(prof, other, create(prof, other), "start").status_code == 200
    assert act(prof, cid, create(prof, cid), "start").status_code == 200


def test_starting_twice_is_harmless(world):
    # 두 번 누르거나 다시 보낸 요청: 이미 진행 중이면 그대로 돌려준다. 위치·시각·기록이 바뀌지 않는다
    prof, cid = classroom(world)
    sid = create(prof, cid)
    act(prof, cid, sid, "start")
    move(world, sid, (3, 1), (4, 0))
    before = row(world, sid)
    world.clock.advance(minutes=1)
    res = act(prof, cid, sid, "start")
    assert res.status_code == 200 and res.json()["status"] == "live"
    assert row(world, sid) == before
    assert [e[0] for e in session_events(world, cid)] == ["session_started"]


def test_an_ended_session_is_resumed_not_started(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    res = act(prof, cid, sid, "start")
    assert res.status_code == 409
    assert res.json()["detail"] == "끝난 회차입니다. '이어서 수업하기'로 다시 시작해 주세요."
    assert row(world, sid)["status"] == "ended"


def test_archived_classroom_cannot_start_or_resume(world):
    prof, cid = classroom(world)
    fresh = create(prof, cid, "예정")
    done = create(prof, cid, "끝난")
    act(prof, cid, done, "start")
    act(prof, cid, done, "end")
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    for sid, what in ((fresh, "start"), (done, "resume")):
        res = act(prof, cid, sid, what)
        assert res.status_code == 409
        assert res.json()["detail"] == ARCHIVED
    assert row(world, fresh)["status"] == "scheduled" and row(world, done)["status"] == "ended"


# --- 종료 ---------------------------------------------------------------------------------


def test_end_makes_a_live_session_ended_and_keeps_its_positions(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    act(prof, cid, sid, "start")
    move(world, sid, (2, 0), (5, 2))
    world.clock.advance(minutes=50)
    res = act(prof, cid, sid, "end")
    assert res.status_code == 200
    assert res.json()["status"] == "ended" and res.json()["version"] == 2
    r = row(world, sid)
    assert r["status"] == "ended" and r["ended_at"] == world.clock.now().isoformat()
    assert (r["current_slide"], r["current_click"], r["furthest_slide"], r["furthest_click"]) == (2, 0, 5, 2)


def test_ending_frees_the_classroom_for_another_session(world):
    prof, cid = classroom(world)
    first = create(prof, cid, "1회차")
    second = create(prof, cid, "2회차")
    act(prof, cid, first, "start")
    act(prof, cid, first, "end")
    assert act(prof, cid, second, "start").status_code == 200


def test_ending_twice_is_harmless_and_scheduled_cannot_end(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    res = act(prof, cid, sid, "end")
    assert res.status_code == 409
    assert res.json()["detail"] == "아직 시작하지 않은 회차입니다."
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    before = row(world, sid)
    world.clock.advance(minutes=1)
    again = act(prof, cid, sid, "end")
    assert again.status_code == 200 and again.json()["status"] == "ended"
    assert row(world, sid) == before
    assert [e[0] for e in session_events(world, cid)] == ["session_started", "session_ended"]


def test_a_live_session_can_still_be_ended_after_the_classroom_is_archived(world):
    # 수업 중 보관은 막지만(AC46, T031), 그 전에 생긴 "보관된 강좌의 진행 중 회차"도 끝낼 수 있어야 한다
    prof, cid = classroom(world)
    sid = create(prof, cid)
    act(prof, cid, sid, "start")
    with world.db() as db:
        db.execute("UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ?", ("2026-03-01T09:00:00+00:00", cid))
    res = act(prof, cid, sid, "end")
    assert res.status_code == 200 and row(world, sid)["status"] == "ended"


# --- 이어서 하기 ------------------------------------------------------------------------------


def test_resume_keeps_the_last_and_the_furthest_position(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    act(prof, cid, sid, "start")
    first_started = row(world, sid)["first_started_at"]
    move(world, sid, (3, 1), (7, 0))
    act(prof, cid, sid, "end")
    world.clock.advance(minutes=3)
    res = act(prof, cid, sid, "resume")
    assert res.status_code == 200
    assert res.json()["status"] == "live" and res.json()["version"] == 3
    r = row(world, sid)
    assert r["status"] == "live" and r["ended_at"] is None
    assert (r["current_slide"], r["current_click"], r["furthest_slide"], r["furthest_click"]) == (3, 1, 7, 0)
    assert r["started_at"] == world.clock.now().isoformat()
    assert r["first_started_at"] == first_started


def test_resume_is_blocked_by_another_live_session(world):
    prof, cid = classroom(world)
    first = create(prof, cid, "1회차")
    second = create(prof, cid, "2회차")
    act(prof, cid, first, "start")
    act(prof, cid, first, "end")
    act(prof, cid, second, "start")
    res = act(prof, cid, first, "resume")
    assert res.status_code == 409
    assert res.json() == {"detail": "2회차 수업이 진행 중입니다. 먼저 끝내 주세요.", "live_session_id": second}
    assert row(world, first)["status"] == "ended"


def test_resume_needs_an_ended_session(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    res = act(prof, cid, sid, "resume")
    assert res.status_code == 409
    assert res.json()["detail"] == "아직 시작하지 않은 회차입니다."
    act(prof, cid, sid, "start")
    again = act(prof, cid, sid, "resume")  # 이미 진행 중이면 그대로
    assert again.status_code == 200 and again.json()["status"] == "live"
    assert [e[0] for e in session_events(world, cid)] == ["session_started"]


# --- 발행과 기록 ----------------------------------------------------------------------------


def test_each_change_is_recorded_then_published_to_the_class_room(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    recording = bus(world)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    act(prof, cid, sid, "resume")
    assert recording.published == [
        (f"class:{cid}", {"type": "session.updated", "session_id": sid, "status": "live", "version": 1}, "live"),
        (f"class:{cid}", {"type": "session.updated", "session_id": sid, "status": "ended", "version": 2}, "ended"),
        (f"class:{cid}", {"type": "session.updated", "session_id": sid, "status": "live", "version": 3}, "live"),
    ]  # 세 번째 값: 발행하는 순간 DB에서 읽은 상태. 발행은 기록이 끝난 뒤다
    assert session_events(world, cid) == [
        ("session_started", "professor", 101, {"session_id": sid}),
        ("session_ended", "professor", 101, {"session_id": sid}),
        ("session_resumed", "professor", 101, {"session_id": sid}),
    ]


def test_nothing_is_published_when_nothing_changes(world):
    prof, cid = classroom(world)
    first = create(prof, cid, "1회차")
    second = create(prof, cid, "2회차")
    act(prof, cid, first, "start")
    recording = bus(world)
    act(prof, cid, first, "start")  # 이미 진행 중
    act(prof, cid, second, "start")  # 거절
    act(prof, cid, second, "end")  # 거절
    assert recording.published == []


def test_a_failed_publish_does_not_undo_the_change(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)

    class Broken:
        def publish(self, room, event):
            raise RuntimeError("방이 고장났다")

    world.app.state.bus = Broken()
    res = act(prof, cid, sid, "start")
    assert res.status_code == 200
    assert row(world, sid)["status"] == "live"


# --- 권한과 강좌 경계 ---------------------------------------------------------------------------


def test_only_the_owner_can_start_end_or_resume(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    other = world.client("lee")
    anonymous = world.client()
    for what in ("start", "end", "resume"):
        res = act(other, cid, sid, what)
        assert res.status_code == 403 and res.json()["detail"] == NO_PERMISSION
        assert act(anonymous, cid, sid, what).status_code == 401
    assert row(world, sid)["status"] == "scheduled"


def test_a_session_of_another_classroom_is_not_found(world):
    prof, cid = classroom(world)
    _, other = classroom(world, "다른 강좌")
    foreign = create(prof, other)
    for what in ("start", "end", "resume"):
        res = act(prof, cid, foreign, what)
        assert res.status_code == 404 and res.json()["detail"] == NOT_FOUND
    assert row(world, foreign)["status"] == "scheduled"


def test_requests_from_another_site_are_refused(world):
    prof, cid = classroom(world)
    sid = create(prof, cid)
    res = act(prof, cid, sid, "start", headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert row(world, sid)["status"] == "scheduled"
