"""003 T013(C13): 출석을 받는 중에 서버 프로세스가 갑자기 죽어도(SIGKILL) 출석이 그대로 남는다.

001 `test_restart_process.py`, 002 `test_restart_class.py`와 같이 실제 uvicorn 프로세스를 띄워 출석을 받은 뒤
강제로 죽이고, 같은 DB로 새 프로세스를 띄워 확인한다(스펙 오류 표 "서버를 다시 시작함").

- 창의 마감 시각(연장한 값), 코드 출석, 수기 요청과 그 처리(승인·거절)가 남는다. 대기 요청은 재시작 뒤에도 처리할 수 있다.
- 마감한 창은 재시작 뒤에도 닫혀 있다.
- 같은 15초 칸의 코드가 재시작 전과 같다(코드는 저장하지 않고 창의 난수와 서버 비밀값으로 계산한다).
- 재시작 뒤에도 바로 앞 칸의 코드를 받는다. 같은 누름의 재전송은 처음과 같은 답이다.
"""

import re
import sqlite3
import time
from datetime import UTC, datetime

import pytest
from test_restart_class import login
from test_restart_process import SCRIPT, Process, free_port, servers  # noqa: F401  (servers는 fixture)

from app.attendance_core import compute_attendance_code, slot_bounds, slot_of

SECRET = "restart-test"  # test_restart_process.SCRIPT의 server_secret
EMAILS = ("s1@x.kr", "s2@x.kr", "s3@x.kr", "s4@x.kr", "s5@x.kr")
CLOSED = "출석 시간이 끝났습니다. 교수님께 수기 출석을 요청하세요."
ALREADY_DECIDED = "이미 처리한 요청입니다."


def test_the_secret_matches_the_test_server_script():
    # previous_slot_code가 서버와 같은 비밀값으로 계산하는지(SCRIPT의 값이 바뀌면 여기서 알린다)
    assert f'server_secret="{SECRET}"' in SCRIPT


def decide(prof, cid, rid, what):
    return prof.post(f"/api/classrooms/{cid}/attendance-requests/{rid}/{what}")


def live_attendance(client, cid, sid):
    res = client.get(f"/api/class/{cid}/sessions/{sid}/live")
    assert res.status_code == 200, res.text
    mine = res.json()["attendance"]
    return {"status": mine["status"], "request": mine["request"]}


def restart(servers, old, port, db):  # noqa: F811
    old.kill()  # 답을 받은 뒤 바로 죽인다. 종료 처리는 없다
    new = Process(port, db)
    servers.append(new)
    return new


def enter(server, token, email):
    """002 `enter`와 같지만, 여러 학생이 차례로 들어오므로 앞 학생의 메일이 아닌 새 메일을 기다린다."""
    student = server.client()
    assert student.get(f"/api/join/{token}").status_code == 200  # 기기 쿠키
    previous = student.get("/api/test/last-mail").json()["text"]
    assert student.post(f"/api/join/{token}/email", json={"email": email}).json()["next"] == "code"
    deadline = time.monotonic() + 10  # 메일 작업 스레드가 보낼 때까지
    while (text := student.get("/api/test/last-mail").json()["text"]) == previous and time.monotonic() < deadline:
        time.sleep(0.1)
    assert text != previous, "인증 메일이 10초 안에 오지 않았습니다"
    code = re.search(r"\b(\d{6})\b", text).group(1)
    assert student.post(f"/api/join/{token}/code", json={"email": email, "code": code}).status_code == 200
    assert student.post(f"/api/join/{token}/enter").status_code == 200
    return student


def code_url(cid, sid):
    return f"/api/classrooms/{cid}/sessions/{sid}/attendance/code"


def check_in(student, cid, sid, code, key):
    return student.post(f"/api/class/{cid}/sessions/{sid}/attendance", json={"code": code, "client_key": key})


def codes_by_slot_end(body):
    """코드 응답을 {칸이 끝나는 시각: 코드}로. 재시작 전후의 같은 칸을 끝나는 시각으로 맞춘다."""
    return {body[k]["ends_at"]: body[k]["code"] for k in ("current", "next")}


def table(prof, cid, sid):
    res = prof.get(f"/api/classrooms/{cid}/sessions/{sid}/attendance")
    assert res.status_code == 200, res.text
    body = res.json()
    return {
        "present": body["present"],
        "students": {s["student_no"]: (s["status"], s["source"], s["at"]) for s in body["students"]},
        "requests": [(r["student_no"], r["reason"]) for r in body["requests"]],
    }


def window_row(db_path, sid):
    db = sqlite3.connect(db_path)
    db.row_factory = sqlite3.Row
    try:
        return dict(db.execute(
            "SELECT id, nonce FROM attendance_windows WHERE session_id = ? ORDER BY id DESC LIMIT 1", (sid,)
        ).fetchone())
    finally:
        db.close()


def previous_slot_code(window):
    """지금 칸 바로 앞 칸의 코드. 칸 경계 2초 안이면 다음 칸까지 기다려, 보내는 사이 칸이 넘어가지 않게 한다."""
    now = datetime.now(UTC)
    if (slot_bounds(slot_of(now))[1] - now).total_seconds() < 2:
        time.sleep(2.1)
        now = datetime.now(UTC)
    return compute_attendance_code(SECRET, window["id"], window["nonce"], slot_of(now) - 1)


@pytest.mark.constitution
def test_c13_attendance_survives_a_killed_process(servers, tmp_path):  # noqa: F811
    db, port = tmp_path / "app.db", free_port()
    a = Process(port, db)
    servers.append(a)

    prof = login(a)
    cid = prof.post("/api/classrooms", json={"name": "웹"}).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    for i, email in enumerate(EMAILS, start=1):
        r = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": f"s{i}", "name": f"학생{i}", "email": email})
        assert r.status_code == 201, r.text
    s1, s2, s3, s4, s5 = (enter(a, token, email) for email in EMAILS)
    sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "1회차"}).json()["id"]
    assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/start").status_code == 200
    extended = prof.post(f"/api/classrooms/{cid}/sessions/{sid}/attendance/extend")  # 마감 +5분
    assert extended.status_code == 200, extended.text

    before = prof.get(code_url(cid, sid)).json()
    assert before["closes_at"] == extended.json()["window"]["closes_at"]
    assert check_in(s1, cid, sid, before["current"]["code"], "s1-key").json() == {"status": "present", "already": False}
    approved = s2.post(f"/api/class/{cid}/sessions/{sid}/attendance-requests", json={"reason": "배터리가 없었습니다"})
    assert approved.status_code == 201, approved.text
    assert decide(prof, cid, approved.json()["id"], "approve").status_code == 200
    pending = s3.post(f"/api/class/{cid}/sessions/{sid}/attendance-requests", json={"reason": "늦게 들어왔습니다"})
    assert pending.status_code == 201, pending.text
    rejected = s5.post(f"/api/class/{cid}/sessions/{sid}/attendance-requests", json={"reason": "출석했습니다"})
    assert rejected.status_code == 201, rejected.text
    assert decide(prof, cid, rejected.json()["id"], "reject").status_code == 200
    table_before = table(prof, cid, sid)
    assert table_before["present"] == 2 and table_before["requests"] == [("s3", "늦게 들어왔습니다")]

    b = restart(servers, a, port, db)
    prof, s1, s2, s3, s4, s5 = (b.client(cookies=c.cookies) for c in (prof, s1, s2, s3, s4, s5))

    # 출석, 처리, 대기 요청이 남는다
    assert table(prof, cid, sid) == table_before
    assert live_attendance(s2, cid, sid) == {"status": "manual", "request": "approved"}
    assert live_attendance(s5, cid, sid) == {"status": "absent", "request": "rejected"}
    for done in (approved, rejected):  # 처리는 한 번뿐이라는 것이 재시작 뒤에도 지켜진다
        again = decide(prof, cid, done.json()["id"], "approve")
        assert (again.status_code, again.json()["detail"]) == (409, ALREADY_DECIDED)
    after = prof.get(code_url(cid, sid))
    assert after.status_code == 200, after.text  # 창은 아직 열려 있다
    after = after.json()
    assert after["closes_at"] == before["closes_at"]  # 연장한 마감 시각이 남는다
    # 같은 칸의 코드는 재시작 전과 같다(재시작이 15초보다 짧아 두 응답이 적어도 한 칸 겹친다)
    same = set(codes_by_slot_end(before)) & set(codes_by_slot_end(after))
    assert same, "재시작 전후 응답에 겹치는 칸이 없습니다(재시작이 너무 오래 걸렸다)"
    for ends_at in same:
        assert codes_by_slot_end(after)[ends_at] == codes_by_slot_end(before)[ends_at], ends_at

    # 같은 누름의 재전송은 처음과 같은 답이다(재시작 전에 받은 코드는 이미 지난 칸일 수 있다)
    assert check_in(s1, cid, sid, before["current"]["code"], "s1-key").json() == {"status": "present", "already": False}
    # 바로 앞 칸의 코드도 받는다
    res = check_in(s4, cid, sid, previous_slot_code(window_row(db, sid)), "s4-key")
    assert res.status_code == 200, res.text
    assert res.json() == {"status": "present", "already": False}
    # 대기 요청은 재시작 뒤에도 처리할 수 있다
    assert decide(prof, cid, pending.json()["id"], "approve").status_code == 200
    assert table(prof, cid, sid)["present"] == 4

    # 마감한 창은 재시작 뒤에도 닫혀 있다
    assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/attendance/close").status_code == 200
    c = restart(servers, b, port, db)
    prof, s5 = (c.client(cookies=x.cookies) for x in (prof, s5))
    assert prof.get(code_url(cid, sid)).status_code == 409
    # 닫힌 창의 맞는 코드라도 받지 않는다
    res = check_in(s5, cid, sid, previous_slot_code(window_row(db, sid)), "s5-key")
    assert (res.status_code, res.json()["detail"]) == (409, CLOSED)
    assert table(prof, cid, sid)["present"] == 4
