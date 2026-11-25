"""002 T004: 회차 만들기·이름 바꾸기·삭제·목록(AC1~AC4, AC8 서버).

- 회차는 '예정'으로 목록 끝에 생긴다. 이름은 1~40자이고 겹쳐도 된다(AC2).
- 이름은 언제든 바꿀 수 있다. 삭제는 한 번도 시작하지 않은 회차만 되고, 그 회차의 묶음도 함께 지운다(AC4).
- 강좌 목록의 "진행 회차"는 한 번이라도 시작한 회차 수다(AC8).
- 행동마다 기록을 남긴다(C6). 다른 강좌의 회차는 찾을 수 없다(C5).
"""

import json

from conftest import ORIGIN

NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."
NOT_FOUND = "찾을 수 없는 회차입니다."


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    return prof, cid


def create(prof, cid, title="3주차 1회차"):
    return prof.post(f"/api/classrooms/{cid}/sessions", json={"title": title}, headers=ORIGIN)


def mark_started(world, session_id, status="ended"):
    # 시작은 T007의 일이다. 여기서는 시작한 적이 있는 회차를 DB에 직접 만든다
    with world.db() as db:
        db.execute(
            "UPDATE class_sessions SET status = ?, first_started_at = '2026-03-01T09:00:00+00:00' WHERE id = ?",
            (status, session_id),
        )


def event_types(world, cid):
    with world.db() as db:
        rows = db.execute("SELECT type, actor_kind, actor_ref, payload FROM events WHERE classroom_id = ? ORDER BY id", (cid,))
        return [(r["type"], r["actor_kind"], r["actor_ref"], json.loads(r["payload"])) for r in rows]


# --- 목록과 만들기 ------------------------------------------------------------------------


def test_new_classroom_has_no_sessions(world):
    prof, cid = classroom(world)
    res = prof.get(f"/api/classrooms/{cid}/sessions")
    assert res.status_code == 200
    assert res.json() == {"items": []}


def test_create_adds_a_scheduled_session_at_the_end(world):
    prof, cid = classroom(world)
    first = create(prof, cid, "2주차 1회차")
    assert first.status_code == 201
    body = first.json()
    assert body["title"] == "2주차 1회차"
    assert body["status"] == "scheduled"
    assert body["can_delete"] is True
    second = create(prof, cid, "  2주차 2회차  ").json()
    assert second["title"] == "2주차 2회차"  # 앞뒤 공백은 뺀다
    items = prof.get(f"/api/classrooms/{cid}/sessions").json()["items"]
    assert [i["title"] for i in items] == ["2주차 1회차", "2주차 2회차"]
    assert [i["id"] for i in items] == [body["id"], second["id"]]


def test_title_is_required_and_at_most_40_characters(world):
    prof, cid = classroom(world)
    for blank in ("", "   ", None, 3):
        res = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": blank}, headers=ORIGIN)
        assert res.status_code == 422
        assert res.json()["detail"] == "회차 이름을 입력해 주세요."
    long = create(prof, cid, "가" * 41)
    assert long.status_code == 422
    assert long.json()["detail"] == "회차 이름은 40자 이하로 입력해 주세요."
    assert create(prof, cid, "가" * 40).status_code == 201
    assert prof.get(f"/api/classrooms/{cid}/sessions").json()["items"][0]["title"] == "가" * 40


def test_same_title_may_repeat(world):
    prof, cid = classroom(world)
    assert create(prof, cid, "보강").status_code == 201
    assert create(prof, cid, "보강").status_code == 201
    assert len(prof.get(f"/api/classrooms/{cid}/sessions").json()["items"]) == 2


def test_list_shows_status_for_each_session(world):
    # AC3: 목록에 이름과 상태가 있다(진행 중 구분은 화면 몫)
    prof, cid = classroom(world)
    a, b, c = (create(prof, cid, t).json()["id"] for t in ("1회차", "2회차", "3회차"))
    mark_started(world, a, "ended")
    mark_started(world, b, "live")
    items = {i["id"]: i for i in prof.get(f"/api/classrooms/{cid}/sessions").json()["items"]}
    assert (items[a]["status"], items[b]["status"], items[c]["status"]) == ("ended", "live", "scheduled")
    assert (items[a]["can_delete"], items[b]["can_delete"], items[c]["can_delete"]) == (False, False, True)


# --- 이름 바꾸기 -----------------------------------------------------------------------------


def test_rename_works_in_any_state(world):
    prof, cid = classroom(world)
    sid = create(prof, cid, "1회차").json()["id"]
    res = prof.patch(f"/api/classrooms/{cid}/sessions/{sid}", json={"title": "1회차 (보강)"}, headers=ORIGIN)
    assert res.status_code == 200 and res.json()["title"] == "1회차 (보강)"
    mark_started(world, sid, "live")
    res = prof.patch(f"/api/classrooms/{cid}/sessions/{sid}", json={"title": "진행 중에 바꿈"}, headers=ORIGIN)
    assert res.status_code == 200 and res.json()["title"] == "진행 중에 바꿈"
    bad = prof.patch(f"/api/classrooms/{cid}/sessions/{sid}", json={"title": " "}, headers=ORIGIN)
    assert bad.status_code == 422 and bad.json()["detail"] == "회차 이름을 입력해 주세요."


# --- 삭제 ------------------------------------------------------------------------------------


def test_delete_a_never_started_session_and_its_deck(world):
    prof, cid = classroom(world)
    keep = create(prof, cid, "남길 회차").json()["id"]
    sid = create(prof, cid, "지울 회차").json()["id"]
    with world.db() as db:
        db.execute(
            "INSERT INTO decks(classroom_id, session_id, original_name, slide_count, size_bytes, uploaded_at) "
            "VALUES (?, ?, 'a.zip', 4, 10, '2026-03-01T09:00:00+00:00')",
            (cid, sid),
        )
    res = prof.delete(f"/api/classrooms/{cid}/sessions/{sid}", headers=ORIGIN)
    assert res.status_code == 204
    assert [i["id"] for i in prof.get(f"/api/classrooms/{cid}/sessions").json()["items"]] == [keep]
    with world.db() as db:
        assert db.execute("SELECT COUNT(*) FROM decks WHERE session_id = ?", (sid,)).fetchone()[0] == 0


def test_a_session_that_was_ever_started_cannot_be_deleted(world):
    prof, cid = classroom(world)
    for status in ("live", "ended"):
        sid = create(prof, cid, status).json()["id"]
        mark_started(world, sid, status)
        res = prof.delete(f"/api/classrooms/{cid}/sessions/{sid}", headers=ORIGIN)
        assert res.status_code == 409
        assert res.json()["detail"] == "한 번이라도 시작한 회차는 삭제할 수 없습니다."
    assert len(prof.get(f"/api/classrooms/{cid}/sessions").json()["items"]) == 2


# --- 진행 회차 수(AC8) -------------------------------------------------------------------------


def test_classroom_list_counts_sessions_that_were_ever_started(world):
    prof, cid = classroom(world)
    ids = [create(prof, cid, f"{n}회차").json()["id"] for n in range(1, 5)]
    mark_started(world, ids[0], "ended")
    mark_started(world, ids[1], "live")
    listed = {c["id"]: c for c in prof.get("/api/classrooms").json()["classrooms"]}
    assert listed[cid]["session_count"] == 2
    assert prof.get(f"/api/classrooms/{cid}").json()["session_count"] == 2
    _, other = classroom(world, "다른 강좌")
    assert {c["id"]: c for c in prof.get("/api/classrooms").json()["classrooms"]}[other]["session_count"] == 0


# --- 기록(C6) ---------------------------------------------------------------------------------


def test_each_action_is_recorded_without_the_title(world):
    prof, cid = classroom(world)
    sid = create(prof, cid, "1회차").json()["id"]
    prof.patch(f"/api/classrooms/{cid}/sessions/{sid}", json={"title": "1회차 고침"}, headers=ORIGIN)
    prof.delete(f"/api/classrooms/{cid}/sessions/{sid}", headers=ORIGIN)
    assert event_types(world, cid) == [
        ("session_created", "professor", 101, {"session_id": sid}),
        ("session_renamed", "professor", 101, {"session_id": sid}),
        ("session_deleted", "professor", 101, {"session_id": sid}),
    ]


# --- 권한과 강좌 구분(C5, C8) -----------------------------------------------------------------


def test_other_professor_and_anonymous_are_refused(world):
    prof, cid = classroom(world)
    sid = create(prof, cid).json()["id"]
    lee = world.client("lee")
    for res in (
        lee.get(f"/api/classrooms/{cid}/sessions"),
        create(lee, cid),
        lee.patch(f"/api/classrooms/{cid}/sessions/{sid}", json={"title": "x"}, headers=ORIGIN),
        lee.delete(f"/api/classrooms/{cid}/sessions/{sid}", headers=ORIGIN),
    ):
        assert res.status_code == 403 and res.json()["detail"] == NO_PERMISSION
    anon = world.client()
    assert anon.get(f"/api/classrooms/{cid}/sessions").status_code == 401
    assert create(anon, cid).status_code == 401


def test_session_of_another_classroom_is_not_found(world):
    prof, a = classroom(world, "A")
    _, b = classroom(world, "B")
    sid_in_b = create(prof, b).json()["id"]
    for res in (
        prof.patch(f"/api/classrooms/{a}/sessions/{sid_in_b}", json={"title": "x"}, headers=ORIGIN),
        prof.delete(f"/api/classrooms/{a}/sessions/{sid_in_b}", headers=ORIGIN),
        prof.patch(f"/api/classrooms/{a}/sessions/999999", json={"title": "x"}, headers=ORIGIN),
    ):
        assert res.status_code == 404 and res.json()["detail"] == NOT_FOUND
    assert prof.get(f"/api/classrooms/{b}/sessions").json()["items"][0]["title"] == "3주차 1회차"


def test_archived_classroom_sessions_can_still_be_managed(world):
    # 001 결정: 보관된 강좌도 교수는 관리한다(session.manage)
    prof, cid = classroom(world)
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    assert create(prof, cid).status_code == 201
