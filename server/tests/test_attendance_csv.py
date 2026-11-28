"""003 T011: 출석부 CSV 서버(AC24, AC25, AC26, C7, C8, C11).

- 형식: UTF-8 BOM, 줄 끝 CRLF, 머리 줄 "학번, 이름, 회차 이름…, 출석 횟수"(plan 'CSV').
- 한 번이라도 시작한 회차만 회차 순서대로 칸이 된다. 값은 출석/결석이고 수기 출석은 출석이다.
- 지금 명단의 학생만 담는다. 이메일이 없다.
- `=`·`+`·`-`·`@`·탭·CR로 시작하는 칸은 앞에 `'`를 붙인다(수식 주입 막기).
"""

import csv
import io
from urllib.parse import quote

import pytest
from attendance_world import act, enroll, entered_student, make_classroom, make_session
from conftest import ORIGIN
from test_attendance_check_in import check_in, class_of, code_at
from test_attendance_open import roster_ids
from test_attendance_table import change

NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."
BOM = b"\xef\xbb\xbf"


def download(client, cid):
    return client.get(f"/api/classrooms/{cid}/attendance.csv")


def rows(res):
    assert res.content.startswith(BOM)
    text = res.content[len(BOM):].decode("utf-8")
    return list(csv.reader(io.StringIO(text, newline="")))


def by_no(table):
    return {r[0]: r for r in table[1:]}


# --- 형식 -----------------------------------------------------------------------------------


def test_csv_is_utf8_with_bom_and_crlf(world):
    # AC24: 엑셀에서 한글이 깨지지 않는다
    prof, cid, _sid, _ = class_of(world)
    res = download(prof, cid)
    assert res.status_code == 200, res.text
    assert res.headers["content-type"] == "text/csv; charset=utf-8"
    assert res.headers["cache-control"] == "no-store"
    assert res.content.startswith(BOM)
    body = res.content[len(BOM):]
    assert body.count(b"\r\n") == 2 and body.endswith(b"\r\n")
    assert b"\n" not in body.replace(b"\r\n", b"")
    assert "학번,이름,1회차,출석 횟수".encode() in body


def test_one_row_per_student_and_one_column_per_started_session(world):
    # AC24: 한 번이라도 시작한 회차마다 한 칸(회차 순서), 값은 출석/결석, 마지막 칸은 출석 횟수. 수기도 출석이다
    prof, cid = make_classroom(world)
    s1 = entered_student(world, prof, cid, "s1@x.kr", name="김일")
    entered_student(world, prof, cid, "s2@x.kr", name="이이")
    first = make_session(prof, cid, "1주차")
    second = make_session(prof, cid, "2주차")
    make_session(prof, cid, "3주차")  # 시작하지 않은 회차는 칸이 없다
    act(prof, cid, first, "start")
    check_in(s1, cid, first, code_at(world, first, world.clock.now()))
    act(prof, cid, first, "end")
    act(prof, cid, second, "start")
    change(prof, cid, second, roster_ids(prof, cid)["s2@x.kr"], "present")

    assert rows(download(prof, cid)) == [
        ["학번", "이름", "1주차", "2주차", "출석 횟수"],
        ["s1", "김일", "출석", "결석", "1"],
        ["s2", "이이", "결석", "출석", "1"],
    ]


def test_columns_follow_session_order_not_start_order(world):
    prof, cid = make_classroom(world)
    enroll(prof, cid, "s1@x.kr", no="s1")
    first = make_session(prof, cid, "1주차")
    second = make_session(prof, cid, "2주차")
    act(prof, cid, second, "start")
    act(prof, cid, second, "end")
    act(prof, cid, first, "start")
    assert rows(download(prof, cid))[0] == ["학번", "이름", "1주차", "2주차", "출석 횟수"]


def test_columns_use_the_session_order_field(world):
    # 칸 순서는 회차 번호가 아니라 회차 순서(sort_order)다
    prof, cid = make_classroom(world)
    enroll(prof, cid, "s1@x.kr", no="s1")
    first = make_session(prof, cid, "1주차")
    second = make_session(prof, cid, "2주차")
    for sid in (first, second):
        act(prof, cid, sid, "start")
        act(prof, cid, sid, "end")
    with world.db() as db:
        db.execute("UPDATE class_sessions SET sort_order = 0 WHERE id = ?", (second,))
    assert rows(download(prof, cid))[0] == ["학번", "이름", "2주차", "1주차", "출석 횟수"]


def test_approved_request_counts_as_attended(world):
    from test_attendance_requests import ask, decide

    prof, cid, sid, (s1,) = class_of(world)
    decide(prof, cid, ask(s1, cid, sid).json()["id"], "approve")
    assert by_no(rows(download(prof, cid)))["s1"][2:] == ["출석", "1"]


def test_csv_is_read_in_one_snapshot(world, monkeypatch):
    # 회차·명단·기록을 한 시점에서 읽는다(T010 현황과 같다)
    from app import attendance_state

    prof, cid, _sid, _ = class_of(world)
    seen = []
    original = attendance_state.attendance_book

    def spy(db, classroom_id):
        seen.append(db.in_transaction)
        return original(db, classroom_id)

    monkeypatch.setattr(attendance_state, "attendance_book", spy)
    assert download(prof, cid).status_code == 200
    assert seen == [True]


def test_live_and_ended_sessions_both_count_as_started(world):
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert by_no(rows(download(prof, cid)))["s1"][2:] == ["출석", "1"]
    act(prof, cid, sid, "end")
    assert by_no(rows(download(prof, cid)))["s1"][2:] == ["출석", "1"]


def test_code_attendance_changed_to_absent_is_absent(world):
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    change(prof, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "absent")
    assert by_no(rows(download(prof, cid)))["s1"][2:] == ["결석", "0"]


def test_classroom_with_no_started_session_has_only_names(world):
    prof, cid = make_classroom(world)
    enroll(prof, cid, "s1@x.kr", no="s1", name="김일")
    make_session(prof, cid)
    assert rows(download(prof, cid)) == [["학번", "이름", "출석 횟수"], ["s1", "김일", "0"]]


def test_rows_follow_the_roster_order(world):
    prof, cid = make_classroom(world)
    for no in ("30", "4", "200"):
        enroll(prof, cid, f"{no}@x.kr", no=no)
    assert [r[0] for r in rows(download(prof, cid))[1:]] == ["30", "4", "200"]


# --- 담는 범위 ------------------------------------------------------------------------------


def test_only_current_roster_and_late_students_are_absent_before(world):
    # AC25: 지금 명단만. 학기 중에 들어온 학생은 그 전 회차가 결석. 빠진 학생은 보이지 않는다
    prof, cid, first, (s1, s2) = class_of(world, 2)
    check_in(s1, cid, first, code_at(world, first, world.clock.now()))
    check_in(s2, cid, first, code_at(world, first, world.clock.now()))
    act(prof, cid, first, "end")
    prof.delete(f"/api/classrooms/{cid}/roster/{roster_ids(prof, cid)['s2@x.kr']}", headers=ORIGIN)
    late = entered_student(world, prof, cid, "late@x.kr")
    second = make_session(prof, cid, "2회차")
    act(prof, cid, second, "start")
    check_in(late, cid, second, code_at(world, second, world.clock.now()))
    table = rows(download(prof, cid))
    assert [r[0] for r in table[1:]] == ["s1", "late"]
    assert by_no(table)["late"][2:] == ["결석", "출석", "1"]


def test_other_classrooms_are_not_mixed_in(world):
    # C5: 다른 강좌의 회차와 학생은 섞이지 않는다
    prof, cid, _sid, _ = class_of(world)
    other_prof, other_cid = make_classroom(world, owner="lee", name="다른 강좌")
    enroll(other_prof, other_cid, "o1@x.kr", no="o1")
    other_sid = make_session(other_prof, other_cid, "남의 회차")
    act(other_prof, other_cid, other_sid, "start")
    table = rows(download(prof, cid))
    assert table[0] == ["학번", "이름", "1회차", "출석 횟수"]
    assert [r[0] for r in table[1:]] == ["s1"]


@pytest.mark.constitution
def test_csv_has_no_email(world):
    # C7, C11: CSV에 이메일을 넣지 않는다(학번·이름은 교수가 올린 명단에서)
    prof, cid, _sid, _ = class_of(world, 2)
    text = download(prof, cid).content.decode("utf-8-sig")
    assert "@" not in text and "x.kr" not in text


# --- 보호 -----------------------------------------------------------------------------------


def _rename(world, cid, entry, name):
    with world.db() as db:
        db.execute("UPDATE roster_entries SET name = ? WHERE id = ? AND classroom_id = ?", (name, entry, cid))


@pytest.mark.parametrize("risky", ["=SUM(A1)", "+1", "-1", "@cmd", "\tx", "\rx"])
def test_cells_that_look_like_formulas_get_a_quote(world, risky):
    # plan: 수식 주입 막기. 이름·학번·회차 이름 모두
    prof, cid, sid, _ = class_of(world)
    _rename(world, cid, roster_ids(prof, cid)["s1@x.kr"], risky)
    with world.db() as db:
        db.execute("UPDATE class_sessions SET title = ? WHERE id = ?", ("=회차" + risky, sid))
    table = rows(download(prof, cid))
    assert table[0][2] == "'=회차" + risky
    assert table[1][1] == "'" + risky


def test_student_number_that_looks_like_a_formula_gets_a_quote(world):
    prof, cid = make_classroom(world)
    enroll(prof, cid, "s1@x.kr", no="-2024", name="김일")
    assert rows(download(prof, cid))[1][:2] == ["'-2024", "김일"]


def test_ordinary_cells_are_left_alone(world):
    prof, cid, _sid, _ = class_of(world)
    _rename(world, cid, roster_ids(prof, cid)["s1@x.kr"], "김 =철수, \"별명\"")
    assert rows(download(prof, cid))[1][1] == "김 =철수, \"별명\""


def test_file_name_is_utf8_and_names_the_classroom_and_section(world):
    # plan: Content-Disposition의 filename*이 UTF-8(강좌 이름·분반)
    prof, cid = make_classroom(world, name="웹 프로그래밍", section="A반")
    disposition = download(prof, cid).headers["content-disposition"]
    assert disposition == (
        "attachment; filename=\"attendance.csv\"; filename*=UTF-8''" + quote("웹 프로그래밍 A반 출석부.csv", safe="")
    )


def test_file_name_without_section(world):
    prof, cid = make_classroom(world, name="자료구조")
    disposition = download(prof, cid).headers["content-disposition"]
    assert disposition.endswith("filename*=UTF-8''" + quote("자료구조 출석부.csv", safe=""))


def test_file_name_drops_characters_that_break_file_names(world):
    prof, cid = make_classroom(world, name='웹/앱: "기초"\\?*<>|')
    disposition = download(prof, cid).headers["content-disposition"]
    assert disposition.endswith("filename*=UTF-8''" + quote('웹_앱_ _기초_______ 출석부.csv', safe=""))
    assert "\r" not in disposition and "\n" not in disposition


def _set_name(world, cid, name, section=None):
    with world.db() as db:
        db.execute("UPDATE classrooms SET name = ?, section_name = ? WHERE id = ?", (name, section, cid))


def test_file_name_replaces_control_and_direction_characters(world):
    # 줄바꿈·탭 같은 제어 문자와 글자 방향을 뒤집는 문자(U+202E)는 파일 이름을 속여 보이게 한다
    prof, cid = make_classroom(world)
    _set_name(world, cid, "a\tb\nc\u202ed")
    disposition = download(prof, cid).headers["content-disposition"]
    assert disposition.endswith("filename*=UTF-8''" + quote("a_b_c_d 출석부.csv", safe=""))


def test_long_file_name_is_cut(world):
    # 브라우저와 파일 시스템이 이름을 자르거나 버리지 않게 강좌 이름·분반을 60자로 줄인다
    prof, cid = make_classroom(world)
    _set_name(world, cid, "가" * 100, "나" * 50)
    disposition = download(prof, cid).headers["content-disposition"]
    assert disposition.endswith("filename*=UTF-8''" + quote("가" * 60 + " 출석부.csv", safe=""))


def test_classroom_gone_after_the_check_is_not_found(world, monkeypatch):
    from app import attendance

    prof, cid = make_classroom(world)
    real = attendance._file_name
    monkeypatch.setattr(attendance, "_file_name", lambda db, _cid: real(db, 999_999))
    res = download(prof, cid)
    assert (res.status_code, res.json()["detail"]) == (404, "찾을 수 없습니다.")


# --- 권한 -----------------------------------------------------------------------------------


def test_only_the_owner_downloads(world):
    # AC26
    _, cid, _sid, (s1,) = class_of(world)
    for client in (s1, world.client("lee")):
        res = download(client, cid)
        assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert download(world.client(), cid).status_code == 401


def test_archived_classroom_can_still_download(world):
    # 교수는 보관 6개월 정리 전에 CSV를 받아 둔다(spec 보관 기간 결정)
    prof, cid, sid, (s1,) = class_of(world)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    act(prof, cid, sid, "end")
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    assert by_no(rows(download(prof, cid)))["s1"][2:] == ["출석", "1"]


def test_missing_classroom_is_not_found(world):
    prof, _cid = make_classroom(world)
    assert download(prof, 999_999).status_code == 404
