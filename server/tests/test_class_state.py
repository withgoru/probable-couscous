"""002 T008: 회차 목록과 회차 현재 상태(AC16, AC23, AC27, AC29, AC39, AC41 서버).

- `GET /api/class/{강좌}/sessions`: 교수에게는 모든 회차, 학생에게는 진행 중과 종료 회차만(최근 것부터) 준다.
- `GET /api/class/{강좌}/sessions/{회차}/live`: 상태를 통째로 준다. 회차 상태, 묶음 번호와 슬라이드 수,
  현재·가장 멀리 간 위치, 학생이 볼 수 있는 끝(`limit`), 보낸 항목, `version`. 화면은 이것으로 다시 맞춘다.
- 학생 응답에는 거둔 항목이 없다. 예정 회차와 다른 강좌의 회차는 없는 것과 같다(404, C5).
- 종료 뒤 묶음을 바꾸면 학생이 볼 수 있는 끝은 가장 멀리 간 위치의 슬라이드 번호까지다(단계는 그 슬라이드 전부).
"""

from conftest import ORIGIN
from test_deck_serving import FIXTURE, ZIP, classroom_with_deck, enroll, entered_student

NOT_FOUND = "찾을 수 없는 회차입니다."
NOT_MEMBER = "이 강좌에 입장한 학생만 볼 수 있습니다."


def create(prof, cid, title):
    return prof.post(f"/api/classrooms/{cid}/sessions", json={"title": title}, headers=ORIGIN).json()["id"]


def act(prof, cid, sid, what):
    res = prof.post(f"/api/classrooms/{cid}/sessions/{sid}/{what}", headers=ORIGIN)
    assert res.status_code == 200, res.text


def move(world, sid, current, furthest):
    # 넘기기는 T009의 일이다. 여기서는 위치를 DB에 직접 둔다
    with world.db() as db:
        db.execute(
            "UPDATE class_sessions SET current_slide = ?, current_click = ?, furthest_slide = ?, furthest_click = ?, "
            "version = version + 1 WHERE id = ?",
            (*current, *furthest, sid),
        )


def add_item(world, cid, sid, key, body=None, url=None, retracted=False):
    # 보내기·거두기는 T010의 일이다. 여기서는 항목을 DB에 직접 둔다
    with world.db() as db:
        cur = db.execute(
            "INSERT INTO session_items(classroom_id, session_id, body, url, client_key, created_at, retracted_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, sid, body, url, key, world.clock.now().isoformat(), world.clock.now().isoformat() if retracted else None),
        )
        return cur.lastrowid


def sessions(client, cid):
    return client.get(f"/api/class/{cid}/sessions")


def live(client, cid, sid):
    return client.get(f"/api/class/{cid}/sessions/{sid}/live")


def with_student(world):
    prof, cid, sid, deck_id, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    return prof, cid, sid, deck_id, entered_student(world, token, "kim@x.kr")


# --- 회차 목록 -----------------------------------------------------------------------------


def test_professor_sees_every_session_in_order(world):
    prof, cid, first, _, _ = classroom_with_deck(world)
    second = create(prof, cid, "2회차")
    third = create(prof, cid, "3회차")
    act(prof, cid, second, "start")
    res = sessions(prof, cid)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert [(s["id"], s["status"]) for s in body["items"]] == [(first, "scheduled"), (second, "live"), (third, "scheduled")]
    assert body["live_session_id"] == second
    assert body["items"][0]["title"] == "1회차"


def test_student_sees_live_and_ended_sessions_most_recent_first(world):
    prof, cid, first, _, student = with_student(world)
    second = create(prof, cid, "2회차")
    third = create(prof, cid, "3회차")
    create(prof, cid, "4회차")  # 예정: 학생에게 보이지 않는다
    act(prof, cid, first, "start")
    world.clock.advance(minutes=60)
    act(prof, cid, first, "end")
    world.clock.advance(hours=2)
    act(prof, cid, second, "start")
    world.clock.advance(minutes=60)
    act(prof, cid, second, "end")
    world.clock.advance(hours=2)
    act(prof, cid, third, "start")
    body = sessions(student, cid).json()
    assert [(s["id"], s["status"]) for s in body["items"]] == [(third, "live"), (second, "ended"), (first, "ended")]
    assert body["live_session_id"] == third


def test_no_live_session_is_reported_as_none(world):
    # AC23: 진행 중인 회차가 없으면 학생 화면은 안내와 지난 회차 목록을 보인다
    prof, cid, sid, _, student = with_student(world)
    body = sessions(student, cid).json()
    assert body == {"items": [], "live_session_id": None}
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    body = sessions(student, cid).json()
    assert body["live_session_id"] is None and [s["id"] for s in body["items"]] == [sid]


def test_listed_session_shape(world):
    prof, cid, sid, deck_id, student = with_student(world)
    act(prof, cid, sid, "start")
    (item,) = sessions(student, cid).json()["items"]
    assert item == {
        "id": sid,
        "title": "1회차",
        "status": "live",
        "started_at": world.clock.now().isoformat(),
        "ended_at": None,
        "deck": {"id": deck_id, "slide_count": 4, "available": True},
    }


# --- 회차 현재 상태 -------------------------------------------------------------------------


def test_live_state_for_a_session_in_class(world):
    prof, cid, sid, deck_id, student = with_student(world)
    act(prof, cid, sid, "start")
    move(world, sid, (2, 1), (3, 0))
    kept = add_item(world, cid, sid, "a", body="과제 안내")
    gone = add_item(world, cid, sid, "b", url="https://example.com/x", retracted=True)
    res = live(student, cid, sid)
    assert res.status_code == 200
    assert res.headers["cache-control"] == "no-store"
    body = res.json()
    assert body["session"] == {
        "id": sid,
        "title": "1회차",
        "status": "live",
        "version": 2,
        "started_at": world.clock.now().isoformat(),  # 교수 화면의 경과 시간(AC12)
    }
    assert body["deck"] == {"id": deck_id, "slide_count": 4, "available": True}
    assert body["current"] == {"slide": 2, "click": 1}
    assert body["furthest"] == {"slide": 3, "click": 0}
    assert body["limit"] == {"slide": 3, "click": 0}  # AC27: 학생은 가장 멀리 간 위치까지
    assert body["items"] == [
        {"id": kept, "body": "과제 안내", "url": None, "created_at": world.clock.now().isoformat()}
    ]  # 거둔 항목은 학생에게 없다
    assert gone not in [i["id"] for i in body["items"]]


def test_professor_sees_retracted_items_marked(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    act(prof, cid, sid, "start")
    kept = add_item(world, cid, sid, "a", body="하나")
    gone = add_item(world, cid, sid, "b", body="둘", retracted=True)
    items = live(prof, cid, sid).json()["items"]
    now = world.clock.now().isoformat()
    assert items == [
        {"id": kept, "body": "하나", "url": None, "created_at": now, "retracted_at": None},
        {"id": gone, "body": "둘", "url": None, "created_at": now, "retracted_at": now},
    ]


def test_professor_can_read_a_scheduled_session_but_a_student_cannot(world):
    prof, cid, sid, _, student = with_student(world)
    body = live(prof, cid, sid).json()
    assert body["session"]["status"] == "scheduled"
    assert body["current"] == {"slide": 1, "click": 0}
    res = live(student, cid, sid)
    assert res.status_code == 404 and res.json()["detail"] == NOT_FOUND


def test_reopened_professor_screen_resumes_from_the_last_position(world):
    # AC16, AC29: 다시 열거나 새로 들어온 화면은 DB의 위치에서 이어진다
    prof, cid, sid, _, student = with_student(world)
    act(prof, cid, sid, "start")
    move(world, sid, (4, 1), (4, 1))
    for client in (prof, world.client("kim"), student):
        assert live(client, cid, sid).json()["current"] == {"slide": 4, "click": 1}


def test_ended_session_keeps_its_range(world):
    # AC39: 종료 회차는 처음부터 가장 멀리 간 위치까지
    prof, cid, sid, _, student = with_student(world)
    act(prof, cid, sid, "start")
    move(world, sid, (1, 0), (3, 2))
    act(prof, cid, sid, "end")
    body = live(student, cid, sid).json()
    assert body["session"]["status"] == "ended"
    assert body["limit"] == {"slide": 3, "click": 2}


def test_replacing_the_deck_after_the_class_widens_clicks_to_the_whole_slide(world):
    # AC41: 새 묶음은 단계 수가 다를 수 있다. 슬라이드 번호까지만 지키고 그 슬라이드의 단계는 모두 보인다
    prof, cid, sid, _, student = with_student(world)
    act(prof, cid, sid, "start")
    move(world, sid, (2, 0), (2, 1))
    act(prof, cid, sid, "end")
    world.clock.advance(hours=1)
    res = prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "b.zip"}, content=FIXTURE.read_bytes(), headers=ZIP
    )
    assert res.status_code == 200
    body = live(student, cid, sid).json()
    assert body["deck"]["id"] == res.json()["deck"]["id"]
    assert body["limit"] == {"slide": 2, "click": None}  # None: 그 슬라이드의 마지막 단계까지
    assert body["furthest"] == {"slide": 2, "click": 1}


def test_limit_never_goes_past_the_last_slide_of_the_deck(world):
    # 새 묶음이 더 짧으면 그 묶음의 마지막 슬라이드까지다
    prof, cid, sid, _, student = with_student(world)
    act(prof, cid, sid, "start")
    move(world, sid, (6, 0), (9, 3))
    act(prof, cid, sid, "end")
    world.clock.advance(hours=1)
    prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "b.zip"}, content=FIXTURE.read_bytes(), headers=ZIP
    )
    assert live(student, cid, sid).json()["limit"] == {"slide": 4, "click": None}


def test_session_without_a_deck(world):
    prof = world.client("kim")
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    sid = create(prof, cid, "슬라이드 없음")
    act(prof, cid, sid, "start")
    body = live(prof, cid, sid).json()
    assert body["deck"] is None
    assert body["limit"] == {"slide": 1, "click": 0}


def test_deck_whose_files_are_missing_is_reported(world):
    import shutil

    prof, cid, sid, deck_id, _ = classroom_with_deck(world)
    shutil.rmtree(world.app.state.deck_store.path_for(cid, deck_id))
    assert live(prof, cid, sid).json()["deck"] == {"id": deck_id, "slide_count": 4, "available": False}


# --- 권한과 강좌 경계 ---------------------------------------------------------------------------


def test_session_of_another_classroom_is_not_found(world):
    prof, cid, _, _, _ = classroom_with_deck(world)
    other = prof.post("/api/classrooms", json={"name": "다른"}, headers=ORIGIN).json()["id"]
    foreign = create(prof, other, "다른 회차")
    act(prof, other, foreign, "start")
    res = live(prof, cid, foreign)
    assert res.status_code == 404 and res.json()["detail"] == NOT_FOUND


def test_outsiders_are_refused(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    act(prof, cid, sid, "start")
    # 다른 강좌에만 입장한 학생
    _, other_cid, _, _, other_token = classroom_with_deck(world, name="다른 강좌")
    enroll(prof, other_cid, "lee@x.kr")
    lee = entered_student(world, other_token, "lee@x.kr")
    for res in (sessions(lee, cid), live(lee, cid, sid)):
        assert res.status_code == 403 and res.json()["detail"] == NOT_MEMBER
    for res in (sessions(world.client("lee"), cid), live(world.client("lee"), cid, sid)):
        assert res.status_code == 403
    anonymous = world.client()
    assert sessions(anonymous, cid).status_code == 401
    assert live(anonymous, cid, sid).status_code == 401
    assert sessions(prof, 9999).status_code == 404


def test_removed_student_is_refused(world):
    prof, cid, sid, _, token = classroom_with_deck(world)
    entry = enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    act(prof, cid, sid, "start")
    assert live(student, cid, sid).status_code == 200
    assert prof.delete(f"/api/classrooms/{cid}/roster/{entry}", headers=ORIGIN).status_code in (200, 204)
    assert live(student, cid, sid).status_code == 403


def test_items_belong_to_their_own_session(world):
    prof, cid, first, _, student = with_student(world)
    second = create(prof, cid, "2회차")
    act(prof, cid, first, "start")
    mine = add_item(world, cid, first, "a", body="1회차 자료")
    act(prof, cid, first, "end")
    act(prof, cid, second, "start")
    add_item(world, cid, second, "a", body="2회차 자료")
    assert [i["id"] for i in live(student, cid, first).json()["items"]] == [mine]
    assert [i["body"] for i in live(prof, cid, second).json()["items"]] == ["2회차 자료"]


def test_started_at_is_the_latest_start(world):
    # 이어서 하면 경과 시간은 이어서 한 때부터 센다. 시작하지 않은 회차는 비어 있다
    prof, cid, sid, _, _ = with_student(world)
    assert live(prof, cid, sid).json()["session"]["started_at"] is None
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    world.clock.advance(minutes=30)
    act(prof, cid, sid, "resume")
    assert live(prof, cid, sid).json()["session"]["started_at"] == world.clock.now().isoformat()
