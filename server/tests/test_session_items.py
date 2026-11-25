"""002 T010: 메시지·자료 보내기와 거두기(AC31, AC32, AC33, AC35 서버, C2, C6, C13).

- 글 1~2000자 또는 링크(http/https만). 둘 다 비면 거절. 잘못된 칸은 `{field, message}`로 알린다.
- 같은 `client_key`는 한 번만 저장하고 같은 응답을 준다(다시 눌러도, 응답이 늦어 다시 보내도).
- 진행 중인 회차에만 보낸다. 저장한 뒤 `item.created`를 발행한다.
- 거두기는 `retracted_at`을 쓰고 `item.retracted`를 발행한다. 되살리지 않는다. 원문은 표에 남는다.
- 기록은 `item_sent`, `item_retracted`이고 본문은 넣지 않는다.
"""

import json

import pytest
from conftest import ORIGIN
from test_deck_serving import classroom_with_deck, enroll, entered_student

from app.db import connect

NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."
BAD_LINK = "링크는 http:// 또는 https://로 시작해야 합니다."


class RecordingBus:
    def __init__(self, database_path):
        self.database_path = database_path
        self.published = []

    def publish(self, room, event):
        with connect(self.database_path) as db:
            (version,) = db.execute(
                "SELECT version FROM class_sessions WHERE id = ?", (event["session_id"],)
            ).fetchone()
        self.published.append((room, event, version))  # 발행하는 순간 DB의 버전

    def subscribe(self, room):  # pragma: no cover
        raise NotImplementedError


def live(world):
    prof, cid, sid, _, token = classroom_with_deck(world)
    assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/start", headers=ORIGIN).status_code == 200
    return prof, cid, sid, token


def send(prof, cid, sid, body=None, url=None, key="k1", headers=ORIGIN):
    return prof.post(
        f"/api/classrooms/{cid}/sessions/{sid}/items", json={"body": body, "url": url, "client_key": key}, headers=headers
    )


def retract(prof, cid, sid, item_id, headers=ORIGIN):
    return prof.post(f"/api/classrooms/{cid}/sessions/{sid}/items/{item_id}/retract", headers=headers)


def items(world, sid):
    with world.db() as db:
        return [dict(r) for r in db.execute("SELECT * FROM session_items WHERE session_id = ? ORDER BY id", (sid,))]


def item_events(world, cid):
    with world.db() as db:
        rows = db.execute(
            "SELECT type, actor_kind, actor_ref, payload FROM events WHERE classroom_id = ? AND type LIKE 'item_%' "
            "ORDER BY id",
            (cid,),
        )
        return [(r["type"], r["actor_kind"], r["actor_ref"], json.loads(r["payload"])) for r in rows]


def version(world, sid):
    with world.db() as db:
        return db.execute("SELECT version FROM class_sessions WHERE id = ?", (sid,)).fetchone()["version"]


# --- 보내기 --------------------------------------------------------------------------------


def test_send_a_text_and_a_link(world):
    prof, cid, sid, _ = live(world)
    world.clock.advance(minutes=10)
    res = send(prof, cid, sid, body="과제 제출은 금요일까지", url="https://example.com/hw")
    assert res.status_code == 201
    body = res.json()
    now = world.clock.now().isoformat()
    assert body == {
        "item": {"id": body["item"]["id"], "body": "과제 제출은 금요일까지", "url": "https://example.com/hw",
                 "created_at": now, "retracted_at": None},
        "version": 2,
    }
    (row,) = items(world, sid)
    assert (row["body"], row["url"], row["client_key"], row["classroom_id"]) == (
        "과제 제출은 금요일까지", "https://example.com/hw", "k1", cid
    )
    assert version(world, sid) == 2


@pytest.mark.parametrize(
    ("body", "url", "stored"),
    [
        ("글만", None, ("글만", None)),
        (None, "http://example.com", (None, "http://example.com")),
        ("  앞뒤 공백  ", "  https://example.com/a  ", ("  앞뒤 공백  ", "https://example.com/a")),
        ("가" * 2000, "", ("가" * 2000, None)),
        ("   ", "https://example.com", (None, "https://example.com")),
    ],
)
def test_text_or_link_alone_is_enough(world, body, url, stored):
    prof, cid, sid, _ = live(world)
    assert send(prof, cid, sid, body=body, url=url).status_code == 201
    (row,) = items(world, sid)
    assert (row["body"], row["url"]) == stored  # 글은 그대로 두고(줄바꿈·띄어쓰기는 교수가 쓴 대로), 빈 칸은 없는 것


def test_both_empty_is_refused(world):
    prof, cid, sid, _ = live(world)
    for body, url in ((None, None), ("", ""), ("  \n ", "  ")):
        res = send(prof, cid, sid, body=body, url=url)
        assert res.status_code == 422
        assert res.json()["detail"] == {"field": None, "message": "글이나 링크를 입력해 주세요."}
    assert items(world, sid) == []


def test_text_longer_than_2000_is_refused(world):
    prof, cid, sid, _ = live(world)
    res = send(prof, cid, sid, body="가" * 2001)
    assert res.status_code == 422
    assert res.json()["detail"] == {"field": "body", "message": "글은 2000자 이하로 입력해 주세요."}


@pytest.mark.parametrize(
    "url",
    ["example.com", "보기 https://example.com", "ftp://example.com", "javascript:alert(1)", "https://", "http:// space.com", "HTTPS//x", 3],
)
def test_links_must_be_http_or_https(world, url):
    prof, cid, sid, _ = live(world)
    res = send(prof, cid, sid, body="글", url=url)
    assert res.status_code == 422
    assert res.json()["detail"] == {"field": "url", "message": BAD_LINK}
    assert items(world, sid) == []


def test_upper_case_scheme_is_a_link_too(world):
    prof, cid, sid, _ = live(world)
    assert send(prof, cid, sid, url="HTTPS://Example.com/A").status_code == 201
    assert items(world, sid)[0]["url"] == "HTTPS://Example.com/A"


def test_very_long_link_is_refused(world):
    prof, cid, sid, _ = live(world)
    res = send(prof, cid, sid, url="https://example.com/" + "a" * 2000)
    assert res.status_code == 422
    assert res.json()["detail"] == {"field": "url", "message": "링크는 2000자 이하로 입력해 주세요."}


@pytest.mark.parametrize("key", [None, "", "a" * 65, "한글", "a b", 7])
def test_client_key_is_required(world, key):
    prof, cid, sid, _ = live(world)
    res = send(prof, cid, sid, body="글", key=key)
    assert res.status_code == 422
    assert res.json()["detail"] == {"field": None, "message": "보내기 요청이 올바르지 않습니다. 화면을 새로 고쳐 주세요."}


def test_the_same_client_key_is_stored_once(world):
    prof, cid, sid, _ = live(world)
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    first = send(prof, cid, sid, body="한 번만", key="same")
    again = send(prof, cid, sid, body="한 번만", key="same")
    assert first.status_code == again.status_code == 201
    assert again.json() == first.json()
    assert len(items(world, sid)) == 1
    assert len(recording.published) == 1 and len(item_events(world, cid)) == 1
    assert version(world, sid) == 2
    other = send(prof, cid, sid, body="한 번만", key="other")  # 다른 키면 같은 글도 새 항목
    assert other.status_code == 201 and other.json()["item"]["id"] != first.json()["item"]["id"]


def test_the_same_client_key_in_another_session_is_a_new_item(world):
    prof, cid, sid, _ = live(world)
    send(prof, cid, sid, body="1회차", key="k")
    prof.post(f"/api/classrooms/{cid}/sessions/{sid}/end", headers=ORIGIN)
    second = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "2회차"}, headers=ORIGIN).json()["id"]
    prof.post(f"/api/classrooms/{cid}/sessions/{second}/start", headers=ORIGIN)
    res = send(prof, cid, second, body="2회차", key="k")
    assert res.status_code == 201 and res.json()["item"]["body"] == "2회차"


def test_only_a_live_session_takes_items(world):
    prof, cid, sid, _ = classroom_with_deck(world)[0:3] + (None,)
    res = send(prof, cid, sid, body="아직")
    assert res.status_code == 409
    assert res.json()["detail"] == {"field": None, "message": "진행 중인 수업에만 보낼 수 있습니다."}
    prof.post(f"/api/classrooms/{cid}/sessions/{sid}/start", headers=ORIGIN)
    prof.post(f"/api/classrooms/{cid}/sessions/{sid}/end", headers=ORIGIN)
    assert send(prof, cid, sid, body="끝남").status_code == 409
    assert items(world, sid) == []


def test_a_retry_after_the_class_ended_gets_the_stored_item(world):
    # 보낸 직후 수업이 끝났고, 응답을 못 받은 화면이 다시 보냈다: 이미 저장된 그 항목을 돌려준다
    prof, cid, sid, _ = live(world)
    first = send(prof, cid, sid, body="막 보냄", key="late")
    prof.post(f"/api/classrooms/{cid}/sessions/{sid}/end", headers=ORIGIN)
    again = send(prof, cid, sid, body="막 보냄", key="late")
    assert again.status_code == 201 and again.json()["item"] == first.json()["item"]


def test_sending_is_recorded_then_published(world):
    prof, cid, sid, _ = live(world)
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    res = send(prof, cid, sid, body="공지")
    item = res.json()["item"]
    assert recording.published == [
        (f"class:{cid}", {"type": "item.created", "session_id": sid,
                          "item": {"id": item["id"], "body": "공지", "url": None, "created_at": item["created_at"]},
                          "version": 2}, 2),
    ]  # 학생에게 갈 항목 그대로(거둔 시각은 없다). 발행하는 순간 DB에는 이미 그 버전이 있다
    assert item_events(world, cid) == [("item_sent", "professor", 101, {"session_id": sid, "item_id": item["id"]})]


def test_a_failed_publish_keeps_the_item(world):
    prof, cid, sid, _ = live(world)

    class Broken:
        def publish(self, room, event):
            raise RuntimeError("방이 고장났다")

    world.app.state.bus = Broken()
    assert send(prof, cid, sid, body="그래도 저장").status_code == 201
    assert len(items(world, sid)) == 1


# --- 거두기 --------------------------------------------------------------------------------


def test_retract_hides_the_item_from_students_and_keeps_the_text(world):
    prof, cid, sid, token = live(world)
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    item_id = send(prof, cid, sid, body="잘못 보냄").json()["item"]["id"]
    recording = RecordingBus(world.settings.database_path)
    world.app.state.bus = recording
    world.clock.advance(minutes=1)
    res = retract(prof, cid, sid, item_id)
    assert res.status_code == 200
    now = world.clock.now().isoformat()
    assert res.json()["item"]["retracted_at"] == now and res.json()["version"] == 3
    (row,) = items(world, sid)
    assert row["body"] == "잘못 보냄" and row["retracted_at"] == now  # 원문은 남는다(C6)
    assert recording.published == [
        (f"class:{cid}", {"type": "item.retracted", "session_id": sid, "item_id": item_id, "version": 3}, 3)
    ]
    assert student.get(f"/api/class/{cid}/sessions/{sid}/live").json()["items"] == []
    assert item_events(world, cid)[-1] == ("item_retracted", "professor", 101, {"session_id": sid, "item_id": item_id})


def test_retracting_twice_keeps_the_first_time_and_there_is_no_undo(world):
    prof, cid, sid, _ = live(world)
    item_id = send(prof, cid, sid, body="x").json()["item"]["id"]
    first = retract(prof, cid, sid, item_id).json()
    world.clock.advance(minutes=5)
    again = retract(prof, cid, sid, item_id)
    assert again.status_code == 200 and again.json() == first
    assert [e[0] for e in item_events(world, cid)] == ["item_sent", "item_retracted"]
    # 같은 글을 같은 키로 다시 보내도 거둔 항목이 되살아나지 않는다
    assert send(prof, cid, sid, body="x", key="k1").json()["item"]["retracted_at"] is not None


def test_items_can_be_retracted_after_the_class(world):
    prof, cid, sid, _ = live(world)
    item_id = send(prof, cid, sid, body="x").json()["item"]["id"]
    prof.post(f"/api/classrooms/{cid}/sessions/{sid}/end", headers=ORIGIN)
    assert retract(prof, cid, sid, item_id).status_code == 200


def test_an_item_of_another_session_or_classroom_is_not_found(world):
    prof, cid, sid, _ = live(world)
    item_id = send(prof, cid, sid, body="x").json()["item"]["id"]
    other_sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "2회차"}, headers=ORIGIN).json()["id"]
    _, other_cid, other_class_sid, _, _ = classroom_with_deck(world, name="다른")
    for c, s in ((cid, other_sid), (other_cid, other_class_sid), (cid, 9999)):
        res = retract(prof, c, s, item_id)
        assert res.status_code == 404 and res.json()["detail"] == "찾을 수 없는 항목입니다."
    assert retract(prof, cid, sid, 9999).status_code == 404
    assert items(world, sid)[0]["retracted_at"] is None


# --- 권한 -----------------------------------------------------------------------------------


def test_only_the_owner_sends_and_retracts(world):
    prof, cid, sid, token = live(world)
    item_id = send(prof, cid, sid, body="x").json()["item"]["id"]
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    for client, status in ((world.client("lee"), 403), (world.client(), 401), (student, 401)):
        assert send(client, cid, sid, body="y", key="z").status_code == status
        assert retract(client, cid, sid, item_id).status_code == status
    assert len(items(world, sid)) == 1 and items(world, sid)[0]["retracted_at"] is None


def test_requests_from_another_site_are_refused(world):
    prof, cid, sid, _ = live(world)
    assert send(prof, cid, sid, body="x", headers={"Origin": "https://evil.example"}).status_code == 403
    assert items(world, sid) == []
