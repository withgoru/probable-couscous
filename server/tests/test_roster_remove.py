"""AC19, AC20, AC48: 명단에서 학생 빼기(DELETE …/roster/{entry})와 로그인 끊기(POST …/roster/{entry}/revoke-login).

- 빼면 명단에서 사라지고 입장이 거부되며, 이 강좌의 로그인 유지도 끝난다(다시 명단에 넣어도 코드가 필요하다).
- 끊으면 그 학생의 모든 기기가 이 강좌에서 로그아웃되고, 다시 들어오려면 이메일 인증이 필요하며 닉네임은 같다.
- 다른 강좌의 입장은 그대로다(기기 로그인은 계정 단위라 강좌별로만 끊는다).
- 둘 다 누가·언제·어느 학생인지를 `events`에 남긴다. 개인정보는 싣지 않는다(C6, C7).
"""

import json
import re

import pytest
from conftest import ORIGIN
from fastapi.testclient import TestClient

from app import authz, events

NOT_FOUND = "명단에서 찾을 수 없는 학생입니다. 명단을 새로 불러와 확인해 주세요."
NOT_ENTERED = "아직 입장하지 않은 학생입니다. 끊을 로그인이 없습니다."
NOT_ON_ROSTER = "이 강좌의 수강생 명단에 없습니다. 교수님께 문의해 주세요."


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def enroll(prof, cid, no="1", name="김철수", email="kim@x.kr"):
    r = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)
    assert r.status_code == 201, r.text
    return r.json()["id"]


def verify_by_code(world, client, token, email="kim@x.kr"):
    assert client.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"
    world.app.state.mail_worker.process_due()
    code = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    res = client.post(f"/api/join/{token}/code", json={"email": email, "code": code}, headers=ORIGIN)
    assert res.status_code == 200, res.text
    return res.json()


def me(client, token):
    return client.get(f"/api/join/{token}/me")


def enter(client, token):
    return client.post(f"/api/join/{token}/enter", headers=ORIGIN)


def entered_student(world, prof, cid, token, email="kim@x.kr"):
    """명단에 있고 코드로 인증한 뒤 입장까지 마친 기기."""
    student = world.client()
    nickname = verify_by_code(world, student, token, email)["nickname"]
    assert enter(student, token).status_code == 200
    return student, nickname


def remove(client, cid, entry, headers=ORIGIN):
    return client.delete(f"/api/classrooms/{cid}/roster/{entry}", headers=headers)


def revoke(client, cid, entry, headers=ORIGIN):
    return client.post(f"/api/classrooms/{cid}/roster/{entry}/revoke-login", headers=headers)


def roster(prof, cid):
    return prof.get(f"/api/classrooms/{cid}/roster").json()["entries"]


def rows(world, table):
    return [dict(r) for r in world.db().execute(f"SELECT * FROM {table} ORDER BY rowid")]


# --- 빼기 (AC19) -----------------------------------------------------------------------------------------------------


def test_removing_takes_the_student_off_the_roster_but_keeps_the_row(world):
    prof, cid, _ = classroom(world)
    entry = enroll(prof, cid)
    other = enroll(prof, cid, "2", "이영희", "lee@x.kr")
    world.clock.advance(minutes=5)
    res = remove(prof, cid, entry)
    assert res.status_code == 200
    assert res.json() == {"id": entry, "removed": True}
    assert [e["id"] for e in roster(prof, cid)] == [other]
    removed = next(r for r in rows(world, "roster_entries") if r["id"] == entry)
    assert removed["removed_at"] == world.clock.now().isoformat()  # 지우지 않고 뺀 시각만 남긴다(기록의 대상이 남아야 한다)
    assert prof.get(f"/api/classrooms/{cid}").json()["student_count"] == 1


def test_a_removed_student_cannot_get_a_code_and_is_told_to_ask(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    remove(prof, cid, entry)
    res = world.client().post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN)
    assert res.json()["next"] == "request_access"


def test_a_removed_student_who_had_entered_is_refused_even_with_a_remembered_login(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    student, _ = entered_student(world, prof, cid, token)
    remove(prof, cid, entry)
    assert me(student, token).json() == {"state": "login"}
    res = enter(student, token)
    assert res.status_code == 403 and res.json() == {"detail": NOT_ON_ROSTER}


def test_removing_ends_the_remembered_login_so_adding_back_needs_a_code_and_keeps_the_nickname(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    student, nickname = entered_student(world, prof, cid, token)
    world.clock.advance(minutes=1)
    remove(prof, cid, entry)
    world.clock.advance(minutes=1)
    enroll(prof, cid)  # 실수로 뺐다가 다시 넣었다
    assert me(student, token).json() == {"state": "login"}  # 로그인 유지는 끝났다
    world.clock.advance(minutes=1)
    assert verify_by_code(world, student, token)["nickname"] == nickname
    assert enter(student, token).json()["nickname"] == nickname


def test_a_code_asked_for_before_removal_cannot_be_used_after_adding_back(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    student = world.client()
    assert student.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN).json()["next"] == "code"
    world.app.state.mail_worker.process_due()
    code = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    remove(prof, cid, entry)
    enroll(prof, cid)
    res = student.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": code}, headers=ORIGIN)
    assert res.status_code == 422  # 빼기 전에 받은 코드는 쓸 수 없다. 새로 받아야 한다
    assert res.json()["detail"]["message"] == "이 코드는 더 이상 쓸 수 없습니다. 코드를 다시 받아 주세요."
    assert {r["status"] for r in rows(world, "login_challenges")} == {"superseded"}


def test_removing_in_one_classroom_does_not_touch_another(world):
    prof, cid, token = classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    entry = enroll(prof, cid)
    enroll(prof, cid2)
    student, _ = entered_student(world, prof, cid, token)
    assert enter(student, token2).status_code == 200  # 같은 기기로 다른 강좌에도 입장했다(AC37)
    remove(prof, cid, entry)
    assert me(student, token2).json()["state"] == "entered"
    assert len(rows(world, "device_logins")) == 1 and rows(world, "device_logins")[0]["revoked_at"] is None


def test_removing_twice_or_a_missing_or_foreign_entry_is_not_found(world):
    prof, cid, _ = classroom(world, "웹")
    _, cid2, _ = classroom(world, "앱")
    entry = enroll(prof, cid)
    foreign = enroll(prof, cid2, "9", "박", "park@x.kr")
    assert remove(prof, cid, entry).status_code == 200
    for target in (entry, foreign, 9999):
        res = remove(prof, cid, target)
        assert res.status_code == 404 and res.json() == {"detail": {"field": None, "message": NOT_FOUND}}
    assert len([e for e in rows(world, "events") if e["type"] == "roster_removed"]) == 1


def test_removing_is_recorded_with_who_when_and_which_student_and_no_personal_data(world):
    prof, cid, _ = classroom(world)
    entry = enroll(prof, cid, "20240001", "김철수", "kim@x.kr")
    world.clock.advance(minutes=3)
    remove(prof, cid, entry)
    (e,) = rows(world, "events")
    assert (e["classroom_id"], e["type"], e["actor_kind"], e["actor_ref"], e["subject_roster_entry_id"]) == (
        cid, "roster_removed", "professor", 101, entry,
    )
    assert e["created_at"] == world.clock.now().isoformat()
    assert json.loads(e["payload"]) == {}
    assert not any(v in str(e) for v in ("kim@x.kr", "김철수", "20240001"))


# --- 로그인 끊기 (AC20) ----------------------------------------------------------------------------------------------


def test_cutting_the_login_logs_out_every_device_of_the_student_in_this_classroom(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    phone, _ = entered_student(world, prof, cid, token)
    world.clock.advance(minutes=1)
    laptop, _ = entered_student(world, prof, cid, token)
    world.clock.advance(minutes=1)
    res = revoke(prof, cid, entry)
    assert res.status_code == 200 and res.json() == {"id": entry, "revoked": True}
    for device in (phone, laptop):
        assert me(device, token).json() == {"state": "login"}
        assert enter(device, token).status_code == 401
    assert [e["id"] for e in roster(prof, cid)] == [entry]  # 명단에는 그대로 있다


def test_after_the_cut_the_student_comes_back_with_a_code_and_the_same_nickname(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    student, nickname = entered_student(world, prof, cid, token)
    world.clock.advance(minutes=1)
    revoke(prof, cid, entry)
    world.clock.advance(minutes=1)
    assert verify_by_code(world, student, token)["nickname"] == nickname
    assert me(student, token).json()["state"] == "notice"
    assert enter(student, token).json()["nickname"] == nickname
    assert len(rows(world, "memberships")) == 1


def test_cutting_the_login_in_one_classroom_keeps_the_other_classrooms(world):
    prof, cid, token = classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    entry = enroll(prof, cid)
    enroll(prof, cid2)
    student, _ = entered_student(world, prof, cid, token)
    enter(student, token2)
    world.clock.advance(minutes=1)
    revoke(prof, cid, entry)
    assert me(student, token).json()["state"] == "login"
    assert me(student, token2).json()["state"] == "entered"


def test_a_student_who_never_entered_has_no_login_to_cut(world):
    prof, cid, _ = classroom(world)
    entry = enroll(prof, cid)
    res = revoke(prof, cid, entry)
    assert res.status_code == 409 and res.json() == {"detail": {"field": None, "message": NOT_ENTERED}}
    assert rows(world, "events") == []


def test_cutting_a_removed_missing_or_foreign_entry_is_not_found(world):
    prof, cid, token = classroom(world, "웹")
    _, cid2, token2 = classroom(world, "앱")
    entry = enroll(prof, cid)
    foreign = enroll(prof, cid2, "9", "박", "park@x.kr")
    entered_student(world, prof, cid2, token2, "park@x.kr")
    entered_student(world, prof, cid, token)
    remove(prof, cid, entry)
    for target in (entry, foreign, 9999):
        res = revoke(prof, cid, target)
        assert res.status_code == 404 and res.json() == {"detail": {"field": None, "message": NOT_FOUND}}


def test_cutting_twice_is_fine_and_each_cut_is_recorded(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    entered_student(world, prof, cid, token)
    world.clock.advance(minutes=1)
    assert revoke(prof, cid, entry).status_code == 200
    world.clock.advance(minutes=1)
    assert revoke(prof, cid, entry).status_code == 200
    cuts = [e for e in rows(world, "events") if e["type"] == "login_revoked"]
    assert len(cuts) == 2
    (m,) = rows(world, "memberships")
    assert m["reverify_after"] == world.clock.now().isoformat()  # 마지막으로 끊은 시각이 기준이다


def test_cutting_is_recorded_with_who_when_and_which_student_and_no_personal_data(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid, "20240001", "김철수", "kim@x.kr")
    _, nickname = entered_student(world, prof, cid, token)
    world.clock.advance(minutes=3)
    revoke(prof, cid, entry)
    (e,) = [e for e in rows(world, "events") if e["type"] == "login_revoked"]
    assert (e["classroom_id"], e["actor_kind"], e["actor_ref"], e["subject_roster_entry_id"]) == (cid, "professor", 101, entry)
    assert e["created_at"] == world.clock.now().isoformat()
    assert json.loads(e["payload"]) == {}
    assert not any(v in str(e) for v in ("kim@x.kr", "김철수", "20240001", nickname))  # 닉네임과 사람을 잇지 않는다(C9)


# --- 기록이 실패하면 아무것도 바뀌지 않는다 (C6) ---------------------------------------------------------------------


def _safe(world, prof):
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    return safe


def test_a_failure_while_recording_undoes_the_removal_and_the_cut(world, monkeypatch):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    student, _ = entered_student(world, prof, cid, token)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(events, "record_event", boom)
    safe = _safe(world, prof)
    assert remove(safe, cid, entry).status_code == 500
    assert revoke(safe, cid, entry).status_code == 500
    assert [e["id"] for e in roster(prof, cid)] == [entry]
    assert rows(world, "memberships")[0]["reverify_after"] is None
    assert me(student, token).json()["state"] == "entered"


# --- 권한과 출처 (C8) ------------------------------------------------------------------------------------------------


@pytest.mark.parametrize("action", ["remove", "revoke"])
def test_only_the_owner_can_remove_or_cut(world, action):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    entered_student(world, prof, cid, token)
    call = remove if action == "remove" else revoke
    assert call(world.client("lee"), cid, entry).status_code == 403
    assert call(world.client(), cid, entry).status_code == 401
    assert call(prof, 9999, entry).status_code == 404
    assert call(prof, cid, entry, headers={"Origin": "https://evil.example"}).status_code == 403
    assert rows(world, "events") == []
    assert [e["id"] for e in roster(prof, cid)] == [entry]


def test_both_are_judged_as_roster_manage(world, monkeypatch):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    entered_student(world, prof, cid, token)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    revoke(prof, cid, entry)
    remove(prof, cid, entry)
    assert calls == [authz.Action.ROSTER_MANAGE] * 2


def test_an_archived_classroom_can_still_be_cleaned_up_by_its_owner(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    entered_student(world, prof, cid, token)
    world.db().execute("UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ?", (world.clock.now().isoformat(), cid))
    assert revoke(prof, cid, entry).status_code == 200
    assert remove(prof, cid, entry).status_code == 200
