"""AC13, AC14, AC18의 서버 쪽: CSV 올리기(POST /api/classrooms/{id}/roster/import).

본문은 CSV 파일 그대로(Content-Type: text/csv)다. 첫 줄은 제목, 열은 학번·이름·이메일 순서.
"""

from conftest import ORIGIN

NOW = "2026-03-01T09:00:00+00:00"
HEADER = "학번,이름,이메일\n"
UNREADABLE = "파일을 읽을 수 없습니다. UTF-8 CSV로 저장해 다시 올려 주세요."


def create(client, name="웹"):
    return client.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]


def upload(client, cid, data, headers=None):
    body = data.encode("utf-8") if isinstance(data, str) else data
    return client.post(
        f"/api/classrooms/{cid}/roster/import",
        content=body,
        headers={**ORIGIN, "Content-Type": "text/csv", **(headers or {})},
    )


def stored(world):
    return [
        (r["student_no"], r["name"], r["email_norm"])
        for r in world.db().execute("SELECT * FROM roster_entries WHERE removed_at IS NULL ORDER BY id")
    ]


def fill(world, cid, count):
    db = world.db()
    for i in range(count):
        db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at) VALUES (?, ?, '학생', ?, ?)",
            (cid, f"f{i}", f"f{i}@x.kr", NOW),
        )


# --- AC13: 정상 등록 ----------------------------------------------------------------


def test_a_valid_csv_adds_everyone_and_reports_the_counts(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, HEADER + "20240001,김철수,kim@x.kr\n20240002,이영희,lee@x.kr\n")
    assert res.status_code == 200
    assert res.json() == {"added": 2, "skipped": 0, "skipped_lines": []}
    assert stored(world) == [("20240001", "김철수", "kim@x.kr"), ("20240002", "이영희", "lee@x.kr")]
    assert kim.get(f"/api/classrooms/{cid}").json()["student_count"] == 2


def test_excel_style_files_work_bom_crlf_quotes_and_no_final_newline(world):
    kim = world.client("kim")
    cid = create(kim)
    data = "﻿학번,이름,이메일\r\n1,\"김, 철수\",Kim@X.kr\r\n2,이영희,lee@x.kr"
    assert upload(kim, cid, data).json()["added"] == 2
    assert stored(world)[0] == ("1", "김, 철수", "kim@x.kr")


def test_values_are_trimmed_and_emails_normalized(world):
    kim = world.client("kim")
    cid = create(kim)
    upload(kim, cid, HEADER + " 1 ,  김  , Kim@X.KR \n")
    assert stored(world) == [("1", "김", "kim@x.kr")]


def test_the_header_line_is_not_a_student_and_a_header_only_file_adds_nobody(world):
    kim = world.client("kim")
    cid = create(kim)
    assert upload(kim, cid, HEADER).json() == {"added": 0, "skipped": 0, "skipped_lines": []}
    assert stored(world) == []


def test_completely_empty_lines_are_ignored_not_counted_as_skipped(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, HEADER + "1,김,a@x.kr\n\n,,\n2,이,b@x.kr\n\n")
    assert res.json() == {"added": 2, "skipped": 0, "skipped_lines": []}


def test_a_file_without_a_title_line_is_refused_instead_of_losing_the_first_student(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, "1,김,a@x.kr\n2,이,b@x.kr\n")
    assert res.status_code == 422
    assert "첫 줄" in res.json()["detail"]["message"] and "제목" in res.json()["detail"]["message"]
    assert stored(world) == []


# --- AC14: 건너뛴 줄 ------------------------------------------------------------------


def test_bad_lines_are_skipped_with_line_number_and_reason_and_good_lines_are_added(world):
    kim = world.client("kim")
    cid = create(kim)
    data = (
        HEADER
        + "1,김,a@x.kr\n"  # 2줄: 정상
        + "2,이,not-an-email\n"  # 3줄: 이메일 형식 오류
        + "3,,c@x.kr\n"  # 4줄: 빈 칸
        + "4,박,A@X.kr\n"  # 5줄: 이메일 중복(2줄과 같음)
        + "1,최,e@x.kr\n"  # 6줄: 학번 중복(2줄과 같음)
        + "5,정,f@x.kr\n"  # 7줄: 정상
    )
    res = upload(kim, cid, data)
    assert res.status_code == 200
    body = res.json()
    assert (body["added"], body["skipped"]) == (2, 4)
    assert [(s["line"], s["reason"]) for s in body["skipped_lines"]] == [
        (3, "이메일 형식 오류"),
        (4, "빈 칸"),
        (5, "이메일 중복"),
        (6, "학번 중복"),
    ]
    assert [s[0] for s in stored(world)] == ["1", "5"]


def test_duplicates_against_the_existing_roster_are_skipped_too(world):
    kim = world.client("kim")
    cid = create(kim)
    upload(kim, cid, HEADER + "1,김,a@x.kr\n")
    res = upload(kim, cid, HEADER + "2,이,A@x.kr\n1,박,b@x.kr\n3,최,c@x.kr\n")
    assert res.json()["added"] == 1
    assert [(s["line"], s["reason"]) for s in res.json()["skipped_lines"]] == [(2, "이메일 중복"), (3, "학번 중복")]


def test_a_removed_student_does_not_block_a_reupload(world):
    kim = world.client("kim")
    cid = create(kim)
    upload(kim, cid, HEADER + "1,김,a@x.kr\n")
    world.db().execute("UPDATE roster_entries SET removed_at = ?", (NOW,))
    assert upload(kim, cid, HEADER + "1,김,a@x.kr\n").json()["added"] == 1


def test_a_line_number_counts_physical_lines_even_after_a_multiline_quoted_cell(world):
    kim = world.client("kim")
    cid = create(kim)
    data = HEADER + '1,"김\n철수",a@x.kr\n2,이,bad\n'  # 2~3줄이 한 학생, 4줄이 오류
    res = upload(kim, cid, data)
    assert res.json()["added"] == 1
    assert res.json()["skipped_lines"][0]["line"] == 4


def test_missing_or_extra_columns_are_skipped_with_a_reason(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, HEADER + "1,김\n2,이,b@x.kr,여분\n3,박,c@x.kr,,\n")
    assert res.json()["added"] == 1  # 뒤쪽의 빈 열은 엑셀이 흔히 붙이므로 허용
    assert [(s["line"], s["reason"]) for s in res.json()["skipped_lines"]] == [(2, "열 개수 오류"), (3, "열 개수 오류")]
    assert stored(world) == [("3", "박", "c@x.kr")]


# --- 파일을 읽을 수 없을 때 --------------------------------------------------------------


def test_a_cp949_file_gets_the_utf8_guidance_and_nothing_is_added(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, (HEADER + "1,김철수,a@x.kr\n").encode("cp949"))
    assert res.status_code == 422
    assert res.json()["detail"] == {"field": None, "message": UNREADABLE}
    assert stored(world) == []


def test_binary_junk_and_nul_bytes_get_the_same_guidance(world):
    kim = world.client("kim")
    cid = create(kim)
    assert upload(kim, cid, b"\x89PNG\r\n\x1a\n\x00\x00").json()["detail"]["message"] == UNREADABLE
    assert upload(kim, cid, HEADER.encode() + b"1,\x00\xea,a@x.kr\n").json()["detail"]["message"] == UNREADABLE


def test_an_empty_upload_is_explained(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, b"")
    assert res.status_code == 422
    assert "비어" in res.json()["detail"]["message"]


# --- 1MB 상한 --------------------------------------------------------------------------


def test_a_file_over_1mb_is_refused_before_reading_it_all(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, b"a" * (1024 * 1024 + 1))
    assert res.status_code == 413
    assert "1MB" in res.json()["detail"]["message"]
    assert stored(world) == []


def test_the_limit_holds_even_without_a_content_length_header(world):
    kim = world.client("kim")
    cid = create(kim)

    def chunks():
        for _ in range(1100):
            yield b"a" * 1024

    res = kim.post(
        f"/api/classrooms/{cid}/roster/import", content=chunks(), headers={**ORIGIN, "Content-Type": "text/csv"}
    )
    assert res.status_code == 413


def test_a_file_of_exactly_1mb_is_not_refused_for_its_size(world):
    kim = world.client("kim")
    cid = create(kim)
    pad = "x" * (1024 * 1024 - len(HEADER.encode()) - len(",,\n"))
    res = upload(kim, cid, HEADER + pad + ",,\n")
    assert res.status_code != 413


# --- AC18: 200명 상한 ---------------------------------------------------------------------


def students(start, count):
    return "".join(f"n{i},학생,n{i}@x.kr\n" for i in range(start, start + count))


def test_exactly_200_are_allowed(world):
    kim = world.client("kim")
    cid = create(kim)
    fill(world, cid, 150)
    res = upload(kim, cid, HEADER + students(0, 50))
    assert res.json()["added"] == 50 and len(stored(world)) == 200


def test_over_200_adds_nobody_and_says_how_many_to_cut(world):
    kim = world.client("kim")
    cid = create(kim)
    fill(world, cid, 150)
    res = upload(kim, cid, HEADER + students(0, 53))
    assert res.status_code == 422
    assert res.json()["detail"] == {
        "field": None,
        "message": "명단은 200명까지 등록할 수 있습니다. 3명을 줄여 다시 올려 주세요.",
    }
    assert len(stored(world)) == 150  # 올바른 줄도 하나도 들어가지 않는다


def test_skipped_lines_do_not_count_toward_the_limit(world):
    kim = world.client("kim")
    cid = create(kim)
    fill(world, cid, 150)
    bad = "".join(f"b{i},학생,bad\n" for i in range(40))  # 형식 오류 40줄
    res = upload(kim, cid, HEADER + students(0, 50) + bad)
    assert res.status_code == 200 and (res.json()["added"], res.json()["skipped"]) == (50, 40)


def test_removed_students_do_not_count_toward_the_limit(world):
    kim = world.client("kim")
    cid = create(kim)
    fill(world, cid, 200)
    world.db().execute("UPDATE roster_entries SET removed_at = ? WHERE student_no < 'f1'", (NOW,))  # f0, f100~f199
    free = 200 - len(stored(world))
    assert upload(kim, cid, HEADER + students(0, free)).status_code == 200
    assert upload(kim, cid, HEADER + students(900, 1)).status_code == 422


# --- 권한과 원자성 ---------------------------------------------------------------------------


def test_another_professor_anonymous_and_missing_classroom(world):
    kim, lee = world.client("kim"), world.client("lee")
    cid = create(kim)
    data = HEADER + "1,김,a@x.kr\n"
    assert upload(lee, cid, data).status_code == 403
    assert upload(world.client(), cid, data).status_code == 401
    assert upload(kim, 999, data).status_code == 404
    assert stored(world) == []


def test_the_service_origin_is_required(world):
    kim = world.client("kim")
    cid = create(kim)
    res = kim.post(
        f"/api/classrooms/{cid}/roster/import",
        content=(HEADER + "1,김,a@x.kr\n").encode(),
        headers={"Origin": "https://evil.example", "Content-Type": "text/csv"},
    )
    assert res.status_code == 403


def test_the_import_is_judged_as_a_roster_manage_action(world, monkeypatch):
    from app import authz

    kim = world.client("kim")
    cid = create(kim)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    upload(kim, cid, HEADER)
    assert calls == [authz.Action.ROSTER_MANAGE]


def test_personal_data_stays_in_the_roster(world):
    kim = world.client("kim")
    cid = create(kim)
    upload(kim, cid, HEADER + "1,김철수,kim@x.kr\n")
    db = world.db()
    assert db.execute("SELECT COUNT(*) FROM memberships").fetchone()[0] == 0
    assert db.execute("SELECT COUNT(*) FROM events WHERE payload LIKE '%kim@x.kr%' OR payload LIKE '%김철수%'").fetchone()[0] == 0


def test_a_failing_insert_rolls_everything_back(world, monkeypatch):
    # 중간에 저장이 실패해도 일부만 들어가지 않는다
    from app import roster

    kim = world.client("kim")
    cid = create(kim)
    real = roster.CleanEntry
    calls = {"n": 0}
    original = roster._insert

    def flaky(db, classroom_id, entry, now):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return original(db, classroom_id, entry, now)

    monkeypatch.setattr(roster, "_insert", flaky)
    from fastapi.testclient import TestClient

    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    safe.cookies.update(kim.cookies)
    res = upload(safe, cid, HEADER + "1,김,a@x.kr\n2,이,b@x.kr\n")
    assert res.status_code == 500 and real is roster.CleanEntry
    assert stored(world) == []


def test_permission_is_checked_before_the_body_is_read(world):
    kim, lee = world.client("kim"), world.client("lee")
    cid = create(kim)
    big = b"a" * (1024 * 1024 + 1)
    assert upload(lee, cid, big).status_code == 403  # 413이 아니다: 권한 없는 사람의 본문은 읽지 않는다
    assert upload(world.client(), cid, big).status_code == 401


def test_a_nul_character_in_valid_utf8_is_also_unreadable(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, HEADER + "1,김\x00철수,a@x.kr\n")
    assert res.status_code == 422 and res.json()["detail"]["message"] == UNREADABLE
    assert stored(world) == []


def test_a_whitespace_only_file_is_explained_as_empty_not_as_a_missing_title(world):
    kim = world.client("kim")
    cid = create(kim)
    res = upload(kim, cid, "  \n\n \r\n")
    assert res.status_code == 422 and "비어" in res.json()["detail"]["message"]
