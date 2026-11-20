"""AC15, AC16, AC18의 서버 쪽: 학생 한 명 추가 API(POST /api/classrooms/{id}/roster)."""

from conftest import ORIGIN

NOW = "2026-03-01T09:00:00+00:00"


def create(client, name="웹"):
    return client.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]


def add(client, cid, student_no="20240001", name="김철수", email="kim@example.com"):
    return client.post(
        f"/api/classrooms/{cid}/roster",
        json={"student_no": student_no, "name": name, "email": email},
        headers=ORIGIN,
    )


def test_owner_adds_a_student_and_gets_the_entry_back(world):
    kim = world.client("kim")
    cid = create(kim)
    res = add(kim, cid, " 20240001 ", " 김철수 ", " Kim@Example.com ")
    assert res.status_code == 201
    body = res.json()
    assert body["student_no"] == "20240001" and body["name"] == "김철수" and body["email"] == "kim@example.com"
    assert isinstance(body["id"], int)
    assert "nickname" not in body  # C9
    row = world.db().execute("SELECT * FROM roster_entries").fetchone()
    assert row["classroom_id"] == cid and row["email_norm"] == "kim@example.com"


def test_the_added_student_shows_in_the_student_count(world):
    kim = world.client("kim")
    cid = create(kim)
    add(kim, cid)
    assert kim.get(f"/api/classrooms/{cid}").json()["student_count"] == 1


def test_a_duplicate_email_is_rejected_next_to_the_email_field(world):
    kim = world.client("kim")
    cid = create(kim)
    add(kim, cid, "1", "김", "Kim@Example.com ")
    res = add(kim, cid, "2", "이", "kim@example.com")
    assert res.status_code == 422
    assert res.json()["detail"] == {"field": "email", "message": "이미 명단에 있는 이메일입니다. 다른 이메일을 입력해 주세요."}
    assert world.db().execute("SELECT COUNT(*) FROM roster_entries").fetchone()[0] == 1


def test_a_duplicate_student_no_is_rejected_next_to_the_student_no_field(world):
    kim = world.client("kim")
    cid = create(kim)
    add(kim, cid, "1", "김", "a@x.kr")
    res = add(kim, cid, "1", "이", "b@x.kr")
    assert res.status_code == 422
    assert res.json()["detail"]["field"] == "student_no"


def test_each_invalid_field_is_reported_with_its_field(world):
    kim = world.client("kim")
    cid = create(kim)
    cases = [(("", "김", "a@x.kr"), "student_no"), (("1", "", "a@x.kr"), "name"),
             (("1", "김", ""), "email"), (("1", "김", "kim"), "email")]
    for args, field in cases:
        res = add(kim, cid, *args)
        assert res.status_code == 422 and res.json()["detail"]["field"] == field, args


def test_non_text_or_missing_fields_are_422_not_500(world):
    kim = world.client("kim")
    cid = create(kim)
    for body in [{}, {"student_no": 1, "name": "김", "email": "a@x.kr"}, {"student_no": "1", "name": None, "email": "a@x.kr"}]:
        res = kim.post(f"/api/classrooms/{cid}/roster", json=body, headers=ORIGIN)
        assert res.status_code == 422, body
        assert isinstance(res.json()["detail"]["message"], str)


def test_the_201st_student_is_refused_and_nothing_is_added(world):
    kim = world.client("kim")
    cid = create(kim)
    db = world.db()
    for i in range(200):
        db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at) VALUES (?, ?, '학생', ?, ?)",
            (cid, f"f{i}", f"f{i}@x.kr", NOW),
        )
    res = add(kim, cid, "new", "넘침", "over@x.kr")
    assert res.status_code == 422
    assert res.json()["detail"]["field"] is None and "200명까지 등록할 수 있습니다" in res.json()["detail"]["message"]
    assert db.execute("SELECT COUNT(*) FROM roster_entries").fetchone()[0] == 200


def test_another_professor_cannot_add_to_my_classroom(world):
    kim, lee = world.client("kim"), world.client("lee")
    cid = create(kim)
    res = add(lee, cid)
    assert res.status_code == 403
    assert world.db().execute("SELECT COUNT(*) FROM roster_entries").fetchone()[0] == 0


def test_anonymous_visitors_get_401_and_a_missing_classroom_404(world):
    cid = create(world.client("kim"))
    assert add(world.client(), cid).status_code == 401
    assert add(world.client("kim"), 999).status_code == 404


def test_adding_needs_the_service_origin(world):
    kim = world.client("kim")
    cid = create(kim)
    res = kim.post(f"/api/classrooms/{cid}/roster", json={"student_no": "1", "name": "김", "email": "a@x.kr"},
                   headers={"Origin": "https://evil.example"})
    assert res.status_code == 403


def test_nothing_but_the_roster_gets_the_personal_data(world):
    kim = world.client("kim")
    cid = create(kim)
    add(kim, cid, "20240001", "김철수", "kim@example.com")
    db = world.db()
    assert db.execute("SELECT COUNT(*) FROM memberships").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM events WHERE payload LIKE '%kim@example.com%' OR payload LIKE '%김철수%'").fetchone()[0] == 0


def test_adding_is_judged_as_a_roster_manage_action(world, monkeypatch):
    # 학생도 읽을 수 있는 classroom.read가 아니라 소유자 전용 roster.manage로 판단해야 한다
    from app import authz

    kim = world.client("kim")
    cid = create(kim)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    add(kim, cid)
    assert calls == [authz.Action.ROSTER_MANAGE]
