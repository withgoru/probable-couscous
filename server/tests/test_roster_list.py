"""AC17의 서버 쪽: 명단 조회(GET /api/classrooms/{id}/roster). 닉네임은 어디에도 나오지 않는다(C9)."""

import json

from conftest import ORIGIN

NOW = "2026-03-01T09:00:00+00:00"


def create(client, name="웹"):
    return client.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]


def add(client, cid, no, name, email):
    r = client.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)
    assert r.status_code == 201
    return r.json()["id"]


def roster(client, cid):
    return client.get(f"/api/classrooms/{cid}/roster")


def enter(world, cid, entry_id, nickname="용감한 수달"):
    """학생이 입장한 상태를 만든다: 멤버십(닉네임)과 명단을 member_identities로 잇는다."""
    db = world.db()
    m = db.execute("INSERT INTO memberships(classroom_id, nickname, created_at) VALUES (?, ?, ?)", (cid, nickname, NOW)).lastrowid
    a = db.execute("INSERT INTO accounts(email_norm, created_at) VALUES (?, ?)", (f"acc{entry_id}@x.kr", NOW)).lastrowid
    db.execute(
        "INSERT INTO member_identities(membership_id, classroom_id, account_id, roster_entry_id) VALUES (?, ?, ?, ?)",
        (m, cid, a, entry_id),
    )


def test_the_roster_lists_student_no_name_email_and_entry_status(world):
    kim = world.client("kim")
    cid = create(kim)
    a = add(kim, cid, "20240001", "김철수", "Kim@X.kr")
    add(kim, cid, "20240002", "이영희", "lee@x.kr")
    enter(world, cid, a)
    body = roster(kim, cid).json()
    assert body["count"] == 2 and body["limit"] == 200
    assert [(e["student_no"], e["name"], e["email"], e["entered"]) for e in body["entries"]] == [
        ("20240001", "김철수", "kim@x.kr", True),
        ("20240002", "이영희", "lee@x.kr", False),
    ]
    assert all(isinstance(e["id"], int) for e in body["entries"])


def test_no_nickname_appears_anywhere_in_the_response(world):
    kim = world.client("kim")
    cid = create(kim)
    a = add(kim, cid, "1", "김", "a@x.kr")
    enter(world, cid, a, nickname="유일한닉네임")
    res = roster(kim, cid)
    assert "유일한닉네임" not in res.text and "nickname" not in res.text.lower()
    assert set(res.json()["entries"][0]) == {"id", "student_no", "name", "email", "entered"}


def test_entered_is_per_classroom(world):
    kim = world.client("kim")
    c1, c2 = create(kim, "웹"), create(kim, "DB")
    a = add(kim, c1, "1", "김", "a@x.kr")
    add(kim, c2, "1", "김", "a@x.kr")
    enter(world, c1, a)
    assert roster(kim, c1).json()["entries"][0]["entered"] is True
    assert roster(kim, c2).json()["entries"][0]["entered"] is False


def test_removed_students_and_other_classrooms_are_not_listed(world):
    kim = world.client("kim")
    c1, c2 = create(kim, "웹"), create(kim, "DB")
    gone = add(kim, c1, "1", "빠짐", "gone@x.kr")
    add(kim, c1, "2", "남음", "stay@x.kr")
    add(kim, c2, "9", "다른강좌", "other@x.kr")
    world.db().execute("UPDATE roster_entries SET removed_at = ? WHERE id = ?", (NOW, gone))
    body = roster(kim, c1).json()
    assert [e["name"] for e in body["entries"]] == ["남음"] and body["count"] == 1


def test_an_empty_roster(world):
    kim = world.client("kim")
    assert roster(kim, create(kim)).json() == {"entries": [], "count": 0, "limit": 200}


def test_entries_are_in_the_order_they_were_added(world):
    kim = world.client("kim")
    cid = create(kim)
    for no in ("30", "10", "20"):
        add(kim, cid, no, f"학생{no}", f"s{no}@x.kr")
    assert [e["student_no"] for e in roster(kim, cid).json()["entries"]] == ["30", "10", "20"]


def test_only_the_owner_sees_the_roster_and_it_is_not_cached(world):
    kim, lee = world.client("kim"), world.client("lee")
    cid = create(kim)
    add(kim, cid, "1", "김", "a@x.kr")
    assert roster(lee, cid).status_code == 403
    assert roster(world.client(), cid).status_code == 401
    assert roster(kim, 999).status_code == 404
    assert "김" not in roster(lee, cid).text
    assert roster(kim, cid).headers["cache-control"] == "no-store"


def test_listing_is_judged_as_a_roster_manage_action(world, monkeypatch):
    from app import authz

    kim = world.client("kim")
    cid = create(kim)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    roster(kim, cid)
    assert calls == [authz.Action.ROSTER_MANAGE]
    json.dumps(calls[0].value)
