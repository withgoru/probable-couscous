"""AC28, AC35, AC36, AC37(그리고 AC10, AC20의 입장 쪽): 입장 확정(POST /enter), 내 상태(GET /me), 로그인 유지, 다른 강좌 입장."""

import re

from conftest import ORIGIN

from app import authz

ARCHIVED = "이 강좌는 보관되었습니다. 교수님께 문의해 주세요."
NOT_LOGGED_IN = "입장 인증이 끝나지 않았습니다. 이메일과 코드로 먼저 인증해 주세요."
NOT_ON_ROSTER = "이 강좌의 수강생 명단에 없습니다. 교수님께 문의해 주세요."


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def enroll(prof, cid, no="1", name="김철수", email="kim@x.kr"):
    r = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)
    assert r.status_code == 201
    return r.json()["id"]


def verify_by_code(world, client, token, email="kim@x.kr", **extra):
    """이메일 확인과 코드 확인까지 끝낸 기기. 코드 응답을 돌려준다."""
    assert client.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"
    mailer = world.app.state.mailer
    before = len(mailer.sent)
    world.app.state.mail_worker.process_due()
    assert len(mailer.sent) == before + 1
    code = re.search(r"\b(\d{6})\b", mailer.sent[-1].text).group(1)
    res = client.post(f"/api/join/{token}/code", json={"email": email, "code": code, **extra}, headers=ORIGIN)
    assert res.status_code == 200, res.text
    return res.json()


def me(client, token):
    return client.get(f"/api/join/{token}/me")


def enter(client, token):
    return client.post(f"/api/join/{token}/enter", headers=ORIGIN)


def reopen(world, client, keep=("device", "student_login")):
    """브라우저를 닫았다 다시 연 것처럼, 남기는 쿠키만 가진 새 클라이언트."""
    fresh = world.client()
    for cookie in client.cookies.jar:
        if cookie.name in keep:
            fresh.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    return fresh


def rows(world, table):
    return [dict(r) for r in world.db().execute(f"SELECT * FROM {table}")]


def verified_student(world, name="웹", **extra):
    prof, cid, token = classroom(world, name)
    enroll(prof, cid)
    student = world.client()
    nickname = verify_by_code(world, student, token, **extra)["nickname"]
    return prof, cid, token, student, nickname


# --- 코드 직후: 안내 화면 단계, 입장 확정 (AC28) -----------------------------------------------------------------


def test_after_the_code_the_state_is_the_notice_step_with_the_nickname_and_not_yet_entered(world):
    _, _cid, token, student, nickname = verified_student(world)
    res = me(student, token)
    assert res.status_code == 200
    assert res.json() == {"state": "notice", "nickname": nickname, "classroom": "웹"}
    assert rows(world, "classroom_verifications") == []  # 아직 입장하지 않았다


def test_confirming_enters_and_me_shows_the_classroom_and_nickname(world):
    _, cid, token, student, nickname = verified_student(world)
    res = enter(student, token)
    assert res.status_code == 200
    assert res.json() == {"next": "entered", "nickname": nickname, "classroom": "웹"}
    assert me(student, token).json() == {"state": "entered", "nickname": nickname, "classroom": "웹"}
    (v,) = rows(world, "classroom_verifications")
    login = rows(world, "device_logins")[0]
    membership = rows(world, "memberships")[0]
    assert (v["device_login_id"], v["classroom_id"], v["membership_id"]) == (login["id"], cid, membership["id"])
    assert v["verified_at"] == world.clock.now().isoformat()
    assert membership["notice_ack_at"] == world.clock.now().isoformat()  # 채팅 이용 안내를 확인했다


def test_entering_twice_changes_nothing(world):
    _, _cid, token, student, nickname = verified_student(world)
    enter(student, token)
    acknowledged = rows(world, "memberships")[0]["notice_ack_at"]
    world.clock.advance(minutes=5)
    again = enter(student, token)
    assert again.status_code == 200 and again.json()["nickname"] == nickname
    assert len(rows(world, "classroom_verifications")) == 1 and len(rows(world, "memberships")) == 1
    assert rows(world, "memberships")[0]["notice_ack_at"] == acknowledged  # 처음 확인한 시각을 유지한다
    assert rows(world, "classroom_verifications")[0]["verified_at"] == acknowledged  # 입장 기록도 처음 것 그대로


def test_no_personal_data_in_any_student_response(world):
    _, _cid, token, student, _ = verified_student(world)
    for res in (me(student, token), enter(student, token), me(student, token)):
        for secret in ("kim@x.kr", "김철수"):
            assert secret not in res.text


def test_me_sets_no_cookies_and_enter_sets_none_either(world):
    _, _cid, token, student, _ = verified_student(world)
    assert "set-cookie" not in me(student, token).headers
    assert "set-cookie" not in enter(student, token).headers


# --- 로그인 유지 (AC35, AC36) ---------------------------------------------------------------------------------------


def test_with_keep_login_the_same_device_enters_again_without_a_code_for_as_long_as_the_classroom_is_active(world):
    _, _cid, token, student, nickname = verified_student(world, keep_login=True)
    enter(student, token)
    for days in (1, 30, 200):
        world.clock.advance(days=days)
        back = reopen(world, student)  # 브라우저를 닫았다 다시 열어도
        assert me(back, token).json() == {"state": "entered", "nickname": nickname, "classroom": "웹"}
    assert len(rows(world, "login_challenges")) == 1  # 새 코드를 받지 않았다


def test_without_keep_login_closing_the_browser_means_starting_from_the_email_again(world):
    _, _cid, token, student, _ = verified_student(world, keep_login=False)
    enter(student, token)
    closed = reopen(world, student, keep=("device",))  # 세션 쿠키는 브라우저를 닫으면 사라진다
    assert me(closed, token).json() == {"state": "login"}


def test_without_keep_login_the_server_also_stops_trusting_the_login_after_24_hours(world):
    _, _cid, token, student, _nickname = verified_student(world, keep_login=False)
    enter(student, token)
    world.clock.advance(hours=23, minutes=59)
    assert me(student, token).json()["state"] == "entered"
    world.clock.advance(minutes=1)
    assert me(student, token).json() == {"state": "login"}  # 쿠키를 지우지 않아도 24시간이 상한이다
    assert enter(student, token).status_code == 401


def test_a_login_that_was_ended_on_the_server_is_no_longer_good(world):
    _, _cid, token, student, _ = verified_student(world)
    enter(student, token)
    world.db().execute("UPDATE device_logins SET revoked_at = ?", (world.clock.now().isoformat(),))
    assert me(student, token).json() == {"state": "login"}
    assert enter(student, token).status_code == 401


# --- 이 기기여야 한다 -----------------------------------------------------------------------------------------------


def test_a_visitor_with_no_cookies_is_asked_to_log_in(world):
    _, _, token = classroom(world)
    assert me(world.client(), token).json() == {"state": "login"}


def test_the_login_cookie_alone_without_its_device_cookie_is_not_enough(world):
    _, _cid, token, student, _ = verified_student(world)
    enter(student, token)
    only_login = reopen(world, student, keep=("student_login",))
    assert me(only_login, token).json() == {"state": "login"}
    assert enter(only_login, token).status_code == 401


def test_a_login_cookie_used_with_another_devices_cookie_is_not_enough(world):
    _, _cid, token, student, _ = verified_student(world)
    enter(student, token)
    thief = world.client()
    thief.get(f"/api/join/{token}")  # 자기 기기 쿠키를 받는다
    thief.cookies.set("student_login", student.cookies["student_login"], domain=thief.cookies.jar.__iter__().__next__().domain, path="/")
    assert me(thief, token).json() == {"state": "login"}
    assert enter(thief, token).status_code == 401
    assert len(rows(world, "classroom_verifications")) == 1  # 진짜 학생의 기록뿐이다


def test_entering_needs_a_login_and_stores_nothing_without_one(world):
    _, _, token = classroom(world)
    res = enter(world.client(), token)
    assert res.status_code == 401 and res.json() == {"detail": NOT_LOGGED_IN}
    assert rows(world, "classroom_verifications") == [] and rows(world, "memberships") == []


# --- 다른 강좌 (AC37) -----------------------------------------------------------------------------------------------


def test_an_authenticated_device_opening_another_classrooms_link_goes_to_the_notice_without_a_code(world):
    _prof, a, token_a, student, _nick_a = verified_student(world, "웹")
    enter(student, token_a)
    world.clock.advance(minutes=3)
    _, b, token_b = classroom(world, "DB", owner="lee")
    enroll(world.client("lee"), b)  # 그 강좌 명단에도 같은 이메일이 있다
    res = me(student, token_b)
    assert res.status_code == 200
    body = res.json()
    assert body["state"] == "notice" and body["classroom"] == "DB" and body["nickname"]  # 이메일·코드 없이 안내 화면 단계
    assert len(rows(world, "login_challenges")) == 1 and len(rows(world, "mail_outbox")) == 1
    memberships = sorted(rows(world, "memberships"), key=lambda m: m["classroom_id"])
    assert [m["classroom_id"] for m in memberships] == sorted([a, b]) and len({m["id"] for m in memberships}) == 2  # 새 멤버십
    assert len(rows(world, "accounts")) == 1  # 계정은 하나


def test_the_other_classroom_is_not_entered_until_the_student_confirms(world):
    _prof, a, token_a, student, _ = verified_student(world, "웹")
    enter(student, token_a)
    _, b, token_b = classroom(world, "DB", owner="lee")
    enroll(world.client("lee"), b)
    assert me(student, token_b).json()["state"] == "notice"
    assert rows(world, "classroom_verifications")[0]["classroom_id"] == a  # 아직 그 강좌 기록이 없다
    res = enter(student, token_b)
    assert res.status_code == 200 and res.json()["classroom"] == "DB"
    assert me(student, token_b).json()["state"] == "entered"
    assert me(student, token_a).json()["state"] == "entered"  # 처음 강좌도 그대로
    assert sorted(v["classroom_id"] for v in rows(world, "classroom_verifications")) == sorted([a, b])


def test_the_nickname_in_the_other_classroom_is_issued_on_its_own_and_stays_the_same_afterwards(world):
    _prof, _a, _token_a, student, _ = verified_student(world, "웹")
    _, b, token_b = classroom(world, "DB", owner="lee")
    enroll(world.client("lee"), b)
    first = me(student, token_b).json()["nickname"]
    assert me(student, token_b).json()["nickname"] == first  # 열 때마다 새로 만들지 않는다
    assert len([m for m in rows(world, "memberships") if m["classroom_id"] == b]) == 1


def test_a_classroom_that_does_not_have_the_student_on_its_roster_still_asks_for_the_email(world):
    _prof, _a, token_a, student, _ = verified_student(world, "웹")
    enter(student, token_a)
    _, b, token_b = classroom(world, "DB", owner="lee")  # 이 강좌 명단에는 없다
    assert me(student, token_b).json() == {"state": "login"}
    assert len([m for m in rows(world, "memberships") if m["classroom_id"] == b]) == 0
    assert enter(student, token_b).status_code == 403
    assert enter(student, token_b).json() == {"detail": NOT_ON_ROSTER}


def test_a_student_removed_from_the_roster_cannot_use_the_remembered_login(world):
    _prof, cid, token, student, _ = verified_student(world)
    enter(student, token)
    world.db().execute("UPDATE roster_entries SET removed_at = ? WHERE classroom_id = ?", (world.clock.now().isoformat(), cid))
    assert me(student, token).json() == {"state": "login"}
    assert enter(student, token).status_code == 403


# --- 로그인 끊기 이후 (AC20의 입장 쪽) ----------------------------------------------------------------------------------


def test_after_a_forced_logout_the_student_must_verify_by_email_again_and_keeps_the_nickname(world):
    _prof, _cid, token, student, nickname = verified_student(world)
    enter(student, token)
    world.clock.advance(minutes=10)
    world.db().execute("UPDATE memberships SET reverify_after = ?", (world.clock.now().isoformat(),))  # 교수가 로그인을 끊은 시각
    assert me(student, token).json() == {"state": "login"}
    assert enter(student, token).status_code == 401
    world.clock.advance(minutes=1)
    again = verify_by_code(world, student, token)
    assert again["nickname"] == nickname  # 다시 입장해도 닉네임은 같다
    assert me(student, token).json()["state"] == "notice"
    assert enter(student, token).json()["nickname"] == nickname
    assert me(student, token).json()["state"] == "entered"


def test_a_device_that_entered_before_the_cut_is_not_let_in_by_an_old_verification_record(world):
    _prof, _cid, token, student, _ = verified_student(world)
    enter(student, token)
    world.clock.advance(seconds=1)
    world.db().execute("UPDATE memberships SET reverify_after = ?", (world.clock.now().isoformat(),))
    assert me(student, token).json()["state"] == "login"  # 입장 기록은 있어도 끊긴 뒤에 인증한 기기가 아니다


# --- 막아야 할 때 -----------------------------------------------------------------------------------------------------


def test_an_archived_classroom_refuses_even_a_remembered_login(world):
    _prof, cid, token, student, _ = verified_student(world)
    enter(student, token)
    world.db().execute("UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ?", (world.clock.now().isoformat(), cid))
    for res in (me(student, token), enter(student, token)):
        assert res.status_code == 403 and res.json() == {"detail": ARCHIVED}


def test_a_revoked_or_made_up_link_gets_the_same_404(world):
    prof, cid, token, student, _ = verified_student(world)
    enter(student, token)
    prof.post(f"/api/classrooms/{cid}/invite/regenerate", headers=ORIGIN)
    for t in (token, "made-up-token-0000000"):
        for res in (me(student, t), enter(student, t)):
            assert res.status_code == 404 and "더 이상 사용할 수 없습니다" in res.json()["detail"]


def test_entering_needs_the_service_origin(world):
    _, _cid, token, student, _ = verified_student(world)
    res = student.post(f"/api/join/{token}/enter", headers={"Origin": "https://evil.example"})
    assert res.status_code == 403 and rows(world, "classroom_verifications") == []


def test_both_routes_are_judged_as_student_enter_actions(world, monkeypatch):
    _, _cid, token, student, _ = verified_student(world)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    me(student, token)
    enter(student, token)
    assert calls == [authz.Action.STUDENT_ENTER] * 2


def test_a_failure_while_entering_leaves_no_half_finished_record(world, monkeypatch):
    from fastapi.testclient import TestClient

    from app import student_login

    _, _cid, token, student, _ = verified_student(world)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in student.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(student_login, "record_verification", boom)
    assert enter(safe, token).status_code == 500
    assert rows(world, "classroom_verifications") == []
    assert rows(world, "memberships")[0]["notice_ack_at"] is None  # 안내 확인만 남지 않는다
    monkeypatch.undo()
    assert enter(safe, token).status_code == 200


def test_a_professor_session_does_not_make_a_student(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    assert me(prof, token).json() == {"state": "login"}  # 교수 로그인은 학생 입장과 무관하다
    assert enter(prof, token).status_code == 401


def test_a_forced_time_window_in_the_future_is_not_confused_with_an_earlier_login(world):
    # 끊은 시각과 로그인 시각이 같은 순간이면 끊긴 뒤에 인증한 것이 아니다(경계는 끊김 쪽)
    _, _cid, token, student, _ = verified_student(world)
    cut = rows(world, "device_logins")[0]["created_at"]
    world.db().execute("UPDATE memberships SET reverify_after = ?", (cut,))
    assert me(student, token).json()["state"] == "login"


def test_the_student_is_found_by_the_email_of_the_logged_in_account_not_by_a_fixed_one(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid, no="7", name="이영희", email="lee@x.kr")
    student = world.client()
    nickname = verify_by_code(world, student, token, "lee@x.kr")["nickname"]
    assert me(student, token).json() == {"state": "notice", "nickname": nickname, "classroom": "웹"}
    assert enter(student, token).json()["nickname"] == nickname
