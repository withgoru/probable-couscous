"""AC26, AC27, AC29, AC30~AC34의 서버 쪽: 코드 확인(POST /api/join/{token}/code)과 다시 받기(POST /api/join/{token}/resend).

코드는 실제 경로로 얻는다: 이메일 확인 → 메일 작업자가 보낸 메일 본문에서 6자리를 읽는다.
"""

import re
from datetime import timedelta

from conftest import ORIGIN

from app import authz, nickname_words

NOT_IN_ROSTER = (
    "수강생 명단에 없는 이메일입니다. 수강신청에 쓴 이메일인지 확인하고, 계속 안 되면 교수님께 입장을 요청해 주세요."
)
GENERIC = "코드가 맞지 않습니다."


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
    """이메일 확인을 거쳐 메일로 온 코드를 돌려준다."""
    res = client.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN)
    assert res.status_code == 200 and res.json()["next"] == "code", res.text
    mailer = world.app.state.mailer
    before = len(mailer.sent)
    world.app.state.mail_worker.process_due()
    assert len(mailer.sent) == before + 1
    return re.search(r"\b(\d{6})\b", mailer.sent[-1].text).group(1)


def submit(client, token, code, email="kim@x.kr", **extra):
    return client.post(f"/api/join/{token}/code", json={"email": email, "code": code, **extra}, headers=ORIGIN)


def rows(world, table):
    return [dict(r) for r in world.db().execute(f"SELECT * FROM {table}")]


def other(code):
    return "000000" if code != "000000" else "111111"


# --- 맞는 코드: 계정, 멤버십, 닉네임 (AC27, AC29) -----------------------------------------------------


def test_the_right_code_creates_the_account_membership_nickname_and_link(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    res = submit(student, token, code)
    assert res.status_code == 200
    body = res.json()
    assert body["next"] == "notice" and body["nickname"]
    (account,) = rows(world, "accounts")
    assert account["email_norm"] == "kim@x.kr"
    (membership,) = rows(world, "memberships")
    assert (membership["classroom_id"], membership["nickname"]) == (cid, body["nickname"])
    (link,) = rows(world, "member_identities")
    assert (link["membership_id"], link["classroom_id"], link["account_id"], link["roster_entry_id"]) == (
        membership["id"], cid, account["id"], entry,
    )
    assert rows(world, "login_challenges")[0]["status"] == "used"


def test_the_nickname_comes_from_the_word_lists_and_the_membership_holds_no_personal_data(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    nickname = submit(student, token, request_code(world, student, token)).json()["nickname"]
    adjective, noun = nickname.split(" ")
    assert adjective in nickname_words.ADJECTIVES and noun in nickname_words.NOUNS
    (membership,) = rows(world, "memberships")
    assert "kim" not in str(membership) and "김철수" not in str(membership)  # C7


def test_each_student_gets_a_different_nickname_in_the_classroom(world):
    prof, cid, token = classroom(world)
    names = set()
    for i in range(12):
        enroll(prof, cid, no=str(i), name=f"학생{i}", email=f"s{i}@x.kr")
        world.clock.advance(seconds=1)  # 메일은 초당 8건까지만 나간다
        student = world.client()
        code = request_code(world, student, token, f"s{i}@x.kr")
        names.add(submit(student, token, code, f"s{i}@x.kr").json()["nickname"])
    assert len(names) == 12


def test_the_response_never_contains_the_email_name_or_student_no(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid, no="20240001", name="김철수", email="kim@x.kr")
    student = world.client()
    res = submit(student, token, request_code(world, student, token))
    for secret in ("kim@x.kr", "김철수", "20240001"):
        assert secret not in res.text


def test_the_email_in_the_request_may_have_spaces_and_capitals(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token, "KIM@x.kr")
    assert submit(student, token, code, "  Kim@X.kr ").status_code == 200


# --- 같은 학생이 다시 입장 (AC29, AC34) -------------------------------------------------------------------


def test_the_same_email_entering_again_is_the_same_membership_and_nickname(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    first_device = world.client()
    first = submit(first_device, token, request_code(world, first_device, token)).json()["nickname"]
    world.clock.advance(minutes=30)
    new_device = world.client()  # 다른 기기에서 다시 입장
    second = submit(new_device, token, request_code(world, new_device, token)).json()["nickname"]
    assert first == second
    assert len(rows(world, "accounts")) == len(rows(world, "memberships")) == len(rows(world, "member_identities")) == 1


def test_one_account_is_shared_across_classrooms_but_each_classroom_has_its_own_membership(world):
    prof, a, token_a = classroom(world, "웹")
    _, b, token_b = classroom(world, "DB", owner="lee")
    enroll(prof, a)
    world.client("lee").post(f"/api/classrooms/{b}/roster", json={"student_no": "1", "name": "김", "email": "kim@x.kr"}, headers=ORIGIN)
    student = world.client()
    submit(student, token_a, request_code(world, student, token_a))
    world.clock.advance(minutes=1)
    submit(student, token_b, request_code(world, student, token_b))
    assert len(rows(world, "accounts")) == 1
    memberships = rows(world, "memberships")
    assert sorted(m["classroom_id"] for m in memberships) == sorted([a, b])
    assert len(rows(world, "member_identities")) == 2


def test_a_student_removed_and_added_again_keeps_the_membership(world):
    prof, cid, token = classroom(world)
    old = enroll(prof, cid)
    student = world.client()
    first = submit(student, token, request_code(world, student, token)).json()["nickname"]
    world.db().execute("UPDATE roster_entries SET removed_at = '2026-03-01T10:00:00+00:00' WHERE id = ?", (old,))
    new = enroll(prof, cid)  # 같은 이메일로 다시 등록
    world.clock.advance(minutes=30)
    again = world.client()
    second = submit(again, token, request_code(world, again, token)).json()["nickname"]
    assert first == second
    (link,) = rows(world, "member_identities")
    assert link["roster_entry_id"] == new  # 지금의 명단 항목에 이어진다


# --- 로그인 유지 선택값 (AC26) --------------------------------------------------------------------------------


def test_keeping_the_login_is_stored_and_the_cookie_lasts(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    res = submit(student, token, request_code(world, student, token), keep_login=True)
    (login,) = rows(world, "device_logins")
    assert login["persistent"] == 1 and login["expires_at"] is None and login["revoked_at"] is None
    assert login["account_id"] == rows(world, "accounts")[0]["id"] and login["device_id"] == rows(world, "devices")[0]["id"]
    header = res.headers["set-cookie"].lower()
    assert "student_login=" in header and "httponly" in header and "samesite=lax" in header and "max-age=" in header


def test_keep_login_is_on_when_the_choice_is_not_sent(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    submit(student, token, request_code(world, student, token))
    assert rows(world, "device_logins")[0]["persistent"] == 1


def test_turning_keep_login_off_gives_a_session_cookie_and_a_one_day_limit(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    res = submit(student, token, request_code(world, student, token), keep_login=False)
    (login,) = rows(world, "device_logins")
    assert login["persistent"] == 0
    assert login["expires_at"] == (world.clock.now() + timedelta(hours=24)).isoformat()  # 24시간 안전 상한
    header = res.headers["set-cookie"].lower()
    assert "student_login=" in header and "max-age" not in header and "expires" not in header  # 브라우저를 닫으면 사라진다


def test_the_login_token_is_stored_only_as_a_hash(world):
    from app.auth import hash_token

    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    submit(student, token, request_code(world, student, token))
    cookie = student.cookies["student_login"]
    (login,) = rows(world, "device_logins")
    assert login["token_hash"] == hash_token(cookie) and cookie not in str(login)


def test_a_wrong_code_creates_no_login_and_no_cookie(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    res = submit(student, token, other(code))
    assert "student_login" not in res.headers.get("set-cookie", "")
    assert rows(world, "device_logins") == [] and rows(world, "memberships") == [] and rows(world, "accounts") == []


# --- 틀린 코드, 횟수, 만료 (AC30, AC31) ----------------------------------------------------------------------------


def test_wrong_codes_say_how_many_tries_are_left_and_the_fifth_locks_the_code(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    for left in (4, 3, 2, 1):
        res = submit(student, token, other(code))
        assert res.status_code == 422
        assert res.json()["detail"] == {
            "field": "code",
            "message": f"코드가 맞지 않습니다. {left}번 더 입력할 수 있습니다.",
            "outcome": "wrong",
            "remaining": left,
        }
    last = submit(student, token, other(code))
    assert last.json()["detail"]["message"] == "코드를 다시 받아 주세요." and last.json()["detail"]["outcome"] == "locked"
    assert submit(student, token, code).status_code == 422  # 잠긴 뒤에는 맞는 코드도 받지 않는다
    assert rows(world, "memberships") == []


def test_an_expired_code_says_so(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    world.clock.advance(minutes=10)
    res = submit(student, token, code)
    assert res.status_code == 422
    assert res.json()["detail"]["message"] == "코드가 만료되었습니다. 코드를 다시 받아 주세요."
    assert res.json()["detail"]["outcome"] == "expired"


def test_a_code_that_is_not_six_digits_is_explained_without_using_a_try(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    for bad in ["123", "abcdef", "", "1234567"]:
        res = submit(student, token, bad)
        assert res.status_code == 422 and res.json()["detail"]["outcome"] == "bad_format"
    assert rows(world, "login_challenges")[0]["attempts"] == 0
    assert submit(student, token, code).status_code == 200


def test_non_text_values_are_a_422_not_a_500(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    request_code(world, student, token)
    for body in [{}, {"email": "kim@x.kr"}, {"code": "123456"}, {"email": 5, "code": 1}, {"email": "kim@x.kr", "code": None}]:
        res = student.post(f"/api/join/{token}/code", json=body, headers=ORIGIN)
        assert res.status_code == 422, body


def test_a_used_code_cannot_be_used_again(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    assert submit(student, token, code).status_code == 200
    again = submit(student, token, code)
    assert again.status_code == 422
    assert again.json()["detail"]["message"] == "이미 사용된 코드입니다. 코드를 다시 받아 주세요."
    assert len(rows(world, "memberships")) == 1


# --- 요청한 기기에서만 (AC33) ---------------------------------------------------------------------------------------


def test_another_device_gets_the_generic_message_and_the_requesting_device_is_unaffected(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    mine = world.client()
    code = request_code(world, mine, token)
    elsewhere = world.client()
    elsewhere.get(f"/api/join/{token}")  # 다른 기기: 링크를 열어 자기 기기 쿠키를 받았다
    res = submit(elsewhere, token, code)
    assert res.status_code == 422
    assert res.json()["detail"]["message"] == GENERIC and res.json()["detail"]["remaining"] is None
    for _ in range(10):
        submit(elsewhere, token, code)
    assert rows(world, "login_challenges")[0]["attempts"] == 0
    assert rows(world, "memberships") == []
    assert submit(mine, token, code).status_code == 200  # 요청한 기기는 그대로 입장한다


def test_a_client_without_a_device_cookie_gets_the_generic_message_and_creates_no_device(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    request_code(world, world.client(), token)
    before = len(rows(world, "devices"))
    cookieless = world.client()
    res = submit(cookieless, token, "123456")
    assert res.status_code == 422 and res.json()["detail"]["message"] == GENERIC
    assert len(rows(world, "devices")) == before


def test_a_code_is_bound_to_its_email(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid, email="kim@x.kr")
    enroll(prof, cid, no="2", name="이", email="lee@x.kr")
    student = world.client()
    code = request_code(world, student, token, "kim@x.kr")
    res = submit(student, token, code, "lee@x.kr")  # 같은 기기에서 다른 이메일로 확인하려 해도
    assert res.status_code == 422 and res.json()["detail"]["message"] == GENERIC
    assert rows(world, "memberships") == []


# --- 명단에서 사라진 경우, 막아야 할 때 -------------------------------------------------------------------------------


def test_a_student_removed_from_the_roster_after_asking_is_sent_to_request_access(world):
    prof, cid, token = classroom(world)
    entry = enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    world.db().execute("UPDATE roster_entries SET removed_at = '2026-03-01T10:00:00+00:00' WHERE id = ?", (entry,))
    res = submit(student, token, code)
    assert res.status_code == 200 and res.json() == {"next": "request_access", "message": NOT_IN_ROSTER}
    assert rows(world, "memberships") == [] and rows(world, "accounts") == []


def test_archived_and_revoked_links_refuse_the_code_step(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    prof.post(f"/api/classrooms/{cid}/invite/regenerate", headers=ORIGIN)
    res = submit(student, token, code)
    assert res.status_code == 404 and "더 이상 사용할 수 없습니다" in res.json()["detail"]
    new_token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    world.db().execute("UPDATE classrooms SET status = 'archived', archived_at = '2026-03-01T00:00:00+00:00' WHERE id = ?", (cid,))
    assert submit(student, new_token, code).status_code == 403
    assert rows(world, "memberships") == []


def test_the_service_origin_is_required(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    res = student.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": code}, headers={"Origin": "https://evil.example"})
    assert res.status_code == 403 and rows(world, "memberships") == []


def test_a_failure_while_creating_the_membership_does_not_use_up_the_code(world, monkeypatch):
    from fastapi.testclient import TestClient

    from app import identity

    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    code = request_code(world, student, token)

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(identity, "membership_for", boom)
    assert submit(student, token, code).status_code == 500
    assert rows(world, "login_challenges")[0]["status"] == "active"  # 코드는 쓰이지 않았다
    assert rows(world, "accounts") == [] and rows(world, "device_logins") == []
    monkeypatch.undo()
    assert submit(student, token, code).status_code == 200  # 다시 입력하면 입장된다


def test_both_routes_are_judged_as_student_enter_actions(world, monkeypatch):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    submit(student, token, code)
    world.clock.advance(seconds=60)
    student.post(f"/api/join/{token}/resend", json={"email": "kim@x.kr"}, headers=ORIGIN)
    assert calls == [authz.Action.STUDENT_ENTER] * 2


# --- 코드 다시 받기 (AC32) ---------------------------------------------------------------------------------------------


def resend(client, token, email="kim@x.kr"):
    return client.post(f"/api/join/{token}/resend", json={"email": email}, headers=ORIGIN)


def test_resend_within_60_seconds_is_refused_with_the_seconds_left(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    request_code(world, student, token)
    world.clock.advance(seconds=15)
    res = resend(student, token)
    assert res.status_code == 429
    assert res.json()["detail"] == {"field": None, "message": "코드는 45초 뒤에 다시 받을 수 있습니다.", "wait_seconds": 45}
    assert len(rows(world, "login_challenges")) == 1 and len(rows(world, "mail_outbox")) == 1


def test_after_60_seconds_resend_sends_a_new_code_and_the_old_one_stops_working(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    old = request_code(world, student, token)
    world.clock.advance(seconds=60)
    res = resend(student, token)
    assert res.status_code == 200 and res.json() == {"next": "code", "wait_seconds": 60}
    world.app.state.mail_worker.process_due()
    new = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    assert new != old  # 난수가 다르다(우연히 같을 확률은 100만분의 1)
    assert [c["status"] for c in rows(world, "login_challenges")] == ["superseded", "active"]
    assert submit(student, token, old).status_code == 422  # 이전 코드는 쓸 수 없다
    assert submit(student, token, new).status_code == 200


def test_resend_for_an_email_not_in_the_roster_sends_nothing(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    res = resend(world.client(), token, "stranger@x.kr")
    assert res.status_code == 200 and res.json() == {"next": "request_access", "message": NOT_IN_ROSTER}
    assert rows(world, "mail_outbox") == []


def test_resend_checks_the_email_format_like_the_first_request(world):
    _, _, token = classroom(world)
    res = resend(world.client(), token, "nope")
    assert res.status_code == 422 and res.json()["detail"]["field"] == "email"


def test_a_keep_login_value_that_is_not_true_or_false_counts_as_the_default_on(world):
    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    submit(student, token, request_code(world, student, token), keep_login=None)
    assert rows(world, "device_logins")[0]["persistent"] == 1


def test_the_login_cookie_is_secure_when_the_service_uses_https(world):
    import dataclasses

    from fastapi.testclient import TestClient

    from app.main import create_app

    prof, cid, token = classroom(world)
    enroll(prof, cid)
    student = world.client()
    code = request_code(world, student, token)
    # 같은 DB를 https 주소로 서비스하는 앱. 요청한 기기의 쿠키를 그대로 들고 온다
    https_app = create_app(
        dataclasses.replace(world.settings, base_url="https://class.example.kr"), clock=world.clock, start_mail_worker=False
    )
    with TestClient(https_app, base_url="https://class.example.kr") as secure_client:
        for cookie in student.cookies.jar:
            secure_client.cookies.set(cookie.name, cookie.value, domain="class.example.kr")
        res = secure_client.post(
            f"/api/join/{token}/code",
            json={"email": "kim@x.kr", "code": code},
            headers={"Origin": "https://class.example.kr"},
        )
    assert res.status_code == 200 and "secure" in res.headers["set-cookie"].lower()
