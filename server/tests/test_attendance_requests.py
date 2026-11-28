"""003 T009: 수기 출석 요청과 승인·거절 서버(AC17~AC20, AC26, AC27, C6, C12, C13).

- 학생: 진행 중인 회차에서, 회차마다 한 번, 사유 1~200자(앞뒤 공백을 지운 값을 검사하고 저장한다, T001 노트).
- 교수: 승인하면 같은 트랜잭션에서 `request_approved` 기록 → "출석 (수기)". 거절은 상태 그대로. 처리는 한 번.
  끝난 회차와 보관된 강좌에서도 처리한다(AC20).
- 요청과 처리 뒤 교수에게 `attendance.tally`, 그 학생에게 `attendance.mine`(T008).
"""

import json

import pytest
from attendance_world import act, entered_student, live, make_classroom, make_session
from conftest import ORIGIN
from fastapi.testclient import TestClient
from test_attendance_check_in import (
    NOT_MEMBER,
    CommitCheckingBus,
    check_in,
    class_of,
    code_at,
    marks,
)
from test_attendance_controls import control
from test_attendance_open import mark, roster_ids
from test_session_lifecycle import bus

SENT = 201
BAD_REASON = "사유를 1~200자로 적어 주세요."
NOT_LIVE = "수업이 진행 중일 때만 수기 출석을 요청할 수 있습니다."
ALREADY_SENT = "이미 요청을 보냈습니다. 교수님이 확인하면 출석 처리됩니다."
ALREADY_PRESENT = "이미 출석했습니다."
ALREADY_DECIDED = "이미 처리한 요청입니다."
NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."


def ask(client, cid, sid, reason="휴대폰 배터리가 없었습니다"):
    return client.post(
        f"/api/class/{cid}/sessions/{sid}/attendance-requests", json={"reason": reason}, headers=ORIGIN
    )


def decide(client, cid, rid, what):
    return client.post(f"/api/classrooms/{cid}/attendance-requests/{rid}/{what}", headers=ORIGIN)


def requests(world, sid):
    with world.db() as db:
        return [dict(r) for r in db.execute(
            "SELECT q.id, q.roster_entry_id, q.membership_id, q.reason, d.decision, d.github_id "
            "FROM attendance_requests q LEFT JOIN attendance_decisions d ON d.request_id = q.id "
            "WHERE q.session_id = ? ORDER BY q.id", (sid,)
        )]


# --- 학생 요청 ------------------------------------------------------------------------------


def test_student_sends_a_request_with_a_reason(world):
    prof, cid, sid, (s1,) = class_of(world)
    res = ask(s1, cid, sid)
    assert res.status_code == SENT, res.text
    assert res.json() == {"id": requests(world, sid)[0]["id"], "request": "pending"}
    [q] = requests(world, sid)
    assert q["reason"] == "휴대폰 배터리가 없었습니다"
    assert q["roster_entry_id"] == roster_ids(prof, cid)["s1@x.kr"]
    assert q["decision"] is None
    assert live(s1, cid, sid)["attendance"]["request"] == "pending"
    assert live(prof, cid, sid)["attendance"]["pending"] == 1


@pytest.mark.parametrize(
    ("typed", "stored"),
    [("  늦었습니다  ", "늦었습니다"), ("\t배터리\n", "배터리"), ("　고장　", "고장"), ("가" * 200, "가" * 200),
     (" " + "가" * 200 + " ", "가" * 200)],
)
def test_reason_is_trimmed_before_checking_and_saving(world, typed, stored):
    _, cid, sid, (s1,) = class_of(world)
    assert ask(s1, cid, sid, typed).status_code == SENT
    assert requests(world, sid)[0]["reason"] == stored


@pytest.mark.parametrize("bad", ["", "   ", "\n\t", "가" * 201, None, 5, ["사유"]])
def test_bad_reason_is_refused(world, bad):
    _, cid, sid, (s1,) = class_of(world)
    res = ask(s1, cid, sid, bad)
    assert (res.status_code, res.json()["detail"]) == (422, BAD_REASON)
    assert requests(world, sid) == []


def test_only_one_request_per_session(world):
    # AC17: 같은 회차에 다시 보낼 수 없다(처리된 뒤에도)
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    res = ask(s1, cid, sid, "다른 사유")
    assert (res.status_code, res.json()["detail"]) == (409, ALREADY_SENT)
    decide(prof, cid, rid, "reject")
    assert ask(s1, cid, sid, "또 보냄").status_code == 409
    assert len(requests(world, sid)) == 1


def test_another_session_takes_its_own_request(world):
    prof, cid, sid, (s1,) = class_of(world)
    ask(s1, cid, sid)
    act(prof, cid, sid, "end")
    other = make_session(prof, cid, "2회차")
    act(prof, cid, other, "start")
    assert ask(s1, cid, other).status_code == SENT


def test_request_only_while_the_session_is_live(world):
    # AC17: 회차가 진행 중인 동안만. 출석 마감 뒤에도 수업 중이면 된다
    prof, cid, sid, (s1, s2) = class_of(world, 2)
    control(prof, cid, sid, "close")
    assert ask(s1, cid, sid).status_code == SENT
    act(prof, cid, sid, "end")
    res = ask(s2, cid, sid)
    assert (res.status_code, res.json()["detail"]) == (409, NOT_LIVE)
    scheduled = make_session(prof, cid, "예정")
    assert ask(s2, cid, scheduled).json()["detail"] == NOT_LIVE


def test_present_student_cannot_request(world):
    prof, cid, sid, (s1, s2) = class_of(world, 2)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    res = ask(s1, cid, sid)
    assert (res.status_code, res.json()["detail"]) == (409, ALREADY_PRESENT)
    mark(world, cid, sid, roster_ids(prof, cid)["s2@x.kr"], "manual_present")
    assert ask(s2, cid, sid).json()["detail"] == ALREADY_PRESENT
    assert requests(world, sid) == []


def test_professors_strangers_and_removed_students_cannot_request(world):
    prof, cid, sid, (s1,) = class_of(world)
    for client in (prof, world.client("lee")):
        assert ask(client, cid, sid).status_code == 403
    assert ask(world.client(), cid, sid).status_code == 401
    entry = roster_ids(prof, cid)["s1@x.kr"]
    prof.delete(f"/api/classrooms/{cid}/roster/{entry}", headers=ORIGIN)
    assert ask(s1, cid, sid).status_code == 403
    assert requests(world, sid) == []


def test_request_for_another_classrooms_session_is_not_found(world):
    prof, cid, _, (s1,) = class_of(world)
    _, other_cid = make_classroom(world, name="다른 강좌")
    other = make_session(prof, other_cid)
    act(prof, other_cid, other, "start")
    assert ask(s1, cid, other).status_code == 404


def test_request_notifies_the_professor_and_the_student(world):
    _, cid, sid, (s1,) = class_of(world)
    recording = bus(world)
    ask(s1, cid, sid)
    ask(s1, cid, sid)  # 거절된 두 번째는 알리지 않는다
    membership = requests(world, sid)[0]["membership_id"]
    assert [e for _, e, _ in recording.published] == [
        {"type": "attendance.tally", "session_id": sid, "present": 0, "roster": 1, "pending": 1, "to": "professor"},
        {"type": "attendance.mine", "session_id": sid, "status": "absent", "request": "pending",
         "membership_id": membership, "to": "member"},
    ]


# --- 교수 처리 -----------------------------------------------------------------------------


def test_approval_makes_the_student_manually_present(world):
    # AC19: 승인하면 "출석 (수기)", 학생 화면에 출석 완료
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    res = decide(prof, cid, rid, "approve")
    assert res.status_code == 200, res.text
    assert res.json() == {"id": rid, "decision": "approved", "status": "manual"}
    assert requests(world, sid)[0]["decision"] == "approved"
    assert requests(world, sid)[0]["github_id"] == 101
    assert [m["kind"] for m in marks(world, sid)] == ["request_approved"]
    with world.db() as db:
        row = db.execute("SELECT actor_kind, actor_ref, request_id FROM attendance_marks WHERE session_id = ?", (sid,))
        assert tuple(row.fetchone()) == ("professor", 101, rid)
    mine = live(s1, cid, sid)["attendance"]
    assert (mine["status"], mine["request"]) == ("manual", "approved")
    att = live(prof, cid, sid)["attendance"]
    assert (att["present"], att["pending"]) == (1, 0)


def test_rejection_keeps_the_student_absent(world):
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    res = decide(prof, cid, rid, "reject")
    assert res.json() == {"id": rid, "decision": "rejected", "status": "absent"}
    assert marks(world, sid) == []
    att = live(s1, cid, sid)["attendance"]
    assert (att["status"], att["request"]) == ("absent", "rejected")
    assert live(prof, cid, sid)["attendance"]["pending"] == 0


@pytest.mark.parametrize(("first", "second"), [("approve", "reject"), ("reject", "approve"), ("approve", "approve")])
def test_a_request_is_decided_once(world, first, second):
    # AC19: 되돌리지 않는다. 바꾸려면 직접 바꾸기(AC21)
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    decide(prof, cid, rid, first)
    res = decide(prof, cid, rid, second)
    assert (res.status_code, res.json()["detail"]) == (409, ALREADY_DECIDED)
    assert len(marks(world, sid)) == (1 if first == "approve" else 0)


def test_approving_a_student_who_meanwhile_attended_by_code_keeps_the_code_attendance(world):
    # 요청을 보낸 뒤 코드로 출석했으면 승인해도 "출석"(코드)이 "출석 (수기)"로 내려가지 않는다
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    res = decide(prof, cid, rid, "approve")
    assert res.json() == {"id": rid, "decision": "approved", "status": "present"}
    assert [m["kind"] for m in marks(world, sid)] == ["code"]


def test_requests_can_be_decided_after_class_and_in_an_archived_classroom(world):
    # AC20: 수업이 끝난 뒤에도 처리한다
    prof, cid, sid, (s1, s2) = class_of(world, 2)
    r1, r2 = ask(s1, cid, sid).json()["id"], ask(s2, cid, sid).json()["id"]
    act(prof, cid, sid, "end")
    assert decide(prof, cid, r1, "approve").status_code == 200
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    assert decide(prof, cid, r2, "reject").status_code == 200


def test_only_the_owner_decides(world):
    # AC26
    _, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    for client in (s1, world.client("lee")):
        res = decide(client, cid, rid, "approve")
        assert (res.status_code, res.json()["detail"]) == (403, NO_PERMISSION)
    assert decide(world.client(), cid, rid, "approve").status_code == 401
    assert requests(world, sid)[0]["decision"] is None


def test_request_of_another_classroom_is_not_found(world):
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    _, other_cid = make_classroom(world, name="다른 강좌")
    assert decide(prof, other_cid, rid, "approve").status_code == 404
    assert decide(prof, cid, 9999, "approve").status_code == 404
    assert requests(world, sid)[0]["decision"] is None


def test_unknown_decision_word_is_not_a_route(world):
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    assert decide(prof, cid, rid, "maybe").status_code in (404, 405)


def test_decision_notifies_the_professor_and_the_student(world):
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    membership = requests(world, sid)[0]["membership_id"]
    recording = bus(world)
    decide(prof, cid, rid, "approve")
    decide(prof, cid, rid, "approve")  # 거절된 두 번째는 알리지 않는다
    assert [e for _, e, _ in recording.published] == [
        {"type": "attendance.tally", "session_id": sid, "present": 1, "roster": 1, "pending": 0, "to": "professor"},
        {"type": "attendance.mine", "session_id": sid, "status": "manual", "request": "approved",
         "membership_id": membership, "to": "member"},
    ]


def test_failure_while_approving_leaves_the_request_pending(world, monkeypatch):
    # 처리와 승인 기록은 한 트랜잭션: 기록이 실패하면 처리도 남지 않는다(C13)
    from app import attendance

    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]

    def boom(*_a, **_k):
        raise RuntimeError("디스크 오류")

    monkeypatch.setattr(attendance, "_approval_mark", boom)
    safe = TestClient(world.app, base_url="http://localhost:8000", raise_server_exceptions=False)
    for cookie in prof.cookies.jar:
        safe.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
    assert decide(safe, cid, rid, "approve").status_code == 500
    assert requests(world, sid)[0]["decision"] is None
    assert marks(world, sid) == []


def test_reason_is_kept_out_of_events_and_class_notices(world):
    # 사유는 학생이 쓴 글이다. 기록(events)과 수업 방 발행에 싣지 않는다(C2, C7)
    prof, cid, sid, (s1,) = class_of(world)
    recording = bus(world)
    with world.db() as db:
        (before,) = db.execute("SELECT COUNT(*) FROM events WHERE classroom_id = ?", (cid,)).fetchone()
    rid = ask(s1, cid, sid, "비밀스러운 사유").json()["id"]
    decide(prof, cid, rid, "approve")
    assert "비밀스러운" not in str(recording.published)
    with world.db() as db:
        # 학생에 대한 일(요청·처리)은 events에 쌓지 않는다(plan 데이터 모델). 지울 수 없는 기록이기 때문이다
        (after,) = db.execute("SELECT COUNT(*) FROM events WHERE classroom_id = ?", (cid,)).fetchone()
        texts = [json.loads(r[0]) for r in db.execute("SELECT payload FROM events")]
    assert after == before
    assert "비밀스러운" not in json.dumps(texts, ensure_ascii=False)
    other = entered_student(world, prof, cid, "s9@x.kr")
    assert "비밀스러운" not in other.get(f"/api/class/{cid}/sessions/{sid}/live").text


# --- 검증에서 더한 것 --------------------------------------------------------------------------


def test_student_removed_after_the_permission_check_cannot_request(world, monkeypatch):
    from app import identity

    _, cid, sid, (s1,) = class_of(world)
    monkeypatch.setattr(identity, "roster_entry_of", lambda *_a: None)
    res = ask(s1, cid, sid)
    assert (res.status_code, res.json()["detail"]) == (403, NOT_MEMBER)
    assert requests(world, sid) == []


def test_student_whose_status_went_back_to_absent_can_request_and_be_approved(world):
    # 마지막 기록이 결석이면(교수가 결석으로 바꿈) 요청할 수 있고, 승인하면 "출석 (수기)"
    prof, cid, sid, (s1,) = class_of(world)
    entry = roster_ids(prof, cid)["s1@x.kr"]
    mark(world, cid, sid, entry, "manual_present")
    mark(world, cid, sid, entry, "manual_absent")
    rid = ask(s1, cid, sid).json()["id"]
    assert decide(prof, cid, rid, "approve").json()["status"] == "manual"


def test_approval_after_code_then_absent_makes_the_student_manually_present(world):
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    mark(world, cid, sid, roster_ids(prof, cid)["s1@x.kr"], "manual_absent")
    assert decide(prof, cid, rid, "approve").json()["status"] == "manual"
    assert [m["kind"] for m in marks(world, sid)] == ["code", "manual_absent", "request_approved"]


def test_pending_count_skips_students_who_attended_after_asking(world):
    # 요청을 보낸 뒤 코드로 출석한 학생은 교수 화면의 "수기 출석 요청 N"에서 빠진다(처리는 남지 않는다)
    prof, cid, sid, (s1, s2) = class_of(world, 2)
    ask(s1, cid, sid)
    ask(s2, cid, sid)
    check_in(s1, cid, sid, code_at(world, sid, world.clock.now()))
    assert live(prof, cid, sid)["attendance"]["pending"] == 1
    assert requests(world, sid)[0]["decision"] is None


def test_request_of_a_removed_student_cannot_be_decided(world):
    prof, cid, sid, (s1,) = class_of(world)
    rid = ask(s1, cid, sid).json()["id"]
    prof.delete(f"/api/classrooms/{cid}/roster/{roster_ids(prof, cid)['s1@x.kr']}", headers=ORIGIN)
    assert decide(prof, cid, rid, "approve").status_code == 404
    assert marks(world, sid) == []


class DecisionCheckingBus(CommitCheckingBus):
    def publish(self, room, event):
        from app.db import connect as db_connect

        with db_connect(self.database_path) as db:
            counts = tuple(
                db.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("attendance_requests", "attendance_decisions", "attendance_marks")
            )
        self.seen.append((event["type"], counts))


def test_request_and_decision_notices_go_out_after_commit(world):
    prof, cid, sid, (s1,) = class_of(world)
    checking = DecisionCheckingBus(world.settings.database_path)
    world.app.state.bus = checking
    rid = ask(s1, cid, sid).json()["id"]
    decide(prof, cid, rid, "approve")
    assert checking.seen == [
        ("attendance.tally", (1, 0, 0)), ("attendance.mine", (1, 0, 0)),
        ("attendance.tally", (1, 1, 1)), ("attendance.mine", (1, 1, 1)),
    ]
