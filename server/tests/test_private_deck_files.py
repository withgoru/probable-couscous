"""002 T033: 비공개 묶음 파일 막기(AC50, C8).

- 학생은 공개 묶음의 파일을 회차 상태와 관계없이 받는다(미리 보기, 다시 보기).
- 비공개 묶음은 그 회차가 진행 중이고 그 회차의 지금 묶음일 때만 받는다(수업 중 따라가기).
- 비공개로 바꾸면 그때부터 받지 못한다. 교수와 프로젝터는 늘 받는다.
- 거절은 없는 묶음과 같은 응답이다(어떤 묶음이 있는지 알리지 않는다).
"""

import shutil

import pytest
from conftest import ORIGIN
from test_deck_serving import FIXTURE, ZIP, asset_path, classroom_with_deck, enroll, entered_student

NOT_FOUND = "찾을 수 없습니다."  # 없거나 지운 묶음과 같은 응답


def with_student(world):
    prof, cid, sid, deck_id, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    return prof, cid, sid, deck_id, entered_student(world, token, "kim@x.kr")


def act(prof, cid, sid, what):
    assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/{what}", headers=ORIGIN).status_code == 200


def publish(prof, cid, sid, public=True):
    res = prof.put(f"/api/classrooms/{cid}/sessions/{sid}/deck/visibility", json={"public": public}, headers=ORIGIN)
    assert res.status_code == 200, res.text


def files(client, deck_id, asset):
    return [client.get(f"/decks/{deck_id}/index.html"), client.get(f"/decks/{deck_id}/"), client.get(asset)]


def refused(responses):
    return all(r.status_code == 404 and r.json()["detail"] == NOT_FOUND for r in responses)


def served(responses):
    return all(r.status_code == 200 for r in responses)


@pytest.mark.parametrize("state", ["scheduled", "live", "ended"])
def test_student_gets_a_public_deck_in_any_state(world, state):
    prof, cid, sid, deck_id, student = with_student(world)
    asset = asset_path(prof, deck_id)
    publish(prof, cid, sid)
    if state != "scheduled":
        act(prof, cid, sid, "start")
    if state == "ended":
        act(prof, cid, sid, "end")
    assert served(files(student, deck_id, asset))


def test_student_gets_a_private_deck_only_while_its_session_is_live(world):
    prof, cid, sid, deck_id, student = with_student(world)
    asset = asset_path(prof, deck_id)
    assert refused(files(student, deck_id, asset))  # 예정
    act(prof, cid, sid, "start")
    assert served(files(student, deck_id, asset))  # 수업 중 따라가기
    act(prof, cid, sid, "end")
    assert refused(files(student, deck_id, asset))  # 종료
    act(prof, cid, sid, "resume")
    assert served(files(student, deck_id, asset))  # 이어서 하기


def test_unpublishing_stops_serving_at_once(world):
    prof, cid, sid, deck_id, student = with_student(world)
    asset = asset_path(prof, deck_id)
    publish(prof, cid, sid)
    assert served(files(student, deck_id, asset))
    publish(prof, cid, sid, public=False)
    assert refused(files(student, deck_id, asset))


def test_a_private_deck_of_another_session_is_not_served_during_class(world):
    # 진행 중인 회차가 있어도, 그 회차의 묶음이 아니면 받지 못한다
    prof, cid, sid, _, student = with_student(world)
    other = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "2회차"}, headers=ORIGIN).json()["id"]
    res = prof.put(
        f"/api/classrooms/{cid}/sessions/{other}/deck", params={"filename": "b.zip"}, content=FIXTURE.read_bytes(), headers=ZIP
    )
    other_deck = res.json()["deck"]["id"]
    act(prof, cid, sid, "start")
    assert refused(files(student, other_deck, asset_path(prof, other_deck)))


def test_a_replaced_deck_is_not_served_even_if_it_was_public(world):
    prof, cid, sid, old_deck, student = with_student(world)
    old_asset = asset_path(prof, old_deck)
    publish(prof, cid, sid)
    res = prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "b.zip"}, content=FIXTURE.read_bytes(), headers=ZIP
    )
    new_deck = res.json()["deck"]["id"]
    assert student.get(f"/decks/{old_deck}/index.html").status_code == 404
    assert student.get(old_asset).status_code == 404
    assert refused(files(student, new_deck, asset_path(prof, new_deck)))  # 바꾼 묶음은 비공개


@pytest.mark.parametrize("state", ["scheduled", "ended"])
def test_owner_and_projector_always_get_a_private_deck(world, state):
    prof, cid, sid, deck_id, _ = with_student(world)
    assert prof.get(f"/api/classrooms/{cid}/sessions").json()["items"][0]["deck"]["public"] is False
    asset = asset_path(prof, deck_id)
    if state == "ended":
        act(prof, cid, sid, "start")
        act(prof, cid, sid, "end")
    assert served(files(prof, deck_id, asset))  # 프로젝터는 교수 로그인으로 연다(AC22)


def test_refusal_looks_like_a_missing_deck(world):
    # 비공개 묶음을 막는 응답과 없는 묶음의 응답이 같다(어떤 묶음이 있는지 알리지 않는다)
    _, _, _, deck_id, student = with_student(world)
    hidden = student.get(f"/decks/{deck_id}/index.html")
    missing = student.get(f"/decks/{deck_id + 999}/index.html")
    assert (hidden.status_code, hidden.json()) == (missing.status_code, missing.json())
    assert "public" not in hidden.text and "private" not in hidden.headers.get("cache-control", "")


def test_refusal_is_not_cached(world):
    _, _, _, deck_id, student = with_student(world)
    res = student.get(f"/decks/{deck_id}/index.html")
    assert res.status_code == 404
    assert res.headers["cache-control"] == "no-store"  # 이어서 하기나 공개 뒤에 막힌 응답이 남지 않게


def test_students_revalidate_every_file(world):
    # 수업 중에 받은 파일이 1년 캐시에 남아 수업 뒤 주소로 바로 열리지 않게, 학생에게는 해시 파일도 매번 확인한다
    prof, cid, sid, deck_id, student = with_student(world)
    asset = asset_path(prof, deck_id)
    act(prof, cid, sid, "start")
    res = student.get(asset)
    assert res.status_code == 200 and res.headers["cache-control"] == "private, no-cache"
    assert "etag" in res.headers or "last-modified" in res.headers  # 다시 확인은 304로 싸게 끝난다
    assert prof.get(asset).headers["cache-control"] == "private, max-age=31536000, immutable"  # 교수·프로젝터는 그대로


def test_refusal_comes_before_the_missing_files_check(world):
    # 파일이 없는 비공개 묶음도 학생에게는 없는 묶음과 같다(410이면 묶음이 있다는 것을 알린다)
    prof, cid, _, deck_id, student = with_student(world)
    shutil.rmtree(world.settings.deck_root / str(cid) / str(deck_id))
    res = student.get(f"/decks/{deck_id}/index.html")
    assert res.status_code == 404 and res.json()["detail"] == NOT_FOUND
    assert prof.get(f"/decks/{deck_id}/index.html").status_code == 410  # 교수에게는 열 수 없다고 알린다
