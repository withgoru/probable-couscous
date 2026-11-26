"""002 T032: 묶음 공개·비공개(AC23, AC41, AC47, AC48, AC49 서버, C6, C8, C13).

- 새로 올리거나 바꾼 묶음은 비공개다. 교수는 회차 상태와 관계없이 공개·비공개를 바꾼다.
- 바꾸면 `deck_published`/`deck_unpublished`를 쌓고, 회차 `version`을 올리고, 커밋한 뒤 `deck.updated`를 발행한다.
- 학생의 회차 목록에는 공개 묶음이 있는 예정 회차가 들어간다(미리 보기). 그 회차의 상태도 받을 수 있다.
- 가장 멀리 간 위치는 없다(상태와 `position`에 `furthest`, `limit`이 없다).
"""

import json

import pytest
from conftest import ORIGIN
from test_class_state import act, create, live, sessions, with_student
from test_deck_serving import FIXTURE, ZIP, classroom_with_deck, enroll, entered_student
from test_session_items import RecordingBus

NO_DECK = "이 회차에 올린 슬라이드가 없습니다."
NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."


def visibility(client, cid, sid, public, headers=ORIGIN):
    return client.put(f"/api/classrooms/{cid}/sessions/{sid}/deck/visibility", json={"public": public}, headers=headers)


def upload(prof, cid, sid):
    res = prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "b.zip"}, content=FIXTURE.read_bytes(), headers=ZIP
    )
    assert res.status_code == 200, res.text
    return res.json()["deck"]


def deck_events(world, cid):
    with world.db() as db:
        rows = db.execute(
            "SELECT type, actor_kind, actor_ref, payload FROM events "
            "WHERE classroom_id = ? AND type IN ('deck_published', 'deck_unpublished') ORDER BY id",
            (cid,),
        )
        return [(r["type"], r["actor_kind"], r["actor_ref"], json.loads(r["payload"])) for r in rows]


def version(world, sid):
    with world.db() as db:
        return db.execute("SELECT version FROM class_sessions WHERE id = ?", (sid,)).fetchone()["version"]


def professor_deck(prof, cid, sid):
    (s,) = [s for s in prof.get(f"/api/classrooms/{cid}/sessions").json()["items"] if s["id"] == sid]
    return s["deck"]


# --- 공개·비공개 바꾸기 (AC47) ----------------------------------------------------------------


def test_a_new_deck_is_private(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    assert professor_deck(prof, cid, sid)["public"] is False
    assert live(prof, cid, sid).json()["deck"]["public"] is False


def test_professor_publishes_and_unpublishes_the_deck(world):
    prof, cid, sid, deck_id, _ = classroom_with_deck(world)
    res = visibility(prof, cid, sid, True)
    assert res.status_code == 200, res.text
    assert res.json()["deck"]["id"] == deck_id and res.json()["deck"]["public"] is True
    assert professor_deck(prof, cid, sid)["public"] is True
    assert visibility(prof, cid, sid, False).json()["deck"]["public"] is False
    assert deck_events(world, cid) == [
        ("deck_published", "professor", 101, {"session_id": sid, "deck_id": deck_id}),
        ("deck_unpublished", "professor", 101, {"session_id": sid, "deck_id": deck_id}),
    ]


@pytest.mark.parametrize("state", ["scheduled", "live", "ended"])
def test_visibility_changes_in_any_session_state(world, state):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    if state != "scheduled":
        act(prof, cid, sid, "start")
    if state == "ended":
        act(prof, cid, sid, "end")
    assert visibility(prof, cid, sid, True).status_code == 200
    assert professor_deck(prof, cid, sid)["public"] is True


def test_change_is_recorded_then_published_with_the_next_version(world):
    # AC48: 수업 중인 화면은 이 발행으로 1초 안에 바뀐다
    prof, cid, sid, deck_id, _ = classroom_with_deck(world)
    act(prof, cid, sid, "start")
    before = version(world, sid)
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    visibility(prof, cid, sid, True)
    assert recording.published == [
        (f"class:{cid}", {"type": "deck.updated", "session_id": sid,
                          "deck": {"id": deck_id, "slide_count": 4, "available": True, "public": True},
                          "version": before + 1}, before + 1),
    ]  # 발행하는 순간 DB에는 이미 그 버전이 있다
    assert version(world, sid) == before + 1


def test_setting_the_same_value_changes_nothing(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    before = version(world, sid)
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    assert visibility(prof, cid, sid, False).json()["deck"]["public"] is False
    assert recording.published == [] and deck_events(world, cid) == [] and version(world, sid) == before


def test_a_failed_publish_keeps_the_change(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)

    class Broken:
        def publish(self, room, event):
            raise RuntimeError("bus down")

    world.app.state.bus = Broken()
    assert visibility(prof, cid, sid, True).status_code == 200
    assert professor_deck(prof, cid, sid)["public"] is True


def test_session_without_a_deck_cannot_be_published(world):
    prof, cid, _, _, _ = classroom_with_deck(world)
    empty = create(prof, cid, "2회차")
    res = visibility(prof, cid, empty, True)
    assert res.status_code == 404 and res.json()["detail"] == NO_DECK


@pytest.mark.parametrize("value", [None, "true", 1, 0])
def test_public_must_be_true_or_false(world, value):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    assert visibility(prof, cid, sid, value).status_code == 422
    assert professor_deck(prof, cid, sid)["public"] is False


def test_only_the_owner_changes_visibility(world):
    prof, cid, sid, _, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    other = world.client("lee")
    assert visibility(student, cid, sid, True).status_code == 401  # 교수 로그인이 아니다
    res = visibility(other, cid, sid, True)
    assert res.status_code == 403 and res.json()["detail"] == NO_PERMISSION
    assert professor_deck(prof, cid, sid)["public"] is False


def test_visibility_change_checks_the_origin(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    assert visibility(prof, cid, sid, True, headers={"Origin": "https://evil.example"}).status_code == 403


def test_replacing_a_public_deck_starts_private(world):
    # AC41, AC47: 바꾼 묶음은 비공개로 시작한다
    prof, cid, sid, _, _ = classroom_with_deck(world)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    visibility(prof, cid, sid, True)
    new = upload(prof, cid, sid)
    assert new["public"] is False
    assert professor_deck(prof, cid, sid)["public"] is False


# --- 학생이 보는 범위 (AC23, AC49) ------------------------------------------------------------


def test_student_list_includes_scheduled_sessions_with_a_public_deck(world):
    prof, cid, ended, _, student = with_student(world)
    act(prof, cid, ended, "start")
    act(prof, cid, ended, "end")
    preview_late = create(prof, cid, "3회차")
    upload(prof, cid, preview_late)
    visibility(prof, cid, preview_late, True)
    preview_soon = create(prof, cid, "2회차")  # 회차 순서는 만든 순서다
    upload(prof, cid, preview_soon)
    visibility(prof, cid, preview_soon, True)
    private = create(prof, cid, "4회차")
    upload(prof, cid, private)  # 비공개 예정 회차는 보이지 않는다
    create(prof, cid, "5회차")  # 묶음 없는 예정 회차도 보이지 않는다
    body = sessions(student, cid).json()
    assert [(s["id"], s["status"]) for s in body["items"]] == [
        (preview_late, "scheduled"), (preview_soon, "scheduled"), (ended, "ended")
    ]  # 진행 중 → 예정(회차 순서) → 종료(최근 것부터)
    assert all(s["deck"]["public"] for s in body["items"] if s["status"] == "scheduled")


def test_unpublishing_hides_the_scheduled_session_again(world):
    prof, cid, sid, _, student = with_student(world)
    visibility(prof, cid, sid, True)
    assert [s["id"] for s in sessions(student, cid).json()["items"]] == [sid]
    visibility(prof, cid, sid, False)
    assert sessions(student, cid).json()["items"] == []


def test_student_reads_a_scheduled_session_only_with_a_public_deck(world):
    prof, cid, sid, deck_id, student = with_student(world)
    assert live(student, cid, sid).status_code == 404
    visibility(prof, cid, sid, True)
    res = live(student, cid, sid)
    assert res.status_code == 200
    assert res.json()["deck"] == {"id": deck_id, "slide_count": 4, "available": True, "public": True}
    assert res.json()["session"]["status"] == "scheduled"


def test_ended_session_with_a_private_deck_is_still_listed(world):
    # AC39: 지난 회차는 비공개여도 보인다(자료를 다시 본다)
    prof, cid, sid, _, student = with_student(world)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    (item,) = sessions(student, cid).json()["items"]
    assert item["status"] == "ended" and item["deck"]["public"] is False
    assert live(student, cid, sid).status_code == 200


def test_state_has_no_furthest_position(world):
    prof, cid, sid, _, student = with_student(world)
    act(prof, cid, sid, "start")
    body = live(student, cid, sid).json()
    assert "furthest" not in body and "limit" not in body


# --- 묶음을 바꾸거나 지우면 열어 둔 화면이 다시 받는다 ----------------------------------------
# 미리 보거나 다시 보는 학생은 예정·종료 회차를 열어 둔다. 묶음이 바뀌면(새 묶음은 비공개) 알아야 한다


def test_replacing_a_deck_tells_open_screens(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    before = version(world, sid)
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    upload(prof, cid, sid)
    assert version(world, sid) == before  # 진행 중이 아닌 회차라 수업 중 발행 순서와 무관하다
    assert recording.published == [
        (f"class:{cid}", {"type": "session.updated", "session_id": sid, "status": "scheduled", "version": before}, before),
    ]  # 기록한 뒤에 알린다(C13). 화면은 이것을 받고 상태를 통째로 다시 받는다


def test_removing_a_deck_tells_open_screens(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    before = version(world, sid)
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    assert prof.delete(f"/api/classrooms/{cid}/sessions/{sid}/deck", headers=ORIGIN).status_code == 204
    assert version(world, sid) == before
    assert recording.published == [
        (f"class:{cid}", {"type": "session.updated", "session_id": sid, "status": "ended", "version": before}, before),
    ]


def test_a_failed_upload_tells_nobody(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    before = version(world, sid)
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    res = prof.put(f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "x.zip"}, content=b"not a zip", headers=ZIP)
    assert res.status_code == 422
    assert version(world, sid) == before and recording.published == []
