"""AC39~AC43, AC48의 서버 쪽: 입장 요청(학생)과 요청 목록·승인·거절(교수). 요청은 이름·학번·이메일만 받는다(C11)."""

import json

from conftest import ORIGIN

from app import authz, events

NOT_IN_ROSTER = (
    "수강생 명단에 없는 이메일입니다. 수강신청에 쓴 이메일인지 확인하고, 계속 안 되면 교수님께 입장을 요청해 주세요."
)
REQUESTED = "요청을 보냈습니다. 교수님이 확인하면 이 이메일로 인증 코드를 받을 수 있습니다."
ALREADY = "이미 요청했습니다. 교수님이 확인할 때까지 기다려 주세요."
REJECTED = "입장 요청이 받아들여지지 않았습니다. 교수님께 문의해 주세요."
DECIDED = "이미 처리한 요청입니다."


def classroom(world, name="웹", owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, token


def ask(client, token, email="new@x.kr", name="박민수", student_no="20249999", **kw):
    return client.post(
        f"/api/join/{token}/request-access",
        json={"email": email, "name": name, "student_no": student_no},
        headers=kw.get("headers", ORIGIN),
    )


def pending(prof, cid):
    res = prof.get(f"/api/classrooms/{cid}/join-requests")
    assert res.status_code == 200
    return res.json()["requests"]


def approve(prof, cid, req):
    return prof.post(f"/api/classrooms/{cid}/join-requests/{req}/approve", headers=ORIGIN)


def reject(prof, cid, req):
    return prof.post(f"/api/classrooms/{cid}/join-requests/{req}/reject", headers=ORIGIN)


def rows(world, table):
    return [dict(r) for r in world.db().execute(f"SELECT * FROM {table}")]


def roster(prof, cid):
    return prof.get(f"/api/classrooms/{cid}/roster").json()["entries"]


def add_to_roster(prof, cid, no, name, email):
    return prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN)


# --- 학생이 요청 보내기 (AC39, AC43) --------------------------------------------------------------------------------


def test_a_request_is_stored_with_only_the_email_name_and_student_no(world):
    _prof, cid, token = classroom(world)
    res = ask(world.client(), token, "  New@X.kr ", " 박민수 ", " 20249999 ")
    assert res.status_code == 201 and res.json() == {"next": "requested", "message": REQUESTED}
    (r,) = rows(world, "join_requests")
    assert (r["classroom_id"], r["email_norm"], r["name"], r["student_no"], r["status"]) == (
        cid, "new@x.kr", "박민수", "20249999", "pending",
    )
    assert r["created_at"] == world.clock.now().isoformat() and r["decided_at"] is None
    # 요청만으로는 명단·계정·코드·메일 어느 것도 생기지 않는다
    for table in ("roster_entries", "accounts", "memberships", "login_challenges", "mail_outbox", "events"):
        assert rows(world, table) == [], table


def test_each_field_is_checked_and_explained_next_to_the_field(world):
    _, _, token = classroom(world)
    cases = [
        ({"email": "nope"}, "email", "이메일 형식을 확인해 주세요."),
        ({"email": ""}, "email", "이메일을 입력해 주세요."),
        ({"name": ""}, "name", "이름을 입력해 주세요."),
        ({"name": "   "}, "name", "이름을 입력해 주세요."),
        ({"student_no": ""}, "student_no", "학번을 입력해 주세요."),
        ({"name": "김" * 101}, "name", "이름은 100자 이하로 입력해 주세요."),
        ({"student_no": "9" * 51}, "student_no", "학번은 50자 이하로 입력해 주세요."),
    ]
    for kwargs, field, message in cases:
        res = ask(world.client(), token, **kwargs)
        assert res.status_code == 422, kwargs
        assert res.json()["detail"] == {"field": field, "message": message}
    assert rows(world, "join_requests") == []


def test_non_text_values_are_a_422_not_a_500(world):
    _, _, token = classroom(world)
    for body in [{}, {"email": 1, "name": 2, "student_no": 3}, {"email": "a@x.kr", "name": None, "student_no": "1"}]:
        res = world.client().post(f"/api/join/{token}/request-access", json=body, headers=ORIGIN)
        assert res.status_code == 422, body


def test_asking_again_with_the_same_email_is_merged_into_one_request(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token, "new@x.kr", "박민수", "1")
    res = ask(world.client(), token, " NEW@x.kr", "다른이름", "2")  # 대소문자·공백이 달라도, 이름이 달라도 같은 요청
    assert res.status_code == 200 and res.json() == {"next": "already_requested", "message": ALREADY}
    (r,) = rows(world, "join_requests")
    assert (r["name"], r["student_no"]) == ("박민수", "1")  # 처음 요청을 그대로 둔다
    assert len(pending(prof, cid)) == 1


def test_a_race_between_two_identical_requests_is_not_a_500(world, monkeypatch):
    import app.join_requests as jr

    _prof, _cid, token = classroom(world)
    ask(world.client(), token)
    monkeypatch.setattr(jr, "latest_request", lambda *_a, **_k: None)  # 둘 다 "아직 없다"고 보고 들어온 경우
    res = ask(world.client(), token)
    assert res.status_code == 200 and res.json()["next"] == "already_requested"
    assert len(rows(world, "join_requests")) == 1


def test_an_email_already_on_the_roster_does_not_need_a_request(world):
    prof, cid, token = classroom(world)
    add_to_roster(prof, cid, "1", "김", "kim@x.kr")
    res = ask(world.client(), token, "kim@x.kr")
    assert res.status_code == 200 and res.json()["next"] == "already_on_roster"
    assert "인증 코드" in res.json()["message"]
    assert rows(world, "join_requests") == []


def test_requests_are_per_classroom(world):
    _prof, _a, token_a = classroom(world, "웹")
    _, _b, token_b = classroom(world, "DB", owner="lee")
    ask(world.client(), token_a)
    assert ask(world.client(), token_b).status_code == 201  # 다른 강좌에는 따로 요청할 수 있다
    assert len(rows(world, "join_requests")) == 2


def test_archived_revoked_and_foreign_origin_are_refused(world):
    _prof, cid, token = classroom(world)
    assert ask(world.client(), token, headers={"Origin": "https://evil.example"}).status_code == 403
    assert ask(world.client(), "made-up-token-0000000").status_code == 404
    world.db().execute("UPDATE classrooms SET status = 'archived', archived_at = '2026-03-01T00:00:00+00:00' WHERE id = ?", (cid,))
    assert ask(world.client(), token).status_code == 403
    assert rows(world, "join_requests") == []


# --- 이메일 단계에서의 요청 상태 (AC42, AC43) ------------------------------------------------------------------------


def test_the_email_step_tells_a_pending_request_apart_from_no_request(world):
    _prof, _cid, token = classroom(world)
    student = world.client()
    first = student.post(f"/api/join/{token}/email", json={"email": "new@x.kr"}, headers=ORIGIN)
    assert first.json() == {"next": "request_access", "message": NOT_IN_ROSTER}
    ask(student, token)
    again = student.post(f"/api/join/{token}/email", json={"email": "new@x.kr"}, headers=ORIGIN)
    assert again.status_code == 200 and again.json() == {"next": "already_requested", "message": ALREADY}
    assert rows(world, "mail_outbox") == []


def test_a_rejected_student_sees_the_rejection_when_opening_again_and_cannot_ask_again(world):
    prof, cid, token = classroom(world)
    student = world.client()
    ask(student, token)
    reject(prof, cid, pending(prof, cid)[0]["id"])
    reopened = student.post(f"/api/join/{token}/email", json={"email": "new@x.kr"}, headers=ORIGIN)
    assert reopened.json() == {"next": "rejected", "message": REJECTED}
    retry = ask(student, token)
    assert retry.status_code == 200 and retry.json() == {"next": "rejected", "message": REJECTED}
    assert len(rows(world, "join_requests")) == 1
    assert student.post(f"/api/join/{token}/resend", json={"email": "new@x.kr"}, headers=ORIGIN).json()["next"] == "rejected"


def test_the_rejection_of_one_email_does_not_affect_another(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token, "a@x.kr", "가", "1")
    reject(prof, cid, pending(prof, cid)[0]["id"])
    assert ask(world.client(), token, "b@x.kr", "나", "2").status_code == 201


def test_after_approval_and_a_later_removal_the_student_can_ask_again(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token)
    approve(prof, cid, pending(prof, cid)[0]["id"])
    world.db().execute("UPDATE roster_entries SET removed_at = ? WHERE classroom_id = ?", (world.clock.now().isoformat(), cid))
    res = ask(world.client(), token)
    assert res.status_code == 201
    assert sorted(r["status"] for r in rows(world, "join_requests")) == ["approved", "pending"]
    again = world.client().post(f"/api/join/{token}/email", json={"email": "new@x.kr"}, headers=ORIGIN)
    assert again.json()["next"] == "already_requested"  # 가장 최근 요청(처리 전)이 기준이다. 오래된 승인 기록이 아니다


# --- 교수의 목록 (AC40) --------------------------------------------------------------------------------------------


def test_the_professor_sees_pending_requests_oldest_first_with_name_student_no_email_and_time(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token, "a@x.kr", "가나다", "1")
    world.clock.advance(minutes=2)
    ask(world.client(), token, "b@x.kr", "라마바", "2")
    res = prof.get(f"/api/classrooms/{cid}/join-requests")
    assert res.headers["cache-control"] == "no-store"
    items = res.json()["requests"]
    assert [(i["name"], i["student_no"], i["email"]) for i in items] == [("가나다", "1", "a@x.kr"), ("라마바", "2", "b@x.kr")]
    assert all({"id", "created_at"} <= set(i) for i in items)
    assert items[0]["created_at"] < items[1]["created_at"]
    assert set(items[0]) == {"id", "name", "student_no", "email", "created_at"}  # 닉네임·상태 등 다른 것은 없다


def test_decided_requests_and_other_classrooms_are_not_listed(world):
    prof, a, token_a = classroom(world, "웹")
    _, _b, token_b = classroom(world, "DB", owner="lee")
    ask(world.client(), token_a, "a@x.kr", "가", "1")
    ask(world.client(), token_a, "b@x.kr", "나", "2")
    ask(world.client(), token_b, "c@x.kr", "다", "3")
    approve(prof, a, pending(prof, a)[0]["id"])
    assert [i["email"] for i in pending(prof, a)] == ["b@x.kr"]


def test_only_the_owner_can_list_approve_or_reject(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token)
    req = pending(prof, cid)[0]["id"]
    lee = world.client("lee")
    assert lee.get(f"/api/classrooms/{cid}/join-requests").status_code == 403
    assert approve(lee, cid, req).status_code == 403 and reject(lee, cid, req).status_code == 403
    anon = world.client()
    assert anon.get(f"/api/classrooms/{cid}/join-requests").status_code == 401
    assert approve(anon, cid, req).status_code == 401
    assert prof.get("/api/classrooms/999/join-requests").status_code == 404
    assert rows(world, "join_requests")[0]["status"] == "pending" and rows(world, "events") == []


# --- 승인 (AC41, AC48) ---------------------------------------------------------------------------------------------


def test_approving_adds_the_student_to_the_roster_but_does_not_let_them_in(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token, "new@x.kr", "박민수", "20249999")
    req = pending(prof, cid)[0]["id"]
    res = approve(prof, cid, req)
    assert res.status_code == 200
    (entry,) = roster(prof, cid)
    assert (entry["student_no"], entry["name"], entry["email"], entry["entered"]) == ("20249999", "박민수", "new@x.kr", False)
    r = rows(world, "join_requests")[0]
    assert r["status"] == "approved" and r["decided_at"] == world.clock.now().isoformat()
    assert pending(prof, cid) == []
    for table in ("accounts", "memberships", "device_logins", "login_challenges", "mail_outbox"):
        assert rows(world, table) == [], table  # 승인만으로 입장되지 않는다


def test_after_approval_the_student_starts_the_normal_entry_from_the_email(world):
    prof, cid, token = classroom(world)
    student = world.client()
    ask(student, token)
    approve(prof, cid, pending(prof, cid)[0]["id"])
    res = student.post(f"/api/join/{token}/email", json={"email": "new@x.kr"}, headers=ORIGIN)
    assert res.json()["next"] == "code"  # 이제 명단에 있으니 정상 절차


def test_approval_is_recorded_as_an_event_with_who_when_and_which_student(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token, "new@x.kr", "박민수", "20249999")
    req = pending(prof, cid)[0]["id"]
    world.clock.advance(minutes=5)
    approve(prof, cid, req)
    (e,) = rows(world, "events")
    entry = roster(prof, cid)[0]
    assert (e["classroom_id"], e["type"], e["actor_kind"], e["actor_ref"], e["subject_roster_entry_id"]) == (
        cid, "join_request_approved", "professor", 101, entry["id"],
    )
    assert json.loads(e["payload"]) == {"request_id": req} and e["created_at"] == world.clock.now().isoformat()
    assert all(secret not in str(e) for secret in ("new@x.kr", "박민수", "20249999"))  # 기록에 개인정보가 없다


def test_approval_fails_with_a_reason_when_the_student_no_or_email_is_already_on_the_roster(world):
    prof, cid, token = classroom(world)
    add_to_roster(prof, cid, "20249999", "다른학생", "other@x.kr")
    ask(world.client(), token, "new@x.kr", "박민수", "20249999")  # 같은 학번
    req = pending(prof, cid)[0]["id"]
    res = approve(prof, cid, req)
    assert res.status_code == 409
    assert res.json()["detail"] == {"field": None, "message": "이미 명단에 있는 학번입니다. 학번을 확인해 주세요."}
    ask(world.client(), token, "taken@x.kr", "최지우", "555")
    add_to_roster(prof, cid, "777", "먼저", "taken@x.kr")  # 요청 뒤에 교수가 같은 이메일을 직접 추가
    taken = next(p for p in pending(prof, cid) if p["email"] == "taken@x.kr")["id"]
    assert approve(prof, cid, taken).json()["detail"]["message"] == "이미 명단에 있는 이메일입니다. 다른 이메일을 입력해 주세요."
    assert [r["status"] for r in rows(world, "join_requests")] == ["pending", "pending"]
    assert rows(world, "events") == [] and len(roster(prof, cid)) == 2  # 아무것도 바뀌지 않았다


def test_approval_respects_the_200_student_limit(world):
    prof, cid, token = classroom(world)
    db = world.db()
    for i in range(199):
        db.execute(
            "INSERT INTO roster_entries(classroom_id, student_no, name, email_norm, created_at) VALUES (?, ?, '학생', ?, ?)",
            (cid, f"f{i}", f"f{i}@x.kr", world.clock.now().isoformat()),
        )
    ask(world.client(), token, "a@x.kr", "가", "1")
    ask(world.client(), token, "b@x.kr", "나", "2")
    first, second = [p["id"] for p in pending(prof, cid)]
    assert approve(prof, cid, first).status_code == 200  # 200명째
    res = approve(prof, cid, second)
    assert res.status_code == 409 and "200명까지" in res.json()["detail"]["message"]
    assert [p["id"] for p in pending(prof, cid)] == [second]


def test_a_decided_request_cannot_be_decided_again(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token, "a@x.kr", "가", "1")
    ask(world.client(), token, "b@x.kr", "나", "2")
    a, b = [p["id"] for p in pending(prof, cid)]
    approve(prof, cid, a)
    reject(prof, cid, b)
    for res in (approve(prof, cid, a), reject(prof, cid, a), approve(prof, cid, b), reject(prof, cid, b)):
        assert res.status_code == 409 and res.json()["detail"] == {"field": None, "message": DECIDED}
    assert len(roster(prof, cid)) == 1 and len(rows(world, "events")) == 2  # 기록이 더 쌓이지 않는다


def test_a_request_of_another_classroom_or_a_missing_one_is_not_found(world):
    prof, a, _token_a = classroom(world, "웹")
    _, b, token_b = classroom(world, "DB", owner="lee")
    ask(world.client(), token_b, "c@x.kr", "다", "3")
    foreign = world.client("lee").get(f"/api/classrooms/{b}/join-requests").json()["requests"][0]["id"]
    assert approve(prof, a, foreign).status_code == 404 and reject(prof, a, foreign).status_code == 404
    assert approve(prof, a, 99999).status_code == 404
    assert rows(world, "join_requests")[0]["status"] == "pending"


def test_a_failure_while_recording_the_event_undoes_the_approval(world, monkeypatch):
    from fastapi.testclient import TestClient

    prof, cid, token = classroom(world)
    ask(world.client(), token)
    req = pending(prof, cid)[0]["id"]

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(events, "record_event", boom)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    assert approve(safe, cid, req).status_code == 500
    assert rows(world, "join_requests")[0]["status"] == "pending" and roster(prof, cid) == []  # 기록 없는 승인은 없다
    assert reject(safe, cid, req).status_code == 500
    assert rows(world, "join_requests")[0]["status"] == "pending"


# --- 거절 (AC42, AC48) ---------------------------------------------------------------------------------------------


def test_rejecting_marks_the_request_records_an_event_and_adds_nobody(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token, "new@x.kr", "박민수", "20249999")
    req = pending(prof, cid)[0]["id"]
    world.clock.advance(minutes=1)
    res = reject(prof, cid, req)
    assert res.status_code == 200
    r = rows(world, "join_requests")[0]
    assert r["status"] == "rejected" and r["decided_at"] == world.clock.now().isoformat()
    assert roster(prof, cid) == [] and pending(prof, cid) == []
    (e,) = rows(world, "events")
    assert (e["type"], e["actor_kind"], e["actor_ref"], e["subject_roster_entry_id"]) == ("join_request_rejected", "professor", 101, None)
    assert json.loads(e["payload"]) == {"request_id": req}
    assert "new@x.kr" not in str(e) and "박민수" not in str(e)


# --- 공통 ------------------------------------------------------------------------------------------------------------


def test_the_professor_routes_are_judged_as_joinrequest_decide_and_the_student_route_as_student_enter(world, monkeypatch):
    prof, cid, token = classroom(world)
    calls = []
    real = authz.decide
    monkeypatch.setattr(authz, "decide", lambda a, action, c: (calls.append(action), real(a, action, c))[1])
    ask(world.client(), token)
    req = pending(prof, cid)[0]["id"]
    approve(prof, cid, req)
    assert calls == [authz.Action.STUDENT_ENTER] + [authz.Action.JOINREQUEST_DECIDE] * 2


def test_decisions_need_the_service_origin(world):
    prof, cid, token = classroom(world)
    ask(world.client(), token)
    req = pending(prof, cid)[0]["id"]
    bad = {"Origin": "https://evil.example"}
    assert prof.post(f"/api/classrooms/{cid}/join-requests/{req}/approve", headers=bad).status_code == 403
    assert prof.post(f"/api/classrooms/{cid}/join-requests/{req}/reject", headers=bad).status_code == 403
    assert rows(world, "join_requests")[0]["status"] == "pending"
