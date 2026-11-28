"""003 T012: 보관 6개월 정리에 출석 표 더하기(plan '보관 기간', C6, C11).

- 보관 6개월이 지난 강좌를 정리하면 그 강좌의 출석 창, 출석 기록, 수기 요청(사유), 처리가 지워진다.
- 다른 강좌의 출석 표는 그대로다.
- 지운 수가 `pii_purged` 기록에 들어간다. 두 번 돌려도 결과가 같다.
"""

import json
from datetime import UTC, datetime

import pytest
from attendance_world import act, entered_student, make_classroom, make_session
from conftest import ORIGIN
from test_attendance_check_in import check_in, code_at
from test_attendance_controls import control
from test_attendance_open import roster_ids
from test_attendance_requests import ask, decide
from test_attendance_table import change

from app import purge

DUE = datetime(2026, 9, 1, 9, tzinfo=UTC)  # 시계 시작 시각(보관 시각)에서 정확히 6개월
ATTENDANCE_TABLES = list(purge.ATTENDANCE_TABLES)  # 정리 코드와 같은 목록(표가 늘면 함께 늘어난다)
REASON = "버스가 늦게 와서 코드를 놓쳤습니다"


def run(world):
    db = world.db()
    try:
        return purge.purge_due(db, world.clock.now())
    finally:
        db.close()


def count(world, table, cid=None):
    with world.db() as db:
        if cid is None:
            return db.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return db.execute(f"SELECT COUNT(*) FROM {table} WHERE classroom_id = ?", (cid,)).fetchone()[0]


def attended_classroom(world, name="웹 프로그래밍"):
    """네 출석 표 모두에 행이 있는 강좌.

    1회차: 창 하나(시작), 학생 1 코드 출석, 학생 2 요청 승인(처리 + 승인 기록), 학생 3 요청 거절.
    2회차: 창 둘(시작 + 다시 받기), 교수가 학생 3을 직접 출석·결석으로 바꿈(기록 둘).
    """
    prof, cid = make_classroom(world, name=name)
    s1, s2, s3 = (entered_student(world, prof, cid, f"{name[:1]}{i}@x.kr") for i in (1, 2, 3))
    first = make_session(prof, cid, "1주차")
    assert act(prof, cid, first, "start").status_code == 200
    assert check_in(s1, cid, first, code_at(world, first, world.clock.now())).status_code == 200
    approved = ask(s2, cid, first, REASON)
    rejected = ask(s3, cid, first, REASON)
    assert approved.status_code == rejected.status_code == 201
    assert decide(prof, cid, approved.json()["id"], "approve").status_code == 200
    assert decide(prof, cid, rejected.json()["id"], "reject").status_code == 200
    assert act(prof, cid, first, "end").status_code == 200

    second = make_session(prof, cid, "2주차")
    assert act(prof, cid, second, "start").status_code == 200
    for what in ("close", "reopen"):  # 열린 창은 마감한 뒤에 다시 받는다
        assert control(prof, cid, second, what).status_code == 200, what
    s3_entry = roster_ids(prof, cid)[f"{name[:1]}3@x.kr"]
    assert change(prof, cid, second, s3_entry, "present").status_code == 200
    assert change(prof, cid, second, s3_entry, "absent").status_code == 200
    assert act(prof, cid, second, "end").status_code == 200
    return prof, cid


EXPECTED = {"attendance_windows": 3, "attendance_marks": 4, "attendance_requests": 2, "attendance_decisions": 2}


def archive(prof, cid):
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200


def test_the_fixture_fills_all_four_tables(world):
    _prof, cid = attended_classroom(world)
    assert {t: count(world, t, cid) for t in ATTENDANCE_TABLES} == EXPECTED


@pytest.mark.constitution
def test_c11_purging_a_due_classroom_deletes_its_attendance_rows_and_keeps_other_classrooms(world):
    prof, cid = attended_classroom(world, "웹 프로그래밍")
    _other_prof, other = attended_classroom(world, "앱 프로그래밍")
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    assert {t: count(world, t, cid) for t in ATTENDANCE_TABLES} == dict.fromkeys(ATTENDANCE_TABLES, 0)
    assert {t: count(world, t, other) for t in ATTENDANCE_TABLES} == EXPECTED  # 살아 있는 강좌는 그대로


@pytest.mark.constitution
def test_c11_the_request_reason_is_gone_after_the_purge(world):
    prof, cid = attended_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    db = world.db()
    try:
        assert REASON not in "\n".join(db.iterdump())
    finally:
        db.close()


def test_nothing_of_attendance_is_purged_before_six_months(world):
    prof, cid = attended_classroom(world)
    archive(prof, cid)
    world.clock.set(datetime(2026, 9, 1, 8, 59, 59, tzinfo=UTC))
    assert run(world) == []
    assert {t: count(world, t, cid) for t in ATTENDANCE_TABLES} == EXPECTED


def test_an_archived_classroom_not_yet_due_keeps_its_attendance(world):
    prof, cid = attended_classroom(world, "웹 프로그래밍")
    _other_prof, other = attended_classroom(world, "앱 프로그래밍")
    archive(prof, cid)
    world.clock.set(datetime(2026, 5, 1, tzinfo=UTC))
    archive(world.client("kim"), other)  # 두 달 늦게 보관했다(시간이 지나 다시 로그인)
    world.clock.set(DUE)
    run(world)
    assert {t: count(world, t, other) for t in ATTENDANCE_TABLES} == EXPECTED


@pytest.mark.constitution
def test_c6_the_deleted_attendance_counts_are_in_the_pii_purged_record(world):
    prof, cid = attended_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    (result,) = run(world)
    for table, n in EXPECTED.items():
        assert result["counts"][table] == n, table
    with world.db() as db:
        (payload,) = [json.loads(r["payload"]) for r in db.execute(
            "SELECT payload FROM events WHERE classroom_id = ? AND type = 'pii_purged'", (cid,)
        )]
    assert payload == result["counts"]
    assert REASON not in json.dumps(payload, ensure_ascii=False)


def test_a_classroom_without_attendance_records_zero_for_the_four_tables(world):
    prof, cid = make_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    (result,) = run(world)
    assert {t: result["counts"][t] for t in ATTENDANCE_TABLES} == dict.fromkeys(ATTENDANCE_TABLES, 0)


def test_running_twice_gives_the_same_result_and_records_once(world):
    prof, cid = attended_classroom(world)
    _other_prof, other = attended_classroom(world, "앱 프로그래밍")
    archive(prof, cid)
    world.clock.set(DUE)
    assert len(run(world)) == 1
    snapshot = {t: count(world, t) for t in ATTENDANCE_TABLES + ["events", "class_sessions", "memberships"]}
    world.clock.advance(days=1)
    assert run(world) == []
    assert {t: count(world, t) for t in snapshot} == snapshot
    with world.db() as db:
        assert db.execute("SELECT COUNT(*) FROM events WHERE type = 'pii_purged'").fetchone()[0] == 1
    assert {t: count(world, t, other) for t in ATTENDANCE_TABLES} == EXPECTED


def test_sessions_and_attendance_events_stay_after_the_purge(world):
    # 회차와 교수의 열기·마감 기록(events)은 개인정보가 아니라 남는다(C6)
    prof, cid = attended_classroom(world)
    with world.db() as db:
        before = db.execute(
            "SELECT COUNT(*) FROM events WHERE classroom_id = ? AND type LIKE 'attendance_%'", (cid,)
        ).fetchone()[0]
    assert before > 0
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    with world.db() as db:
        after = db.execute(
            "SELECT COUNT(*) FROM events WHERE classroom_id = ? AND type LIKE 'attendance_%'", (cid,)
        ).fetchone()[0]
    assert after == before
    assert count(world, "class_sessions", cid) == 2


def test_a_failure_halfway_keeps_the_attendance_rows(world, monkeypatch):
    prof, cid = attended_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(purge.events, "record_event", boom)
    with pytest.raises(RuntimeError):
        run(world)
    monkeypatch.undo()
    assert {t: count(world, t, cid) for t in ATTENDANCE_TABLES} == EXPECTED


def test_a_classroom_purged_before_attendance_was_added_is_purged_again_with_a_new_record(world, monkeypatch):
    # 출석 표가 생기기 전의 정리(T012 이전)가 이미 기록을 남긴 강좌도, 남은 출석 행을 지우고 그 수를 새로 기록한다
    prof, cid = attended_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    monkeypatch.setattr(purge, "ATTENDANCE_TABLES", ())  # 예전 정리: 출석 표를 모른다
    (old,) = run(world)
    assert not any(t in old["counts"] for t in ATTENDANCE_TABLES)
    monkeypatch.undo()
    assert {t: count(world, t, cid) for t in ATTENDANCE_TABLES} == EXPECTED
    world.clock.advance(days=1)
    (result,) = run(world)
    assert {t: result["counts"][t] for t in ATTENDANCE_TABLES} == EXPECTED
    assert {t: count(world, t, cid) for t in ATTENDANCE_TABLES} == dict.fromkeys(ATTENDANCE_TABLES, 0)
    with world.db() as db:
        assert db.execute(
            "SELECT COUNT(*) FROM events WHERE classroom_id = ? AND type = 'pii_purged'", (cid,)
        ).fetchone()[0] == 2


def test_no_attendance_can_be_written_into_a_purged_classroom(world):
    # 정리 뒤에는 출석 행이 다시 생기지 않는다. 이 안전은 purge.py가 아니라 권한(보관된 강좌)과 명단 확인에서 온다
    prof, cid = attended_classroom(world)
    with world.db() as db:
        first, second = [r["id"] for r in db.execute(
            "SELECT id FROM class_sessions WHERE classroom_id = ? ORDER BY sort_order, id", (cid,)
        )]
        request_id = db.execute("SELECT MIN(id) FROM attendance_requests WHERE classroom_id = ?", (cid,)).fetchone()[0]
    entry = roster_ids(prof, cid)["웹3@x.kr"]
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    prof = world.client("kim")  # 6개월이 지나 교수 로그인이 끝났다. 다시 로그인한다
    assert change(prof, cid, second, entry, "present").status_code == 404  # 명단이 지워졌다
    assert decide(prof, cid, request_id, "approve").status_code == 404  # 요청이 지워졌다
    assert act(prof, cid, first, "start").status_code == 409  # 보관된 강좌는 수업을 시작할 수 없다
    assert {t: count(world, t, cid) for t in ATTENDANCE_TABLES} == dict.fromkeys(ATTENDANCE_TABLES, 0)
    world.clock.advance(days=1)
    assert run(world) == []
