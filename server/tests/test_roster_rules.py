"""AC15, AC16, AC18의 규칙: 명단 한 줄의 검사(CSV 올리기와 한 명 추가가 같이 쓴다)."""

import pytest

from app.roster import ROSTER_LIMIT, RosterError, add_entry, clean_entry, normalize_email

NOW = "2026-03-01T09:00:00+00:00"


# --- 이메일 정규화 (AC16) -----------------------------------------------------


def test_email_ignores_surrounding_spaces_and_case():
    assert normalize_email("  Kim@Example.com ") == "kim@example.com"
    assert normalize_email("kim@example.com") == "kim@example.com"
    assert normalize_email("\tKIM@EXAMPLE.COM\n") == "kim@example.com"


# --- 한 줄의 검사 ---------------------------------------------------------------


def test_a_valid_line_is_cleaned():
    e = clean_entry("  20240001 ", " 김철수 ", " Kim@Example.com ")
    assert (e.student_no, e.name, e.email_norm) == ("20240001", "김철수", "kim@example.com")


@pytest.mark.parametrize(
    "args, field",
    [
        (("", "김", "a@b.kr"), "student_no"),
        (("   ", "김", "a@b.kr"), "student_no"),
        (("1", "", "a@b.kr"), "name"),
        (("1", "  ", "a@b.kr"), "name"),
        (("1", "김", ""), "email"),
        (("1", "김", "  "), "email"),
        ((None, "김", "a@b.kr"), "student_no"),
        (("1", 5, "a@b.kr"), "name"),
    ],
)
def test_blank_or_missing_fields_are_rejected_per_field(args, field):
    with pytest.raises(RosterError) as err:
        clean_entry(*args)
    assert err.value.reason == "blank" and err.value.field == field
    assert "입력해 주세요" in err.value.message


@pytest.mark.parametrize(
    "email", ["kim", "kim@", "@x.kr", "kim@x", "kim x@x.kr", "kim@@x.kr", "kim@x .kr", "a@b@c.kr", "kim@.kr", "kim@x."]
)
def test_malformed_email_is_rejected(email):
    with pytest.raises(RosterError) as err:
        clean_entry("1", "김", email)
    assert (err.value.reason, err.value.field) == ("email_format", "email")
    assert err.value.message == "이메일 형식을 확인해 주세요."


@pytest.mark.parametrize("args, field", [(("9" * 51, "김", "a@b.kr"), "student_no"), (("1", "김" * 101, "a@b.kr"), "name"),
                                          (("1", "김", "a" * 250 + "@b.kr"), "email")])
def test_too_long_values_are_rejected(args, field):
    with pytest.raises(RosterError) as err:
        clean_entry(*args)
    assert err.value.reason == "too_long" and err.value.field == field


def test_the_limits_themselves_are_allowed():
    clean_entry("9" * 50, "김" * 100, "a" * 244 + "@b.kr")  # 254자


# --- 저장: 중복과 200명 상한 ------------------------------------------------------


@pytest.fixture
def classroom(world):
    world.client("kim").post("/api/classrooms", json={"name": "웹"}, headers={"Origin": "http://localhost:8000"})
    return world.db(), 1


def entry(no="1", name="김", email="a@b.kr"):
    return clean_entry(no, name, email)


def test_added_entry_is_stored_with_normalized_email(classroom):
    db, cid = classroom
    entry_id = add_entry(db, cid, entry("1", "김", " A@B.kr "), NOW)
    row = db.execute("SELECT * FROM roster_entries WHERE id = ?", (entry_id,)).fetchone()
    assert (row["classroom_id"], row["student_no"], row["name"], row["email_norm"]) == (cid, "1", "김", "a@b.kr")
    assert row["created_at"] == NOW and row["removed_at"] is None


def test_same_email_with_other_case_and_spaces_is_a_duplicate(classroom):
    db, cid = classroom
    add_entry(db, cid, entry("1", "김", "Kim@Example.com "), NOW)
    with pytest.raises(RosterError) as err:
        add_entry(db, cid, entry("2", "이", "kim@example.com"), NOW)
    assert (err.value.reason, err.value.field) == ("duplicate_email", "email")
    assert db.execute("SELECT COUNT(*) FROM roster_entries").fetchone()[0] == 1


def test_same_student_no_is_a_duplicate(classroom):
    db, cid = classroom
    add_entry(db, cid, entry("1", "김", "a@b.kr"), NOW)
    with pytest.raises(RosterError) as err:
        add_entry(db, cid, entry("1", "이", "c@d.kr"), NOW)
    assert (err.value.reason, err.value.field) == ("duplicate_student_no", "student_no")


def test_duplicates_are_only_checked_inside_the_same_classroom(world):
    kim = world.client("kim")
    for n in ("웹", "DB"):
        kim.post("/api/classrooms", json={"name": n}, headers={"Origin": "http://localhost:8000"})
    db = world.db()
    add_entry(db, 1, entry(), NOW)
    add_entry(db, 2, entry(), NOW)  # 다른 강좌라 같은 학번·이메일이어도 된다
    assert db.execute("SELECT COUNT(*) FROM roster_entries").fetchone()[0] == 2


def test_a_removed_student_does_not_block_the_same_email_or_student_no(classroom):
    db, cid = classroom
    first = add_entry(db, cid, entry(), NOW)
    db.execute("UPDATE roster_entries SET removed_at = ? WHERE id = ?", (NOW, first))
    add_entry(db, cid, entry(), NOW)  # 빼기한 뒤 다시 추가할 수 있다
    assert db.execute("SELECT COUNT(*) FROM roster_entries WHERE removed_at IS NULL").fetchone()[0] == 1


def fill(db, cid, count, removed=0):
    for i in range(count + removed):
        db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at, removed_at) "
            "VALUES (?, ?, '학생', ?, ?, ?)",
            (cid, f"f{i}", f"f{i}@x.kr", NOW, NOW if i >= count else None),
        )


def test_the_200th_student_is_allowed_and_the_201st_is_refused_with_the_ac18_message(classroom):
    db, cid = classroom
    fill(db, cid, ROSTER_LIMIT - 1)
    add_entry(db, cid, entry("new1", "마지막", "last@x.kr"), NOW)  # 200명째
    with pytest.raises(RosterError) as err:
        add_entry(db, cid, entry("new2", "넘침", "over@x.kr"), NOW)  # 201명째
    assert err.value.reason == "roster_full" and err.value.field is None
    assert "200명까지 등록할 수 있습니다" in err.value.message
    assert db.execute("SELECT COUNT(*) FROM roster_entries").fetchone()[0] == 200


def test_removed_students_do_not_count_toward_the_limit(classroom):
    db, cid = classroom
    fill(db, cid, ROSTER_LIMIT - 1, removed=30)
    add_entry(db, cid, entry("new1", "마지막", "last@x.kr"), NOW)


def test_the_limit_is_counted_inside_the_write_transaction(classroom, monkeypatch):
    # 센 뒤 다른 쓰기가 끼어들 틈이 없어야 한다: 쓰기 잠금(BEGIN IMMEDIATE)을 잡은 안에서 센다
    from app import roster

    db, cid = classroom
    seen = []
    real = roster.live_count

    def spy(conn, classroom_id):
        seen.append(conn.in_transaction)
        return real(conn, classroom_id)

    monkeypatch.setattr(roster, "live_count", spy)
    add_entry(db, cid, entry(), NOW)
    assert seen == [True]


def test_a_failed_add_leaves_nothing_behind(classroom):
    db, cid = classroom
    add_entry(db, cid, entry("1", "김", "a@b.kr"), NOW)
    with pytest.raises(RosterError):
        add_entry(db, cid, entry("2", "이", "A@b.kr"), NOW)
    assert not db.in_transaction
    assert [r["student_no"] for r in db.execute("SELECT student_no FROM roster_entries")] == ["1"]
