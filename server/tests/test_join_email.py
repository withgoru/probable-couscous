"""AC10, AC22~AC25, AC38의 서버 쪽: 초대 링크 열기(GET /api/join/{token})와 이메일 확인(POST /api/join/{token}/email)."""

import dataclasses

from conftest import ORIGIN

from app import authz
from app.challenges import code_for

NOT_IN_ROSTER = (
    "수강생 명단에 없는 이메일입니다. 수강신청에 쓴 이메일인지 확인하고, 계속 안 되면 교수님께 입장을 요청해 주세요."
)
REVOKED = "이 링크는 더 이상 사용할 수 없습니다. 교수님께 새 링크를 받으세요."
ARCHIVED = "이 강좌는 보관되었습니다. 교수님께 문의해 주세요."
BAD_EMAIL = "이메일 형식을 확인해 주세요."


def classroom(world, name="웹", section="월수반", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name, "section_name": section}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def enroll(prof, cid, no="1", name="김철수", email="kim@x.kr"):
    r = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)
    assert r.status_code == 201
    return r.json()["id"]


def open_link(client, token):
    return client.get(f"/api/join/{token}")


def post_email(client, token, email, **kw):
    return client.post(f"/api/join/{token}/email", json={"email": email}, headers=kw.get("headers", ORIGIN))


def rows(world, table):
    return [dict(r) for r in world.db().execute(f"SELECT * FROM {table}")]


# --- 링크 열기 (AC22, AC23, AC10) ---------------------------------------------------------------


def test_opening_a_valid_link_shows_the_classroom_name_and_section(world):
    _, _, token = classroom(world)
    res = open_link(world.client(), token)
    assert res.status_code == 200
    assert res.json() == {"name": "웹", "section_name": "월수반"}  # 강좌 번호와 교수 정보는 내려 주지 않는다


def test_a_made_up_token_and_a_revoked_token_get_exactly_the_same_answer(world):
    prof, cid, old = classroom(world)
    prof.post(f"/api/classrooms/{cid}/invite/regenerate", headers=ORIGIN)
    student = world.client()
    revoked = open_link(student, old)
    made_up = open_link(student, "never-existed-token-0000")
    assert revoked.status_code == made_up.status_code == 404
    assert revoked.json() == made_up.json() == {"detail": REVOKED}


def test_the_new_link_works_after_regenerating(world):
    prof, cid, _ = classroom(world)
    new = prof.post(f"/api/classrooms/{cid}/invite/regenerate", headers=ORIGIN).json()["token"]
    assert open_link(world.client(), new).status_code == 200


def test_an_archived_classroom_says_so_and_does_not_let_anyone_in(world):
    _, cid, token = classroom(world)
    world.db().execute("UPDATE classrooms SET status = 'archived', archived_at = '2026-03-01T00:00:00+00:00' WHERE id = ?", (cid,))
    res = open_link(world.client(), token)
    assert res.status_code == 403 and res.json() == {"detail": ARCHIVED}


def test_opening_a_link_does_not_log_anyone_in(world):
    _, _, token = classroom(world)
    student = world.client()
    res = open_link(student, token)
    assert set(res.cookies.keys()) == {"device"}  # 기기 쿠키뿐이다. 로그인 상태는 없다(AC23)
    assert student.get("/api/me").status_code == 401
    assert rows(world, "memberships") == [] and rows(world, "device_logins") == []


def test_the_device_cookie_is_planted_once_and_is_http_only(world):
    _, _, token = classroom(world)
    student = world.client()
    first = open_link(student, token)
    header = first.headers["set-cookie"].lower()
    assert "httponly" in header and "samesite=lax" in header and "path=/" in header and "max-age=" in header
    assert "secure" not in header  # 개발 주소(http)에서는 붙이지 않는다
    second = open_link(student, token)
    assert "set-cookie" not in second.headers  # 이미 있으면 다시 심지 않는다
    assert len(rows(world, "devices")) == 1


def test_the_cookie_is_secure_when_the_service_uses_https(world):
    _, _, token = classroom(world)  # 교수 로그인은 http에서 먼저 끝낸다
    world.app.state.settings = dataclasses.replace(world.settings, base_url="https://class.example.kr")
    res = world.client().get(f"/api/join/{token}", headers={"Origin": "https://class.example.kr"})
    assert "secure" in res.headers["set-cookie"].lower()


def test_junk_tokens_do_not_create_devices(world):
    student = world.client()
    for i in range(5):
        res = open_link(student, f"junk-{i}")
        assert "set-cookie" not in res.headers
    assert rows(world, "devices") == []


def test_one_device_cookie_serves_every_classroom(world):
    _, _, a = classroom(world, "웹")
    _, _, b = classroom(world, "DB")
    student = world.client()
    open_link(student, a)
    open_link(student, b)
    assert len(rows(world, "devices")) == 1  # 다른 강좌 링크를 열어도 같은 기기다(AC37의 바탕)


# --- 이메일 형식 (AC24) -------------------------------------------------------------------------------------


def test_a_malformed_email_is_explained_next_to_the_field_and_nothing_is_stored(world):
    _, _, token = classroom(world)
    for bad in ["kim", "kim@", "@x.kr", "kim x@x.kr", "", "   "]:
        res = post_email(world.client(), token, bad)
        assert res.status_code == 422, bad
        detail = res.json()["detail"]
        assert detail["field"] == "email"
        assert detail["message"] == (BAD_EMAIL if bad.strip() else "이메일을 입력해 주세요.")
    assert rows(world, "login_challenges") == [] and rows(world, "mail_outbox") == []


def test_a_non_text_email_is_a_422_not_a_500(world):
    _, _, token = classroom(world)
    for body in [{}, {"email": None}, {"email": 5}, {"email": ["a@x.kr"]}]:
        res = world.client().post(f"/api/join/{token}/email", json=body, headers=ORIGIN)
        assert res.status_code == 422 and res.json()["detail"]["field"] == "email", body


# --- 명단에 있는 이메일 (AC25) ---------------------------------------------------------------------------------


def test_an_email_in_the_roster_gets_a_challenge_and_a_queued_mail(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid, email="kim@x.kr")
    student = world.client()
    open_link(student, token)
    res = post_email(student, token, "kim@x.kr")
    assert res.status_code == 200
    body = res.json()
    assert body["next"] == "code" and body["wait_seconds"] == 60
    (challenge,) = rows(world, "login_challenges")
    assert (challenge["classroom_id"], challenge["email_norm"], challenge["status"]) == (cid, "kim@x.kr", "active")
    (mail,) = rows(world, "mail_outbox")
    assert (mail["classroom_id"], mail["kind"], mail["body_ref"], mail["status"], mail["to_email"]) == (
        cid, "code", challenge["id"], "pending", "kim@x.kr",
    )


def test_the_code_is_in_the_mail_and_never_in_the_response(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    res = post_email(world.client(), token, "kim@x.kr")
    code = code_for(world.db(), world.settings.server_secret, rows(world, "login_challenges")[0]["id"])
    assert code not in res.text
    world.app.state.mail_worker.process_due()
    (msg,) = world.app.state.mailer.sent
    assert msg.to == "kim@x.kr" and code in msg.text and "웹" in msg.text


def test_the_challenge_belongs_to_the_device_that_asked(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    res = post_email(student, token, "kim@x.kr")
    device_id = rows(world, "devices")[0]["id"]
    assert rows(world, "login_challenges")[0]["device_id"] == device_id
    assert "device" in student.cookies and "set-cookie" in res.headers


def test_a_new_device_cookie_is_planted_even_if_the_link_was_never_opened_first(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    post_email(student, token, "kim@x.kr")
    assert "device" in student.cookies and len(rows(world, "devices")) == 1


def test_the_same_email_with_other_case_and_spaces_finds_the_student(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid, email="kim@x.kr")
    res = post_email(world.client(), token, "  KIM@X.kr ")
    assert res.json()["next"] == "code"
    assert rows(world, "login_challenges")[0]["email_norm"] == "kim@x.kr"


def test_asking_again_within_60_seconds_is_refused_with_the_seconds_left(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    post_email(student, token, "kim@x.kr")
    world.clock.advance(seconds=20)
    res = post_email(student, token, "kim@x.kr")
    assert res.status_code == 429
    assert res.json()["detail"] == {"field": None, "message": "코드는 40초 뒤에 다시 받을 수 있습니다.", "wait_seconds": 40}
    assert len(rows(world, "login_challenges")) == 1 and len(rows(world, "mail_outbox")) == 1
    world.clock.advance(seconds=40)
    assert post_email(student, token, "kim@x.kr").status_code == 200
    assert [c["status"] for c in rows(world, "login_challenges")] == ["superseded", "active"]  # 이전 코드는 쓸 수 없다


def test_a_failure_while_queueing_the_mail_leaves_no_challenge_behind(world, monkeypatch):
    from app import join

    prof, cid, token = classroom(world)
    enroll(prof, cid)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(join, "enqueue_code_mail", boom)
    from fastapi.testclient import TestClient

    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    assert post_email(safe, token, "kim@x.kr").status_code == 500
    assert rows(world, "login_challenges") == []  # 코드만 있고 메일이 없는 챌린지가 남지 않는다


# --- 명단에 없는 이메일 (AC38) ---------------------------------------------------------------------------------


def test_an_email_not_in_the_roster_gets_no_mail_and_the_request_access_guidance(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid, email="kim@x.kr")
    res = post_email(world.client(), token, "stranger@x.kr")
    assert res.status_code == 200
    assert res.json() == {"next": "request_access", "message": NOT_IN_ROSTER}
    assert rows(world, "login_challenges") == [] and rows(world, "mail_outbox") == []


def test_a_removed_student_is_not_in_the_roster_anymore(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    world.db().execute("UPDATE roster_entries SET removed_at = '2026-03-01T00:00:00+00:00' WHERE id = ?", (entry,))
    assert post_email(world.client(), token, "kim@x.kr").json()["next"] == "request_access"
    assert rows(world, "mail_outbox") == []


def test_a_student_on_another_classrooms_roster_is_not_on_this_one(world):
    _, _, token = classroom(world, "웹")
    _, other, _ = classroom(world, "DB", owner="lee")
    world.client("lee").post(f"/api/classrooms/{other}/roster", json={"student_no": "1", "name": "김", "email": "kim@x.kr"}, headers=ORIGIN)
    assert post_email(world.client(), token, "kim@x.kr").json()["next"] == "request_access"
    assert rows(world, "mail_outbox") == []


# --- 막아야 할 때 ------------------------------------------------------------------------------------------------


def test_posting_to_a_revoked_or_made_up_link_gets_the_same_answer_and_stores_nothing(world):
    prof, cid, old = classroom(world)
    enroll(prof, cid)
    prof.post(f"/api/classrooms/{cid}/invite/regenerate", headers=ORIGIN)
    for token in (old, "made-up-token-0000000"):
        res = post_email(world.client(), token, "kim@x.kr")
        assert res.status_code == 404 and res.json() == {"detail": REVOKED}
    assert rows(world, "login_challenges") == [] and rows(world, "mail_outbox") == [] and rows(world, "devices") == []


def test_an_archived_classroom_gets_no_code(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    world.db().execute("UPDATE classrooms SET status = 'archived', archived_at = '2026-03-01T00:00:00+00:00' WHERE id = ?", (cid,))
    res = post_email(world.client(), token, "kim@x.kr")
    assert res.status_code == 403 and res.json() == {"detail": ARCHIVED}
    assert rows(world, "login_challenges") == [] and rows(world, "mail_outbox") == []


def test_the_service_origin_is_required_for_posting(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    res = post_email(world.client(), token, "kim@x.kr", headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert rows(world, "login_challenges") == []


def test_both_routes_are_judged_as_student_enter_actions(world, monkeypatch):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    student = world.client()
    open_link(student, token)
    post_email(student, token, "kim@x.kr")
    assert calls == [authz.Action.STUDENT_ENTER] * 2


def test_the_professors_own_session_does_not_change_what_the_link_does(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    assert open_link(prof, token).status_code == 200
    assert post_email(prof, token, "kim@x.kr").json()["next"] == "code"
    assert rows(world, "memberships") == []


def test_no_personal_data_leaks_into_events_or_memberships(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    post_email(world.client(), token, "kim@x.kr")
    assert rows(world, "memberships") == []
    assert all("kim@x.kr" not in str(e) for e in rows(world, "events"))
