"""AC44~AC48의 서버 쪽: '교수님께 알리기'(학생)와 '대기 중인 인증' 목록(교수). 알린 챌린지의 코드만 교수에게 보이고, 볼 때마다 기록한다."""

import json
import re
from datetime import timedelta

from conftest import ORIGIN

from app import authz, events

NOTIFIED = "교수님께 알렸습니다. 교수님이 알려 주는 코드를 입력하세요."
NO_CHALLENGE = "알릴 인증 코드가 없습니다. 인증 코드 받기부터 다시 해 주세요."
EXPIRED = "코드가 만료되었습니다. 코드를 다시 받아 주세요."
USED = "이미 사용된 코드입니다. 코드를 다시 받아 주세요."


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def enroll(prof, cid, no="1", name="김철수", email="kim@x.kr"):
    r = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)
    assert r.status_code == 201
    return r.json()["id"]


def request_code(world, client, token, email="kim@x.kr"):
    """코드를 요청하고 메일로 간 코드를 돌려준다(메일 코드와 교수가 보는 코드가 같아야 한다)."""
    assert client.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"
    mailer = world.app.state.mailer
    before = len(mailer.sent)
    world.app.state.mail_worker.process_due()
    assert len(mailer.sent) == before + 1
    return re.search(r"\b(\d{6})\b", mailer.sent[-1].text).group(1)


def notify(client, token, email="kim@x.kr", **kw):
    return client.post(f"/api/join/{token}/notify-professor", json={"email": email}, headers=kw.get("headers", ORIGIN))


def pending(prof, cid):
    return prof.get(f"/api/classrooms/{cid}/pending-auth")


def submit(client, token, code, email="kim@x.kr"):
    return client.post(f"/api/join/{token}/code", json={"email": email, "code": code}, headers=ORIGIN)


def rows(world, table):
    return [dict(r) for r in world.db().execute(f"SELECT * FROM {table}")]


def student_with_code(world, name="웹"):
    prof, cid, token = classroom(world, name)
    entry = enroll(prof, cid)
    student = world.client()
    return prof, cid, token, entry, student, request_code(world, student, token)


# --- 학생: 교수님께 알리기 (AC44) -------------------------------------------------------------------------------------


def test_notifying_marks_the_challenge_and_says_what_to_do_next(world):
    _prof, _cid, token, _entry, student, _code = student_with_code(world)
    res = notify(student, token)
    assert res.status_code == 200 and res.json() == {"next": "notified", "message": NOTIFIED}
    (c,) = rows(world, "login_challenges")
    assert c["professor_notified_at"] == world.clock.now().isoformat() and c["status"] == "active" and c["attempts"] == 0


def test_notifying_again_keeps_the_first_time_and_sends_no_mail(world):
    _prof, _cid, token, _entry, student, _code = student_with_code(world)
    notify(student, token)
    first = rows(world, "login_challenges")[0]["professor_notified_at"]
    world.clock.advance(minutes=3)
    assert notify(student, token).status_code == 200
    assert rows(world, "login_challenges")[0]["professor_notified_at"] == first
    assert len(rows(world, "mail_outbox")) == 1  # 알려도 메일이 더 가지 않는다


def test_a_device_that_did_not_ask_for_the_code_cannot_notify_and_learns_nothing(world):
    _prof, _cid, token, _entry, _student, _code = student_with_code(world)
    elsewhere = world.client()
    elsewhere.get(f"/api/join/{token}")
    cookieless = world.client()
    for client in (elsewhere, cookieless):
        res = notify(client, token)
        assert res.status_code == 422 and res.json()["detail"] == {"field": None, "message": NO_CHALLENGE}
    assert rows(world, "login_challenges")[0]["professor_notified_at"] is None
    assert len(rows(world, "devices")) == 2  # 쿠키 없는 요청은 기기를 만들지 않는다(링크를 연 기기와 코드를 요청한 기기)


def test_notifying_without_having_asked_for_a_code_is_explained(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    student.get(f"/api/join/{token}")
    res = notify(student, token)
    assert res.status_code == 422 and res.json()["detail"]["message"] == NO_CHALLENGE


def test_the_email_must_be_the_one_the_code_was_asked_for(world):
    prof, cid, token, _entry, student, _code = student_with_code(world)
    enroll(prof, cid, no="2", name="이영희", email="lee@x.kr")
    assert notify(student, token, "lee@x.kr").status_code == 422
    assert rows(world, "login_challenges")[0]["professor_notified_at"] is None


def test_an_expired_or_used_code_cannot_be_notified(world):
    _prof, _cid, token, _entry, student, code = student_with_code(world)
    assert submit(student, token, code).status_code == 200
    used = notify(student, token)
    assert used.status_code == 422 and used.json()["detail"]["message"] == USED
    world.clock.advance(minutes=1)
    student.post(f"/api/join/{token}/resend", json={"email": "kim@x.kr"}, headers=ORIGIN)
    world.clock.advance(minutes=11)
    expired = notify(student, token)
    assert expired.status_code == 422 and expired.json()["detail"]["message"] == EXPIRED
    assert all(c["professor_notified_at"] is None for c in rows(world, "login_challenges"))


def test_a_locked_code_cannot_be_notified(world):
    _prof, _cid, token, _entry, student, code = student_with_code(world)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        submit(student, token, wrong)
    assert notify(student, token).json()["detail"]["message"] == EXPIRED


def test_the_email_is_checked_like_everywhere_else(world):
    _, _, token, _, student, _ = student_with_code(world)
    for body in [{}, {"email": None}, {"email": 5}, {"email": "nope"}, {"email": ""}]:
        res = student.post(f"/api/join/{token}/notify-professor", json=body, headers=ORIGIN)
        assert res.status_code == 422 and res.json()["detail"]["field"] == "email", body


def test_notify_is_refused_for_archived_revoked_links_and_foreign_origins(world):
    _prof, cid, token, _entry, student, _code = student_with_code(world)
    assert notify(student, token, headers={"Origin": "https://evil.example"}).status_code == 403
    assert notify(student, "made-up-token-0000000").status_code == 404
    world.db().execute("UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ?", (world.clock.now().isoformat(), cid))
    assert notify(student, token).status_code == 403
    assert rows(world, "login_challenges")[0]["professor_notified_at"] is None


# --- 교수: 대기 중인 인증 (AC45) ---------------------------------------------------------------------------------------


def test_before_anyone_notifies_the_list_is_empty_and_no_code_is_computed(world):
    prof, cid, _token, _entry, _student, code = student_with_code(world)
    res = pending(prof, cid)
    assert res.status_code == 200 and res.json() == {"items": []}
    assert code not in res.text and rows(world, "events") == []


def test_a_notified_student_shows_with_student_no_name_time_and_the_mailed_code(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    asked_at = world.clock.now()
    world.clock.advance(minutes=2)
    notify(student, token)
    res = pending(prof, cid)
    assert res.headers["cache-control"] == "no-store"
    (item,) = res.json()["items"]
    assert (item["student_no"], item["name"], item["status"], item["code"]) == ("1", "김철수", "waiting", code)
    assert item["notified_at"] == world.clock.now().isoformat() and isinstance(item["id"], int)
    # 화면이 시간이 지나면 스스로 '만료됨'으로 바꿀 수 있게 만료 시각을 준다(서버가 밀어 보내지 않는다)
    assert item["expires_at"] == (asked_at + timedelta(minutes=10)).isoformat()
    assert set(item) == {"id", "student_no", "name", "notified_at", "status", "code", "expires_at"}


def test_only_notified_students_codes_are_shown(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    enroll(prof, cid, no="2", name="이영희", email="lee@x.kr")
    world.clock.advance(seconds=1)
    other = world.client()
    other_code = request_code(world, other, token, "lee@x.kr")
    notify(student, token)  # 김철수만 알렸다
    res = pending(prof, cid)
    assert code in res.text and other_code not in res.text
    assert [i["name"] for i in res.json()["items"]] == ["김철수"]


def test_the_list_is_newest_notification_first(world):
    prof, cid, token, _entry, student, _code = student_with_code(world)
    enroll(prof, cid, no="2", name="이영희", email="lee@x.kr")
    notify(student, token)
    world.clock.advance(seconds=5)
    other = world.client()
    request_code(world, other, token, "lee@x.kr")
    world.clock.advance(seconds=5)
    notify(other, token, "lee@x.kr")
    assert [i["name"] for i in pending(prof, cid).json()["items"]] == ["이영희", "김철수"]


def test_no_email_nickname_or_link_to_a_membership_is_in_the_response(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    assert submit(student, token, code).status_code == 200  # 입장해서 멤버십(닉네임)이 생겼다
    nickname = rows(world, "memberships")[0]["nickname"]
    res = pending(prof, cid)
    for secret in ("kim@x.kr", nickname, "nickname"):
        assert secret not in res.text
    assert set(res.json()["items"][0]) == {"id", "student_no", "name", "notified_at", "status", "used_at"}


# --- 코드를 볼 때마다 기록 (AC48) ----------------------------------------------------------------------------------------


def test_every_response_records_a_code_revealed_event_for_each_code_it_shows(world):
    prof, cid, token, entry, student, _code = student_with_code(world)
    enroll(prof, cid, no="2", name="이영희", email="lee@x.kr")
    world.clock.advance(seconds=1)
    other = world.client()
    request_code(world, other, token, "lee@x.kr")
    notify(student, token)
    notify(other, token, "lee@x.kr")
    world.clock.advance(minutes=1)
    pending(prof, cid)
    pending(prof, cid)
    evs = rows(world, "events")
    assert len(evs) == 4  # 두 번 응답 x 코드 두 개
    for e in evs:
        assert (e["classroom_id"], e["type"], e["actor_kind"], e["actor_ref"]) == (cid, "code_revealed", "professor", 101)
        assert e["created_at"] == world.clock.now().isoformat()
        assert set(json.loads(e["payload"])) == {"challenge_id"}
        assert not re.search(r"\d{6}|@|김철수|이영희", e["payload"])  # 코드와 개인정보는 기록에 없다
    assert {e["subject_roster_entry_id"] for e in evs} == {entry, rows(world, "roster_entries")[1]["id"]}


def test_a_list_without_codes_records_nothing(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    submit(student, token, code)  # 사용됨: 코드는 더 보여 주지 않는다
    before = len(rows(world, "events"))
    pending(prof, cid)
    assert len(rows(world, "events")) == before


def test_if_the_event_cannot_be_recorded_the_code_is_not_shown(world, monkeypatch):
    from fastapi.testclient import TestClient

    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(events, "record_event", boom)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    res = safe.get(f"/api/classrooms/{cid}/pending-auth")
    assert res.status_code == 500 and code not in res.text  # 기록 없이 코드를 보여 주지 않는다


def test_a_failure_halfway_leaves_no_event_behind(world, monkeypatch):
    from fastapi.testclient import TestClient

    prof, cid, token, _entry, student, _code = student_with_code(world)
    enroll(prof, cid, no="2", name="이영희", email="lee@x.kr")
    world.clock.advance(seconds=1)
    other = world.client()
    request_code(world, other, token, "lee@x.kr")
    notify(student, token)
    notify(other, token, "lee@x.kr")
    real = events.record_event
    calls = {"n": 0}

    def second_fails(*args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("디스크 오류")
        return real(*args, **kwargs)

    monkeypatch.setattr(events, "record_event", second_fails)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    assert safe.get(f"/api/classrooms/{cid}/pending-auth").status_code == 500
    assert rows(world, "events") == []  # 한 응답의 기록은 함께 저장되거나 함께 사라진다


# --- 상태: 사용됨, 만료, 새 코드 (AC47) -----------------------------------------------------------------------------------


def test_a_used_code_shows_as_used_with_the_time_and_no_code(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    world.clock.advance(minutes=4)
    assert submit(student, token, code).status_code == 200  # 교수가 알려 준 코드로 입장 (AC46)
    (item,) = pending(prof, cid).json()["items"]
    assert item["status"] == "used" and item["used_at"] == world.clock.now().isoformat() and "code" not in item


def test_the_code_the_professor_tells_works_under_the_same_rules_as_the_mailed_one(world):
    prof, cid, token, _entry, student, _code = student_with_code(world)
    notify(student, token)
    told = pending(prof, cid).json()["items"][0]["code"]
    wrong = "000000" if told != "000000" else "111111"
    for _ in range(4):
        assert submit(student, token, wrong).status_code == 422
    assert submit(student, token, told).status_code == 200


def test_entering_with_an_already_used_code_gets_the_used_message(world):
    _prof, _cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    assert submit(student, token, code).status_code == 200
    again = submit(student, token, code)
    assert again.status_code == 422 and again.json()["detail"]["message"] == USED


def test_an_expired_or_locked_code_shows_as_expired_without_a_code(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    world.clock.advance(minutes=10)
    (item,) = pending(prof, cid).json()["items"]
    assert item["status"] == "expired" and "code" not in item and code not in json.dumps(item)


def test_a_code_locked_by_wrong_tries_shows_as_expired(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    wrong = "000000" if code != "000000" else "111111"
    for _ in range(5):
        submit(student, token, wrong)
    assert pending(prof, cid).json()["items"][0]["status"] == "expired"


def test_a_notified_code_that_was_replaced_by_a_new_one_disappears(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    world.clock.advance(minutes=1)
    student.post(f"/api/join/{token}/resend", json={"email": "kim@x.kr"}, headers=ORIGIN)  # 새 코드가 나왔다
    res = pending(prof, cid)
    assert res.json() == {"items": []}  # 이전 코드는 쓸 수 없고 새 코드는 알리지 않았다
    assert code not in res.text


def test_a_student_removed_from_the_roster_is_not_listed_and_their_code_is_not_shown(world):
    prof, cid, token, entry, student, code = student_with_code(world)
    notify(student, token)
    world.db().execute("UPDATE roster_entries SET removed_at = ? WHERE id = ?", (world.clock.now().isoformat(), entry))
    res = pending(prof, cid)
    assert res.json() == {"items": []} and code not in res.text and rows(world, "events") == []


def test_pending_auths_are_per_classroom(world):
    _prof, _a, token_a, _entry, student, code = student_with_code(world, "웹")
    notify(student, token_a)
    lee, b, _ = classroom(world, "DB", owner="lee")
    assert pending(lee, b).json() == {"items": []} and code not in pending(lee, b).text


# --- 권한 ------------------------------------------------------------------------------------------------------------------


def test_only_the_owner_sees_pending_auths_and_nothing_is_recorded_for_others(world):
    prof, cid, token, _entry, student, code = student_with_code(world)
    notify(student, token)
    lee = world.client("lee")
    res = pending(lee, cid)
    assert res.status_code == 403 and code not in res.text
    anon = pending(world.client(), cid)
    assert anon.status_code == 401 and code not in anon.text
    assert pending(prof, 999).status_code == 404
    assert rows(world, "events") == []


def test_the_routes_are_judged_by_the_right_actions(world, monkeypatch):
    prof, cid, token, _entry, student, _code = student_with_code(world)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    notify(student, token)
    pending(prof, cid)
    assert calls == [authz.Action.STUDENT_ENTER, authz.Action.PENDINGAUTH_VIEW]
