"""AC5~AC8의 서버 쪽: 강좌 만들기, 목록(진행 중/보관됨 개수), 조회, 소유자 확인."""

import secrets

from conftest import ORIGIN


def create(client, name="알고리즘", section=None, **extra):
    body = {"name": name, **({"section_name": section} if section is not None else {}), **extra}
    return client.post("/api/classrooms", json=body, headers=ORIGIN)


def names(res):
    return [c["name"] for c in res.json()["classrooms"]]


# --- AC5: 만들기 -----------------------------------------------------------------


def test_creating_a_classroom_returns_it_with_the_owner_and_an_invite_token(world):
    kim = world.client("kim")
    res = create(kim, "알고리즘", "월수반")
    assert res.status_code == 201
    body = res.json()
    assert body["name"] == "알고리즘" and body["section_name"] == "월수반"
    assert body["status"] == "active" and body["student_count"] == 0
    row = world.db().execute("SELECT * FROM classrooms WHERE id = ?", (body["id"],)).fetchone()
    assert row["owner_github_id"] == 101  # 로그인한 교수가 주인이다
    assert len(row["invite_token"]) >= 20  # 128비트 난수


def test_the_invite_token_is_not_exposed_in_list_or_detail(world):
    kim = world.client("kim")
    created = create(kim).json()
    assert "invite_token" not in created
    assert "invite_token" not in kim.get("/api/classrooms").json()["classrooms"][0]
    assert "invite_token" not in kim.get(f"/api/classrooms/{created['id']}").json()


def test_section_is_optional_and_names_are_trimmed(world):
    kim = world.client("kim")
    body = create(kim, "  알고리즘  ", "   ").json()
    assert body["name"] == "알고리즘" and body["section_name"] is None
    assert create(kim, "자료구조").json()["section_name"] is None


def test_every_classroom_gets_its_own_invite_token(world):
    kim = world.client("kim")
    for n in "ABC":
        create(kim, n)
    tokens = [r["invite_token"] for r in world.db().execute("SELECT invite_token FROM classrooms")]
    assert len(tokens) == 3 and len(set(tokens)) == 3


def test_a_token_collision_is_retried_instead_of_failing(world, monkeypatch):
    kim = world.client("kim")
    create(kim, "첫째")
    existing = world.db().execute("SELECT invite_token FROM classrooms").fetchone()["invite_token"]
    answers = iter([existing, existing, "fresh-unique-token-123456"])
    monkeypatch.setattr(secrets, "token_urlsafe", lambda *_: next(answers))
    res = create(kim, "둘째")
    assert res.status_code == 201
    tokens = {r["invite_token"] for r in world.db().execute("SELECT invite_token FROM classrooms")}
    assert "fresh-unique-token-123456" in tokens


# --- AC6: 이름이 비면 거부 -----------------------------------------------------------


def test_empty_or_blank_name_is_refused_with_the_ac6_message_and_nothing_is_created(world):
    kim = world.client("kim")
    for bad in ["", "   ", "\t\n"]:
        res = create(kim, bad)
        assert res.status_code == 422, repr(bad)
        assert res.json()["detail"] == "강좌 이름을 입력해 주세요."
    assert kim.post("/api/classrooms", json={}, headers=ORIGIN).json()["detail"] == "강좌 이름을 입력해 주세요."
    assert world.db().execute("SELECT COUNT(*) FROM classrooms").fetchone()[0] == 0


def test_too_long_names_say_the_limit(world):
    kim = world.client("kim")
    assert create(kim, "가" * 100).status_code == 201
    res = create(kim, "가" * 101)
    assert res.status_code == 422 and "100자 이하" in res.json()["detail"]
    res = create(kim, "정상", "나" * 51)
    assert res.status_code == 422 and "50자 이하" in res.json()["detail"]


def test_a_non_text_name_is_refused_not_crashed(world):
    kim = world.client("kim")
    assert create(kim, 123).status_code == 422  # type: ignore[arg-type]


def test_creating_needs_a_login_and_the_service_origin(world):
    assert create(world.client()).status_code == 401
    kim = world.client("kim")
    assert kim.post("/api/classrooms", json={"name": "x"}).status_code == 403  # Origin 없음


# --- AC7: 목록, 개수, 카드 정보 -------------------------------------------------------


def test_new_classroom_comes_first_in_the_list(world):
    kim = world.client("kim")
    create(kim, "첫째")
    world.clock.advance(minutes=1)
    create(kim, "둘째")
    world.clock.advance(minutes=1)
    create(kim, "셋째")
    assert names(kim.get("/api/classrooms")) == ["셋째", "둘째", "첫째"]


def test_classrooms_created_at_the_same_moment_still_have_a_stable_order(world):
    kim = world.client("kim")
    for n in ["가", "나", "다"]:
        create(kim, n)
    assert names(kim.get("/api/classrooms")) == ["다", "나", "가"]


def test_list_gives_card_fields_and_active_and_archived_counts(world):
    kim = world.client("kim")
    a = create(kim, "진행1", "월수반").json()["id"]
    b = create(kim, "진행2").json()["id"]
    c = create(kim, "보관됨").json()["id"]
    world.db().execute("UPDATE classrooms SET status='archived', archived_at='2026-03-01T09:00:00+00:00' WHERE id=?", (c,))
    body = kim.get("/api/classrooms").json()
    assert body["counts"] == {"active": 2, "archived": 1}
    by_id = {x["id"]: x for x in body["classrooms"]}
    assert set(by_id) == {a, b, c}
    assert by_id[a]["section_name"] == "월수반" and by_id[a]["status"] == "active"
    assert by_id[c]["status"] == "archived"
    assert {"id", "name", "section_name", "status", "student_count", "created_at"} <= set(by_id[a])


def test_empty_list_has_zero_counts(world):
    body = world.client("kim").get("/api/classrooms").json()
    assert body == {"classrooms": [], "counts": {"active": 0, "archived": 0}}


def test_student_count_counts_only_people_still_on_the_roster(world):
    kim = world.client("kim")
    cid = create(kim).json()["id"]
    db = world.db()
    for i, removed in enumerate([None, None, "2026-03-02T00:00:00+00:00"]):
        db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at, removed_at) "
            "VALUES (?, ?, '학생', ?, '2026-03-01T09:00:00+00:00', ?)",
            (cid, str(i), f"s{i}@x.kr", removed),
        )
    assert kim.get("/api/classrooms").json()["classrooms"][0]["student_count"] == 2
    assert kim.get(f"/api/classrooms/{cid}").json()["student_count"] == 2


def test_listing_needs_a_login(world):
    res = world.client().get("/api/classrooms")
    assert res.status_code == 401 and "로그인" in res.json()["detail"]


# --- AC8: 내 강좌만 -------------------------------------------------------------------


def test_each_professor_sees_only_their_own_classrooms(world):
    kim, lee = world.client("kim"), world.client("lee")
    create(kim, "김교수 강좌")
    create(lee, "이교수 강좌1")
    create(lee, "이교수 강좌2")
    assert names(kim.get("/api/classrooms")) == ["김교수 강좌"]
    assert sorted(names(lee.get("/api/classrooms"))) == ["이교수 강좌1", "이교수 강좌2"]
    assert kim.get("/api/classrooms").json()["counts"] == {"active": 1, "archived": 0}


def test_another_professors_classroom_cannot_be_opened_and_nothing_leaks(world):
    kim, lee = world.client("kim"), world.client("lee")
    kims = create(kim, "김교수 비밀 강좌").json()["id"]
    res = lee.get(f"/api/classrooms/{kims}")
    assert res.status_code == 403
    assert res.json()["detail"] == "이 강좌를 볼 권한이 없습니다."
    assert "비밀" not in res.text


def test_owner_opens_own_classroom_including_archived_ones(world):
    kim = world.client("kim")
    cid = create(kim, "내 강좌").json()["id"]
    assert kim.get(f"/api/classrooms/{cid}").json()["name"] == "내 강좌"
    world.db().execute("UPDATE classrooms SET status='archived' WHERE id=?", (cid,))
    res = kim.get(f"/api/classrooms/{cid}")
    assert res.status_code == 200 and res.json()["status"] == "archived"  # 기록 보기


def test_unknown_classroom_is_404_for_a_logged_in_professor_and_401_for_visitors(world):
    assert world.client("kim").get("/api/classrooms/9999").status_code == 404
    assert world.client().get("/api/classrooms/9999").status_code == 401  # 있는지 없는지 알려 주지 않는다


def test_logging_in_as_someone_else_does_not_expose_the_first_persons_classrooms(world):
    kim = world.client("kim")
    create(kim, "김교수 강좌")
    stranger_session = world.client("lee")
    assert names(stranger_session.get("/api/classrooms")) == []
