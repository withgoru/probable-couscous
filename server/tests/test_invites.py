"""AC21, AC22의 서버 쪽: 초대 링크 보기와 다시 만들기, 그리고 토큰을 강좌로 바꾸는 규칙(학생 입장이 쓴다)."""

import secrets
from dataclasses import replace

from conftest import BASE, ORIGIN

from app.invites import resolve_token


def create(client, name="웹"):
    return client.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]


def invite(client, cid):
    return client.get(f"/api/classrooms/{cid}/invite")


def regenerate(client, cid):
    return client.post(f"/api/classrooms/{cid}/invite/regenerate", headers=ORIGIN)


def stored_token(world, cid):
    return world.db().execute("SELECT invite_token FROM classrooms WHERE id = ?", (cid,)).fetchone()[0]


# --- AC21: 링크 보기 ---------------------------------------------------------------


def test_the_owner_sees_the_invite_link_of_the_classroom(world):
    kim = world.client("kim")
    cid = create(kim)
    res = invite(kim, cid)
    assert res.status_code == 200
    body = res.json()
    token = stored_token(world, cid)
    assert body == {"token": token, "url": f"{BASE}/join/{token}"}
    assert len(token) >= 20  # 128비트 난수


def test_viewing_does_not_change_the_link(world):
    kim = world.client("kim")
    cid = create(kim)
    assert invite(kim, cid).json() == invite(kim, cid).json()


def test_each_classroom_has_its_own_link(world):
    kim = world.client("kim")
    a, b = create(kim, "웹"), create(kim, "DB")
    assert invite(kim, a).json()["url"] != invite(kim, b).json()["url"]


def test_the_link_uses_the_service_address_without_double_slashes(world):
    world.app.state.settings = replace(world.settings, base_url=BASE + "/")  # 끝의 /가 있어도
    kim = world.client("kim")
    cid = create(kim)
    assert invite(kim, cid).json()["url"].startswith(f"{BASE}/join/")


def test_the_link_is_not_cached(world):
    kim = world.client("kim")
    cid = create(kim)
    assert invite(kim, cid).headers["cache-control"] == "no-store"
    assert regenerate(kim, cid).headers["cache-control"] == "no-store"


# --- AC22: 다시 만들기 ---------------------------------------------------------------


def test_regenerating_gives_a_new_link_and_the_old_token_stops_working(world):
    kim = world.client("kim")
    cid = create(kim)
    old = invite(kim, cid).json()["token"]
    db = world.db()
    assert resolve_token(db, old) is not None  # 만들 때는 열린다

    res = regenerate(kim, cid)
    assert res.status_code == 200
    new = res.json()
    assert new["token"] != old and new["url"] == f"{BASE}/join/{new['token']}"
    assert invite(kim, cid).json() == new  # 이제 보이는 링크는 새 것이다
    assert resolve_token(db, old) is None  # 이전 링크는 폐기
    assert resolve_token(db, new["token"]).id == cid


def test_a_revoked_token_and_a_made_up_token_look_the_same(world):
    kim = world.client("kim")
    cid = create(kim)
    old = invite(kim, cid).json()["token"]
    regenerate(kim, cid)
    db = world.db()
    assert resolve_token(db, old) == resolve_token(db, "never-existed-token-0000") is None  # AC22: 강좌 존재를 알려 주지 않는다


def test_regenerating_twice_revokes_every_earlier_link(world):
    kim = world.client("kim")
    cid = create(kim)
    tokens = [invite(kim, cid).json()["token"]]
    for _ in range(2):
        tokens.append(regenerate(kim, cid).json()["token"])
    assert len(set(tokens)) == 3
    db = world.db()
    assert [resolve_token(db, t) is not None for t in tokens] == [False, False, True]


def test_regenerating_leaves_the_roster_and_other_classrooms_alone(world):
    kim = world.client("kim")
    a, b = create(kim, "웹"), create(kim, "DB")
    kim.post(f"/api/classrooms/{a}/roster", json={"student_no": "1", "name": "김", "email": "a@x.kr"}, headers=ORIGIN)
    other = stored_token(world, b)
    regenerate(kim, a)
    assert stored_token(world, b) == other
    assert kim.get(f"/api/classrooms/{a}").json()["student_count"] == 1


def test_a_token_collision_is_retried(world, monkeypatch):
    kim = world.client("kim")
    a, b = create(kim, "웹"), create(kim, "DB")
    taken = stored_token(world, b)
    answers = iter([taken, taken, "fresh-unique-token-123456"])
    monkeypatch.setattr(secrets, "token_urlsafe", lambda *_: next(answers))
    assert regenerate(kim, a).json()["token"] == "fresh-unique-token-123456"


def test_the_new_link_is_a_fresh_random_value_not_derived_from_the_old(world):
    kim = world.client("kim")
    cid = create(kim)
    seen = {invite(kim, cid).json()["token"]}
    for _ in range(5):
        seen.add(regenerate(kim, cid).json()["token"])
    assert len(seen) == 6


# --- 권한 ----------------------------------------------------------------------------


def test_only_the_owner_can_view_or_regenerate(world):
    kim, lee = world.client("kim"), world.client("lee")
    cid = create(kim)
    before = stored_token(world, cid)
    assert invite(lee, cid).status_code == 403
    assert regenerate(lee, cid).status_code == 403
    assert invite(world.client(), cid).status_code == 401
    assert regenerate(world.client(), cid).status_code == 401
    assert invite(kim, 999).status_code == 404
    assert regenerate(kim, 999).status_code == 404
    assert stored_token(world, cid) == before
    assert before not in invite(lee, cid).text


def test_regenerating_needs_the_service_origin(world):
    kim = world.client("kim")
    cid = create(kim)
    before = stored_token(world, cid)
    res = kim.post(f"/api/classrooms/{cid}/invite/regenerate", headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert stored_token(world, cid) == before


def test_both_are_judged_as_classroom_manage_actions(world, monkeypatch):
    from app import authz

    kim = world.client("kim")
    cid = create(kim)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    invite(kim, cid)
    regenerate(kim, cid)
    assert calls == [authz.Action.CLASSROOM_MANAGE] * 2


def test_the_token_still_does_not_appear_in_list_or_detail(world):
    kim = world.client("kim")
    cid = create(kim)
    token = stored_token(world, cid)
    assert token not in kim.get("/api/classrooms").text
    assert token not in kim.get(f"/api/classrooms/{cid}").text
    assert token not in kim.get("/api/me/summary").text
