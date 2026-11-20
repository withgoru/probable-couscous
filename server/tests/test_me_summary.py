"""AC49의 서버 쪽: 마이페이지 요약. @GitHub 계정, 진행 중·보관된 강좌 수, 진행 중 수강생 합계, 진행 중 강좌 목록."""

from conftest import ORIGIN

NOW = "2026-03-01T09:00:00+00:00"


def create(client, name, section=None):
    return client.post("/api/classrooms", json={"name": name, "section_name": section}, headers=ORIGIN).json()


def add_students(world, classroom_id, count, removed=0):
    db = world.db()
    for i in range(count + removed):
        db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at, removed_at) "
            "VALUES (?, ?, '학생', ?, ?, ?)",
            (classroom_id, f"s{i}", f"s{i}@x.kr", NOW, NOW if i >= count else None),
        )


def archive(world, classroom_id):
    world.db().execute(
        "UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ?", (NOW, classroom_id)
    )


def summary(client):
    return client.get("/api/me/summary")


def test_summary_has_the_account_counts_total_and_active_list(world):
    kim = world.client("kim")
    a = create(kim, "웹 프로그래밍", "월수반")
    b = create(kim, "데이터베이스")
    old = create(kim, "알고리즘")
    add_students(world, a["id"], 38)
    add_students(world, b["id"], 55)
    add_students(world, old["id"], 40)
    archive(world, old["id"])

    res = summary(kim)
    assert res.status_code == 200
    body = res.json()
    assert body["login"] == "kim" and body["github_id"] == 101
    assert body["counts"] == {"active": 2, "archived": 1}
    assert body["active_students"] == 93  # 보관된 강좌의 40명은 세지 않는다
    assert {c["name"]: (c["section_name"], c["student_count"]) for c in body["active_classrooms"]} == {
        "웹 프로그래밍": ("월수반", 38),
        "데이터베이스": (None, 55),
    }
    assert all({"id", "name", "section_name", "student_count", "status"} <= set(c) for c in body["active_classrooms"])


def test_removed_students_are_not_counted(world):
    kim = world.client("kim")
    a = create(kim, "웹")
    add_students(world, a["id"], 3, removed=2)
    body = summary(kim).json()
    assert body["active_students"] == 3
    assert body["active_classrooms"][0]["student_count"] == 3


def test_a_new_professor_sees_zeros(world):
    body = summary(world.client("kim")).json()
    assert body["counts"] == {"active": 0, "archived": 0}
    assert body["active_students"] == 0 and body["active_classrooms"] == []


def test_only_the_professors_own_classrooms_are_counted(world):
    kim, lee = world.client("kim"), world.client("lee")
    mine = create(kim, "내 강좌")
    theirs = create(lee, "남의 강좌")
    add_students(world, mine["id"], 2)
    add_students(world, theirs["id"], 30)
    body = summary(kim).json()
    assert body["counts"]["active"] == 1 and body["active_students"] == 2
    assert [c["name"] for c in body["active_classrooms"]] == ["내 강좌"]


def test_newest_active_classroom_comes_first(world):
    kim = world.client("kim")
    for n in ["첫째", "둘째", "셋째"]:
        create(kim, n)
    assert [c["name"] for c in summary(kim).json()["active_classrooms"]] == ["셋째", "둘째", "첫째"]


def test_login_requires_a_professor_session(world):
    assert world.client().get("/api/me/summary").status_code == 401


def test_summary_is_not_cached(world):
    assert summary(world.client("kim")).headers["cache-control"] == "no-store"
