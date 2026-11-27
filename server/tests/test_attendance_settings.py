"""003 T004: 출석 받는 시간 설정 서버(AC1, AC26)."""

import json

import pytest
from attendance_world import enroll, entered_student, invite_token, make_classroom
from conftest import ORIGIN
from fastapi.testclient import TestClient

from app import events

NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."
BAD_MINUTES = "출석 받는 시간은 5분, 10분, 15분 중에서 골라 주세요."


def put_minutes(client, classroom_id, minutes):
    return client.put(
        f"/api/classrooms/{classroom_id}/attendance-settings", json={"minutes": minutes}, headers=ORIGIN
    )


def minutes_in_db(world, classroom_id):
    return world.db().execute("SELECT attendance_minutes FROM classrooms WHERE id = ?", (classroom_id,)).fetchone()[0]


def events_of(world, classroom_id, type_):
    rows = world.db().execute(
        "SELECT actor_kind, actor_ref, payload FROM events WHERE classroom_id = ? AND type = ? ORDER BY id",
        (classroom_id, type_),
    ).fetchall()
    return [(r["actor_kind"], r["actor_ref"], json.loads(r["payload"])) for r in rows]


def test_new_classroom_starts_at_ten_minutes_and_reports_it(world):
    prof, cid = make_classroom(world)
    assert prof.get(f"/api/classrooms/{cid}").json()["attendance_minutes"] == 10
    listed = prof.get("/api/classrooms").json()["classrooms"]
    assert [c["attendance_minutes"] for c in listed] == [10]


@pytest.mark.parametrize("minutes", [5, 15, 10])
def test_owner_saves_5_10_or_15_minutes(world, minutes):
    prof, cid = make_classroom(world)
    res = put_minutes(prof, cid, minutes)
    assert res.status_code == 200, res.text
    assert res.json()["attendance_minutes"] == minutes
    assert minutes_in_db(world, cid) == minutes
    assert prof.get(f"/api/classrooms/{cid}").json()["attendance_minutes"] == minutes


@pytest.mark.parametrize("bad", [0, 7, 20, -5, "10", 10.0, 10.5, True, None, [10]])
def test_other_values_are_refused_with_a_korean_message(world, bad):
    prof, cid = make_classroom(world)
    res = put_minutes(prof, cid, bad)
    assert res.status_code == 422
    assert res.json()["detail"] == BAD_MINUTES
    assert minutes_in_db(world, cid) == 10


def test_missing_body_field_is_refused(world):
    prof, cid = make_classroom(world)
    res = prof.put(f"/api/classrooms/{cid}/attendance-settings", json={}, headers=ORIGIN)
    assert res.status_code == 422
    assert res.json()["detail"] == BAD_MINUTES


def test_change_is_recorded_once_per_change(world):
    prof, cid = make_classroom(world)
    put_minutes(prof, cid, 15)
    put_minutes(prof, cid, 15)  # 같은 값이면 기록하지 않는다
    put_minutes(prof, cid, 5)
    assert events_of(world, cid, "attendance_minutes_changed") == [
        ("professor", 101, {"from": 10, "to": 15}),
        ("professor", 101, {"from": 15, "to": 5}),
    ]


def test_archived_classroom_can_still_be_set(world):
    # attendance.manage는 보관된 강좌도 된다(끝난 뒤 정리용)
    prof, cid = make_classroom(world)
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    assert put_minutes(prof, cid, 5).status_code == 200


def test_other_professor_is_refused(world):
    _, cid = make_classroom(world)
    other = world.client("lee")
    res = put_minutes(other, cid, 5)
    assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert minutes_in_db(world, cid) == 10


def test_entered_student_is_refused_with_the_same_message(world):
    # AC26: 학생이 시도해도 "이 강좌에 대한 권한이 없습니다."(로그인 안내가 아니다)
    prof, cid = make_classroom(world)
    student = entered_student(world, prof, cid, "s1@x.kr")
    res = put_minutes(student, cid, 5)
    assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert minutes_in_db(world, cid) == 10


def test_student_who_has_not_entered_is_refused_with_the_same_message(world):
    # 이메일 인증까지만 하고 입장하지 않은 학생(명단에서 빠졌거나 로그인이 끊긴 학생도 이렇게 된다)
    prof, cid = make_classroom(world)
    enroll(prof, cid, "s2@x.kr", no="2")
    token = invite_token(prof, cid)
    half = world.client()
    half.post(f"/api/join/{token}/email", json={"email": "s2@x.kr"}, headers=ORIGIN)
    res = put_minutes(half, cid, 5)
    assert res.status_code == 401  # 아직 로그인 전이다(코드를 넣지 않았다)
    other_class_student = entered_student(world, *make_classroom(world, name="다른 강좌"), "s3@x.kr")
    res = put_minutes(other_class_student, cid, 5)
    assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert minutes_in_db(world, cid) == 10


def test_failure_while_recording_leaves_the_setting_unchanged(world, monkeypatch):
    # C6: 기록 없이 바뀌지 않는다(바꾸기와 기록이 한 트랜잭션)
    prof, cid = make_classroom(world)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(events, "record_event", boom)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    assert put_minutes(safe, cid, 5).status_code == 500
    assert minutes_in_db(world, cid) == 10


def test_anonymous_is_asked_to_log_in(world):
    _, cid = make_classroom(world)
    res = put_minutes(world.client(), cid, 5)
    assert res.status_code == 401


def test_unknown_classroom_is_not_found(world):
    prof, _ = make_classroom(world)
    assert put_minutes(prof, 9999, 5).status_code == 404


def test_request_from_another_site_is_refused(world):
    prof, cid = make_classroom(world)
    res = prof.put(
        f"/api/classrooms/{cid}/attendance-settings", json={"minutes": 5}, headers={"Origin": "https://evil.example"}
    )
    assert res.status_code == 403
    assert minutes_in_db(world, cid) == 10


def test_clone_keeps_the_attendance_minutes(world):
    # AC1: 분반 만들기·새 학기 복제는 원래 강좌의 값을 가져간다
    prof, cid = make_classroom(world, section="월수반")
    put_minutes(prof, cid, 15)
    res = prof.post(f"/api/classrooms/{cid}/clone", json={"section_name": "화목반"}, headers=ORIGIN)
    assert res.status_code == 201, res.text
    assert res.json()["attendance_minutes"] == 15
    assert minutes_in_db(world, res.json()["id"]) == 15
    assert minutes_in_db(world, cid) == 15


def test_new_classroom_does_not_inherit_from_another(world):
    prof, cid = make_classroom(world)
    put_minutes(prof, cid, 5)
    _, other = make_classroom(world, name="자료구조")
    assert minutes_in_db(world, other) == 10
