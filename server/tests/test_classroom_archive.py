"""AC9, AC10(서버): 강좌 보관(POST /api/classrooms/{id}/archive).

- 보관하면 학생 입장이 보관 안내로 거부되고, 로그인 유지 중이던 학생도 거부된다.
- 보관된 강좌는 목록의 보관됨으로 옮겨지고, 기록 보기(조회)와 복제는 그대로 된다.
- 보관은 누가·언제를 `classroom_archived`로 남긴다(C6). 되돌리는 기능은 없다(스펙 범위 밖).
"""

import json
import re

import pytest
from conftest import ORIGIN
from fastapi.testclient import TestClient

from app import authz, events

ARCHIVED = "이 강좌는 보관되었습니다. 교수님께 문의해 주세요."
ALREADY = "이미 보관된 강좌입니다."


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def enroll(prof, cid, no="1", name="김철수", email="kim@x.kr"):
    r = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def ask_code(world, client, token, email="kim@x.kr"):
    assert client.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"


def entered_student(world, token, email="kim@x.kr"):
    student = world.client()
    ask_code(world, student, token, email)
    world.app.state.mail_worker.process_due()
    code = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    assert student.post(f"/api/join/{token}/code", json={"email": email, "code": code}, headers=ORIGIN).status_code == 200
    assert student.post(f"/api/join/{token}/enter", headers=ORIGIN).status_code == 200
    return student


def archive(client, cid, headers=ORIGIN):
    return client.post(f"/api/classrooms/{cid}/archive", headers=headers)


def rows(world, table):
    return [dict(r) for r in world.db().execute(f"SELECT * FROM {table} ORDER BY rowid")]


# --- 보관 (AC9) ------------------------------------------------------------------------------------------------------


def test_archiving_marks_the_classroom_and_returns_it(world):
    prof, cid, _ = classroom(world)
    enroll(prof, cid)
    world.clock.advance(minutes=5)
    res = archive(prof, cid)
    assert res.status_code == 200
    body = res.json()
    assert (body["id"], body["status"], body["student_count"]) == (cid, "archived", 1)
    (c,) = rows(world, "classrooms")
    assert c["archived_at"] == world.clock.now().isoformat()


def test_an_archived_classroom_moves_to_the_archived_count_of_the_list(world):
    prof, cid, _ = classroom(world, "웹")
    classroom(world, "앱")
    archive(prof, cid)
    listing = prof.get("/api/classrooms").json()
    assert listing["counts"] == {"active": 1, "archived": 1}
    assert {c["name"]: c["status"] for c in listing["classrooms"]} == {"웹": "archived", "앱": "active"}


def test_archiving_is_recorded_with_who_and_when(world):
    prof, cid, _ = classroom(world)
    world.clock.advance(minutes=1)
    archive(prof, cid)
    (e,) = rows(world, "events")
    assert (e["classroom_id"], e["type"], e["actor_kind"], e["actor_ref"], e["subject_roster_entry_id"]) == (
        cid, "classroom_archived", "professor", 101, None,
    )
    assert e["created_at"] == world.clock.now().isoformat()
    assert json.loads(e["payload"]) == {}


def test_archiving_twice_is_refused_and_recorded_once(world):
    prof, cid, _ = classroom(world)
    archive(prof, cid)
    first = rows(world, "classrooms")[0]["archived_at"]
    world.clock.advance(minutes=1)
    res = archive(prof, cid)
    assert res.status_code == 409 and res.json() == {"detail": ALREADY}
    assert rows(world, "classrooms")[0]["archived_at"] == first  # 6개월 정리의 기준 시각이 바뀌지 않는다
    assert len(rows(world, "events")) == 1


def test_a_failure_while_recording_leaves_the_classroom_active(world, monkeypatch):
    prof, cid, _ = classroom(world)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(events, "record_event", boom)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    assert archive(safe, cid).status_code == 500
    assert rows(world, "classrooms")[0]["status"] == "active"


# --- 보관 뒤 학생 (AC10) ---------------------------------------------------------------------------------------------


def test_after_archiving_the_invite_link_shows_the_archived_notice(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    archive(prof, cid)
    visitor = world.client()
    for res in (
        visitor.get(f"/api/join/{token}"),
        visitor.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN),
    ):
        assert res.status_code == 403 and res.json() == {"detail": ARCHIVED}


def test_a_student_with_a_remembered_login_gets_the_same_notice(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = entered_student(world, token)
    archive(prof, cid)
    for res in (student.get(f"/api/join/{token}/me"), student.post(f"/api/join/{token}/enter", headers=ORIGIN)):
        assert res.status_code == 403 and res.json() == {"detail": ARCHIVED}


def test_archiving_one_classroom_keeps_the_students_other_classrooms(world):
    prof, cid, token = classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    enroll(prof, cid)
    enroll(prof, cid2)
    student = entered_student(world, token)
    assert student.post(f"/api/join/{token2}/enter", headers=ORIGIN).status_code == 200
    archive(prof, cid)
    assert student.get(f"/api/join/{token2}/me").json()["state"] == "entered"


def test_codes_waiting_to_be_sent_or_used_are_dropped(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    ask_code(world, world.client(), token)  # 메일이 아직 나가지 않았다
    archive(prof, cid)
    world.app.state.mail_worker.process_due()
    assert world.app.state.mailer.sent == []  # 보관된 강좌의 코드는 보내지 않는다
    assert {r["status"] for r in rows(world, "login_challenges")} == {"superseded"}
    (mail,) = rows(world, "mail_outbox")
    assert mail["status"] == "failed" and mail["to_email"] is None  # 수신 주소도 비운다(C11)


def test_archiving_leaves_the_codes_of_other_classrooms_alone(world):
    prof, cid, _ = classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    enroll(prof, cid)
    enroll(prof, cid2)
    ask_code(world, world.client(), token2)
    archive(prof, cid)
    world.app.state.mail_worker.process_due()
    assert len(world.app.state.mailer.sent) == 1


# --- 보관 뒤 교수 --------------------------------------------------------------------------------------------------------


def test_the_owner_still_reads_the_records_and_can_clone(world):
    prof, cid, _ = classroom(world)
    enroll(prof, cid)
    archive(prof, cid)
    assert prof.get(f"/api/classrooms/{cid}").json()["status"] == "archived"
    assert len(prof.get(f"/api/classrooms/{cid}/roster").json()["entries"]) == 1
    clone = prof.post(f"/api/classrooms/{cid}/clone", json={}, headers=ORIGIN)
    assert clone.status_code == 201 and clone.json()["status"] == "active"


# --- 권한과 출처 (C8) ------------------------------------------------------------------------------------------------


def test_only_the_owner_can_archive(world):
    prof, cid, _ = classroom(world)
    assert archive(world.client("lee"), cid).status_code == 403
    assert archive(world.client(), cid).status_code == 401
    assert archive(prof, 9999).status_code == 404
    assert archive(prof, cid, headers={"Origin": "https://evil.example"}).status_code == 403
    assert rows(world, "classrooms")[0]["status"] == "active" and rows(world, "events") == []


def test_archiving_is_judged_as_classroom_manage(world, monkeypatch):
    prof, cid, _ = classroom(world)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    archive(prof, cid)
    assert calls == [authz.Action.CLASSROOM_MANAGE]


@pytest.mark.parametrize("body", [None, {"anything": 1}])
def test_the_body_is_ignored(world, body):
    prof, cid, _ = classroom(world)
    res = prof.post(f"/api/classrooms/{cid}/archive", json=body, headers=ORIGIN)
    assert res.status_code == 200
