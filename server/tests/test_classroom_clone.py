"""AC11, AC12의 서버 쪽: 분반 만들기·새 학기로 복제. 이름과 분반만 가져오고 나머지는 새로 시작한다."""

import secrets

from conftest import ORIGIN

NOW = "2026-03-01T09:00:00+00:00"


def create(client, name="웹 프로그래밍", section="월수반"):
    return client.post("/api/classrooms", json={"name": name, "section_name": section}, headers=ORIGIN).json()


def clone(client, source_id, **body):
    return client.post(f"/api/classrooms/{source_id}/clone", json=body, headers=ORIGIN)


def fill_source_with_data(world, classroom_id):
    """원본에 명단, 입장 요청, 멤버십, 챌린지, 이벤트를 채운다. 복제가 이 중 무엇도 가져오면 안 된다."""
    db = world.db()
    roster_ids = []
    for i in range(3):
        cur = db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at) VALUES (?, ?, '학생', ?, ?)",
            (classroom_id, f"s{i}", f"s{i}@x.kr", NOW),
        )
        roster_ids.append(cur.lastrowid)
    db.execute(
        "INSERT INTO join_requests(classroom_id, email_norm, name, student_no, created_at) VALUES (?, 'new@x.kr', '새', '9', ?)",
        (classroom_id, NOW),
    )
    membership = db.execute(
        "INSERT INTO memberships(classroom_id, nickname, created_at) VALUES (?, '용감한 수달', ?)",
        (classroom_id, NOW),
    ).lastrowid
    account = db.execute("INSERT INTO accounts(email_norm, created_at) VALUES ('s0@x.kr', ?)", (NOW,)).lastrowid
    db.execute(
        "INSERT INTO member_identities(membership_id, classroom_id, account_id, roster_entry_id) VALUES (?, ?, ?, ?)",
        (membership, classroom_id, account, roster_ids[0]),
    )
    device = db.execute("INSERT INTO devices(token_hash, first_seen_at) VALUES ('d', ?)", (NOW,)).lastrowid
    db.execute(
        "INSERT INTO login_challenges(classroom_id, email_norm, device_id, nonce, created_at, expires_at) "
        "VALUES (?, 's0@x.kr', ?, 'n', ?, ?)",
        (classroom_id, device, NOW, NOW),
    )
    db.execute(
        "INSERT INTO events(classroom_id, type, actor_kind, payload, created_at) VALUES (?, 'x', 'system', '{}', ?)",
        (classroom_id, NOW),
    )
    db.execute(
        "INSERT INTO mail_outbox(classroom_id, kind, to_email, created_at) VALUES (?, 'code', 's0@x.kr', ?)",
        (classroom_id, NOW),
    )


SCOPED_TABLES = [
    "roster_entries", "join_requests", "memberships", "member_identities",
    "classroom_verifications", "login_challenges", "mail_outbox", "events",
]


def counts(db, classroom_id):
    return {t: db.execute(f"SELECT COUNT(*) FROM {t} WHERE classroom_id = ?", (classroom_id,)).fetchone()[0]
            for t in SCOPED_TABLES}


# --- AC11: 복제 -------------------------------------------------------------------


def test_cloning_creates_a_new_active_classroom_owned_by_the_caller(world):
    kim = world.client("kim")
    source = create(kim)
    res = clone(kim, source["id"], name="웹 프로그래밍", section_name="화목반")
    assert res.status_code == 201
    body = res.json()
    assert body["id"] != source["id"]
    assert body["name"] == "웹 프로그래밍" and body["section_name"] == "화목반"
    assert body["status"] == "active" and body["student_count"] == 0
    row = world.db().execute("SELECT * FROM classrooms WHERE id = ?", (body["id"],)).fetchone()
    assert row["owner_github_id"] == 101
    assert row["source_classroom_id"] == source["id"]  # 어느 강좌에서 복제했는지 남긴다


def test_the_form_values_win_so_the_professor_can_edit_before_creating(world):
    kim = world.client("kim")
    source = create(kim, "웹 프로그래밍", "월수반")
    body = clone(kim, source["id"], name="  웹 프로그래밍 (2학기)  ", section_name="  ").json()
    assert body["name"] == "웹 프로그래밍 (2학기)"  # 다듬는다
    assert body["section_name"] is None  # 분반을 비우면 분반 없이


def test_omitted_fields_default_to_the_original_name_and_section(world):
    kim = world.client("kim")
    source = create(kim, "자료구조", "수요반")
    body = clone(kim, source["id"]).json()
    assert body["name"] == "자료구조" and body["section_name"] == "수요반"


def test_a_cloned_classroom_appears_first_in_the_active_list(world):
    kim = world.client("kim")
    source = create(kim, "원본")
    world.clock.advance(minutes=1)
    clone(kim, source["id"], name="복제본")
    listing = kim.get("/api/classrooms").json()
    assert [c["name"] for c in listing["classrooms"]] == ["복제본", "원본"]
    assert listing["counts"] == {"active": 2, "archived": 0}


def test_an_archived_classroom_can_be_cloned_for_a_new_term(world):
    kim = world.client("kim")
    source = create(kim, "지난 학기")
    world.db().execute("UPDATE classrooms SET status='archived', archived_at=? WHERE id=?", (NOW, source["id"]))
    res = clone(kim, source["id"], name="새 학기")
    assert res.status_code == 201 and res.json()["status"] == "active"
    row = world.db().execute("SELECT status FROM classrooms WHERE id = ?", (source["id"],)).fetchone()
    assert row["status"] == "archived"  # 원본은 그대로 보관됨


# --- AC12: 별개이고 비어 있다 --------------------------------------------------------


def test_the_clone_starts_with_no_roster_requests_members_or_records(world):
    kim = world.client("kim")
    source = create(kim)
    fill_source_with_data(world, source["id"])
    new_id = clone(kim, source["id"]).json()["id"]
    db = world.db()
    assert counts(db, new_id) == dict.fromkeys(SCOPED_TABLES, 0)
    assert kim.get(f"/api/classrooms/{new_id}").json()["student_count"] == 0


def test_the_original_is_left_untouched(world):
    kim = world.client("kim")
    source = create(kim, "원본", "월수반")
    fill_source_with_data(world, source["id"])
    db = world.db()
    before_counts = counts(db, source["id"])
    before_row = dict(db.execute("SELECT * FROM classrooms WHERE id = ?", (source["id"],)).fetchone())
    assert clone(kim, source["id"], name="복제본").status_code == 201  # 복제가 실제로 일어났다
    assert counts(db, source["id"]) == before_counts
    assert dict(db.execute("SELECT * FROM classrooms WHERE id = ?", (source["id"],)).fetchone()) == before_row
    assert before_counts["roster_entries"] == 3  # 채워 둔 데이터가 실제로 있었다


def test_the_clone_gets_its_own_invite_token(world):
    kim = world.client("kim")
    source = create(kim)
    new_id = clone(kim, source["id"]).json()["id"]
    rows = {r["id"]: r["invite_token"] for r in world.db().execute("SELECT id, invite_token FROM classrooms")}
    assert rows[new_id] != rows[source["id"]]
    assert len(rows[new_id]) >= 20 and len(set(rows.values())) == 2


def test_a_token_collision_is_retried_for_clones_too(world, monkeypatch):
    kim = world.client("kim")
    source = create(kim)
    existing = world.db().execute("SELECT invite_token FROM classrooms").fetchone()["invite_token"]
    answers = iter([existing, "fresh-clone-token-12345678"])
    monkeypatch.setattr(secrets, "token_urlsafe", lambda *_: next(answers))
    res = clone(kim, source["id"], name="복제본")
    assert res.status_code == 201
    tokens = {r["invite_token"] for r in world.db().execute("SELECT invite_token FROM classrooms")}
    assert "fresh-clone-token-12345678" in tokens


# --- 검증 ----------------------------------------------------------------------------


def test_blank_or_too_long_names_are_refused_and_nothing_is_created(world):
    kim = world.client("kim")
    source = create(kim)
    for bad in ["", "   "]:
        res = clone(kim, source["id"], name=bad)
        assert res.status_code == 422 and res.json()["detail"] == "강좌 이름을 입력해 주세요."
    assert "100자 이하" in clone(kim, source["id"], name="가" * 101).json()["detail"]
    assert "50자 이하" in clone(kim, source["id"], name="정상", section_name="나" * 51).json()["detail"]
    assert world.db().execute("SELECT COUNT(*) FROM classrooms").fetchone()[0] == 1


# --- 권한 (AC8과 같은 규칙) ---------------------------------------------------------------


def test_another_professor_cannot_clone_and_nothing_is_created(world):
    kim, lee = world.client("kim"), world.client("lee")
    source = create(kim, "김교수 비밀 강좌")
    res = clone(lee, source["id"], name="훔쳐 온 강좌")
    assert res.status_code == 403
    assert res.json()["detail"] == "이 강좌를 볼 권한이 없습니다."
    assert world.db().execute("SELECT COUNT(*) FROM classrooms").fetchone()[0] == 1
    assert lee.get("/api/classrooms").json()["classrooms"] == []


def test_unknown_classroom_is_404_and_visitors_get_401(world):
    assert clone(world.client("kim"), 9999).status_code == 404
    assert clone(world.client(), 1).status_code == 401  # 있는지 없는지 알려 주지 않는다


def test_cloning_needs_the_service_origin(world):
    kim = world.client("kim")
    source = create(kim)
    assert kim.post(f"/api/classrooms/{source['id']}/clone", json={"name": "x"}).status_code == 403
