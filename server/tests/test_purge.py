"""C11, C6(T031): 보관 후 6개월이 지난 강좌의 개인정보 정리.

- 지우는 것: 그 강좌의 명단(roster_entries), 멤버십과 사람의 연결(member_identities), 입장 요청, 인증 챌린지, 메일 발송 대기,
  기기 인증 기록(classroom_verifications), 그리고 다른 강좌에서 쓰이지 않게 된 계정(accounts)과 그 계정의 기기 로그인.
- 남기는 것: 가명(memberships)과 기록(events). 다른 살아 있는(또는 아직 6개월이 안 된) 강좌에서 쓰는 계정.
- 같은 입력에 여러 번 돌려도 결과가 같고, 정리 결과는 `pii_purged` 기록으로 한 번 남는다.
"""

import json
import re
from datetime import UTC, datetime

import pytest
from conftest import ORIGIN

from app import purge

START = datetime(2026, 3, 1, 9, tzinfo=UTC)  # conftest의 시계 시작 시각
DUE = datetime(2026, 9, 1, 9, tzinfo=UTC)  # 보관(START)에서 정확히 6개월


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def enroll(prof, cid, no="1", name="김철수", email="kim@x.kr"):
    r = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def enter(world, token, email="kim@x.kr", student=None):
    """코드로 인증하고 입장까지 마친 기기. 같은 기기로 여러 강좌에 들어가려면 student를 넘긴다."""
    student = student or world.client()
    assert student.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"
    world.app.state.mail_worker.process_due()
    code = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    assert student.post(f"/api/join/{token}/code", json={"email": email, "code": code}, headers=ORIGIN).status_code == 200
    assert student.post(f"/api/join/{token}/enter", headers=ORIGIN).status_code == 200
    return student


def archive(prof, cid):
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200


def count(world, table, where="1=1", params=()):
    return world.db().execute(f"SELECT COUNT(*) FROM {table} WHERE {where}", params).fetchone()[0]


def run(world):
    db = world.db()
    try:
        return purge.purge_due(db, world.clock.now())
    finally:
        db.close()


def full_classroom(world, name="웹"):
    """명단, 입장한 학생, 입장 요청, 쓰지 않은 챌린지와 보내지 않은 메일이 있는 강좌."""
    prof, cid, token = classroom(world, name)
    enroll(prof, cid, "1", "김철수", "kim@x.kr")
    enroll(prof, cid, "2", "이영희", "lee@x.kr")
    student = enter(world, token)
    world.client().post(
        f"/api/join/{token}/request-access", json={"email": "new@x.kr", "name": "박민수", "student_no": "9"}, headers=ORIGIN
    )
    world.client().post(f"/api/join/{token}/email", json={"email": "lee@x.kr"}, headers=ORIGIN)  # 메일은 아직 보내지 않았다
    return prof, cid, token, student


PII_TABLES = ["roster_entries", "member_identities", "join_requests", "login_challenges", "mail_outbox", "classroom_verifications"]


# --- 6개월 뒤 정리 (C11) ---------------------------------------------------------------------------------------------


@pytest.mark.constitution
def test_c11_six_months_after_archiving_the_personal_data_is_gone_and_the_pseudonymous_record_stays(world):
    prof, cid, _token, _ = full_classroom(world)
    for table in PII_TABLES:
        assert count(world, table, "classroom_id = ?", (cid,)) > 0, table  # 지울 것이 있는 상태에서 시작한다
    nicknames = [r["nickname"] for r in world.db().execute("SELECT nickname FROM memberships WHERE classroom_id = ?", (cid,))]
    events_before = count(world, "events", "classroom_id = ?", (cid,))
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    for table in PII_TABLES:
        assert count(world, table, "classroom_id = ?", (cid,)) == 0, table
    assert count(world, "accounts") == 0 and count(world, "device_logins") == 0  # 이 강좌에만 쓰인 계정과 그 로그인
    assert [r["nickname"] for r in world.db().execute("SELECT nickname FROM memberships WHERE classroom_id = ?", (cid,))] == nicknames
    assert count(world, "events", "classroom_id = ?", (cid,)) == events_before + 2  # 보관 기록 + 정리 기록. 지운 것은 없다
    assert count(world, "classrooms", "id = ? AND status = 'archived'", (cid,)) == 1  # 강좌는 기록 보기를 위해 남는다


@pytest.mark.constitution
def test_c11_no_email_name_or_student_no_of_the_purged_classroom_is_left_anywhere(world):
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    db = world.db()
    dump = "\n".join(db.iterdump())
    for value in ("kim@x.kr", "lee@x.kr", "new@x.kr", "김철수", "이영희", "박민수"):
        assert value not in dump, value


def test_nothing_is_purged_before_six_months(world):
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    world.clock.set(datetime(2026, 9, 1, 8, 59, 59, tzinfo=UTC))
    assert run(world) == []
    for table in PII_TABLES:
        assert count(world, table, "classroom_id = ?", (cid,)) > 0, table
    assert count(world, "events", "type = 'pii_purged'") == 0


def test_a_classroom_that_is_still_active_is_never_purged(world):
    _prof, cid, _token, _ = full_classroom(world)
    world.clock.set(datetime(2030, 1, 1, tzinfo=UTC))
    assert run(world) == []
    assert count(world, "roster_entries", "classroom_id = ?", (cid,)) == 2


def test_six_months_are_calendar_months_even_at_the_end_of_a_month():
    # 8월 31일에 보관하면 2월 말일(윤년이면 29일)이 지나야 정리한다
    assert purge.months_before(datetime(2027, 2, 28, 12, tzinfo=UTC), 6) == datetime(2026, 8, 28, 12, tzinfo=UTC)
    assert purge.months_before(datetime(2028, 2, 29, tzinfo=UTC), 6) == datetime(2027, 8, 29, tzinfo=UTC)
    assert purge.months_before(datetime(2026, 9, 1, 9, tzinfo=UTC), 6) == START
    # 그 달에 같은 날이 없으면 말일로 맞춘다
    assert purge.months_before(datetime(2026, 8, 31, tzinfo=UTC), 6) == datetime(2026, 2, 28, tzinfo=UTC)
    assert purge.months_before(datetime(2028, 8, 31, tzinfo=UTC), 6) == datetime(2028, 2, 29, tzinfo=UTC)
    assert purge.months_before(datetime(2027, 3, 31, tzinfo=UTC), 6) == datetime(2026, 9, 30, tzinfo=UTC)


# --- 두 번 돌려도 같다 ---------------------------------------------------------------------------------------------------


def test_running_twice_gives_the_same_result_and_records_once(world):
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    first = run(world)
    snapshot = {t: count(world, t) for t in PII_TABLES + ["accounts", "device_logins", "memberships", "events"]}
    world.clock.advance(days=1)
    assert run(world) == []
    assert {t: count(world, t) for t in snapshot} == snapshot
    assert len(first) == 1 and count(world, "events", "type = 'pii_purged'") == 1


def test_data_added_after_the_purge_is_purged_on_the_next_run(world):
    # 보관된 강좌도 소유자는 명단에 넣을 수 있다(T025 결정). 6개월이 지난 강좌에 남지 않게 다음 실행이 지운다
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    prof = world.client("kim")  # 6개월이 지나 교수 로그인이 끝났다. 다시 로그인한다
    enroll(prof, cid, "7", "최지은", "choi@x.kr")
    world.clock.advance(days=1)
    (result,) = run(world)
    assert result["classroom_id"] == cid and result["counts"]["roster_entries"] == 1
    assert count(world, "roster_entries", "classroom_id = ?", (cid,)) == 0
    assert count(world, "events", "type = 'pii_purged'") == 2


# --- 다른 강좌의 계정은 남긴다 ---------------------------------------------------------------------------------------------


@pytest.mark.constitution
def test_c11_an_account_still_used_by_a_live_classroom_stays_with_its_login(world):
    prof, cid, _token, _ = full_classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    enroll(prof, cid2, "1", "김철수", "kim@x.kr")
    phone = enter(world, token2)  # 김철수는 다른 기기로 앱 강좌에도 입장했다
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    assert count(world, "accounts", "email_norm = 'kim@x.kr'") == 1  # 앱 강좌가 쓴다
    assert count(world, "accounts", "email_norm = 'lee@x.kr'") == 0  # 웹 강좌에만 있었다
    assert count(world, "member_identities", "classroom_id = ?", (cid2,)) == 1
    assert phone.get(f"/api/join/{token2}/me").json()["state"] == "entered"  # 다른 강좌의 입장은 그대로


def test_the_same_device_entered_in_both_keeps_the_other_classroom(world):
    prof, cid, _token, student = full_classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    enroll(prof, cid2, "1", "김철수", "kim@x.kr")
    assert student.post(f"/api/join/{token2}/enter", headers=ORIGIN).status_code == 200  # 같은 기기로 다른 강좌(AC37)
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    assert count(world, "classroom_verifications", "classroom_id = ?", (cid,)) == 0
    assert count(world, "classroom_verifications", "classroom_id = ?", (cid2,)) == 1
    assert student.get(f"/api/join/{token2}/me").json()["state"] == "entered"


def test_an_account_of_an_archived_classroom_not_yet_due_stays_until_that_one_is_due(world):
    prof, cid, _token, _ = full_classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    enroll(prof, cid2, "1", "김철수", "kim@x.kr")
    enter(world, token2)
    archive(prof, cid)
    world.clock.set(datetime(2026, 5, 1, tzinfo=UTC))
    archive(world.client("kim"), cid2)  # 두 달 늦게 보관했다(시간이 지나 다시 로그인)
    world.clock.set(DUE)
    run(world)
    assert count(world, "accounts", "email_norm = 'kim@x.kr'") == 1
    world.clock.set(datetime(2026, 11, 1, tzinfo=UTC))
    run(world)
    assert count(world, "accounts") == 0 and count(world, "device_logins") == 0


def test_other_classrooms_rows_are_untouched(world):
    prof, cid, _token, _ = full_classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    enroll(prof, cid2, "5", "정하늘", "jung@x.kr")
    world.client().post(f"/api/join/{token2}/email", json={"email": "jung@x.kr"}, headers=ORIGIN)
    before = {t: count(world, t, "classroom_id = ?", (cid2,)) for t in PII_TABLES}
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    assert {t: count(world, t, "classroom_id = ?", (cid2,)) for t in PII_TABLES} == before


# --- 기록 (C6) ----------------------------------------------------------------------------------------------------------


@pytest.mark.constitution
def test_c6_the_purge_is_recorded_as_a_system_event_with_counts_and_no_personal_data(world):
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    (result,) = run(world)
    (e,) = [dict(r) for r in world.db().execute("SELECT * FROM events WHERE type = 'pii_purged'")]
    assert (e["classroom_id"], e["actor_kind"], e["actor_ref"], e["subject_roster_entry_id"]) == (cid, "system", None, None)
    assert e["created_at"] == DUE.isoformat()
    payload = json.loads(e["payload"])
    assert payload == result["counts"]
    assert payload == {
        "roster_entries": 2,
        "member_identities": 1,
        "join_requests": 1,
        "login_challenges": 2,
        "mail_outbox": 2,
        "classroom_verifications": 1,
        "device_logins": 1,
        "accounts": 1,
    }
    assert "@" not in e["payload"]


def test_a_classroom_with_nothing_to_purge_is_still_recorded_once(world):
    prof, cid, _token = classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    run(world)
    run(world)
    (e,) = [dict(r) for r in world.db().execute("SELECT * FROM events WHERE type = 'pii_purged'")]
    assert all(v == 0 for v in json.loads(e["payload"]).values())


def test_a_failure_halfway_leaves_the_classroom_as_it_was(world, monkeypatch):
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    before = {t: count(world, t) for t in PII_TABLES + ["accounts", "device_logins", "events"]}
    real = purge.events.record_event

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(purge.events, "record_event", boom)
    with pytest.raises(RuntimeError):
        run(world)
    monkeypatch.setattr(purge.events, "record_event", real)
    assert {t: count(world, t) for t in before} == before  # 기록 없는 정리는 없다


# --- 하루 한 번 -----------------------------------------------------------------------------------------------------------


def test_the_job_runs_once_when_started_and_then_once_a_day(world):
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    job = world.app.state.purge_job
    world.clock.set(DUE)
    assert job.run_once() == [{"classroom_id": cid, "counts": job.last_result[0]["counts"]}]
    assert job.interval_seconds == 24 * 60 * 60


def test_the_job_thread_purges_without_being_asked_and_stops_cleanly(world):
    prof, cid, _token, _ = full_classroom(world)
    archive(prof, cid)
    world.clock.set(DUE)
    job = purge.PurgeJob(world.db, world.clock, interval_seconds=0.05)
    job.start()
    try:
        deadline = datetime.now(UTC).timestamp() + 5
        while count(world, "roster_entries", "classroom_id = ?", (cid,)) and datetime.now(UTC).timestamp() < deadline:
            job._stop.wait(0.02)
    finally:
        job.stop()
    assert count(world, "roster_entries", "classroom_id = ?", (cid,)) == 0
    assert not job.is_running()


def test_a_failing_run_does_not_kill_the_thread(world, monkeypatch):
    calls = []

    def flaky(db, now):
        calls.append(now)
        if len(calls) == 1:
            raise RuntimeError("잠김")
        return []

    monkeypatch.setattr(purge, "purge_due", flaky)
    job = purge.PurgeJob(world.db, world.clock, interval_seconds=0.02)
    job.start()
    try:
        deadline = datetime.now(UTC).timestamp() + 5
        while len(calls) < 2 and datetime.now(UTC).timestamp() < deadline:
            job._stop.wait(0.01)
    finally:
        job.stop()
    assert len(calls) >= 2


def test_the_server_starts_the_job_with_itself_and_stops_it_on_shutdown(world, tmp_path):
    from dataclasses import replace

    from fastapi.testclient import TestClient

    from app.main import create_app

    settings = replace(world.settings, database_path=tmp_path / "own.db")
    app = create_app(settings, clock=world.clock, auth_provider=None, start_mail_worker=False, start_purge_job=True)
    job = app.state.purge_job
    assert not job.is_running()
    with TestClient(app):
        assert job.is_running()
    assert not job.is_running()


def test_by_default_the_job_follows_the_mail_worker_switch(world):
    # 테스트용 앱(conftest)은 메일 작업을 끄므로 정리 작업도 돌지 않는다(시계를 옮겨도 저절로 지워지지 않는다)
    assert not world.app.state.purge_job.is_running()
