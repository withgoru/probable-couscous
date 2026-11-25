"""002 T031: 수업 중에는 강좌를 보관할 수 없다(AC46).

- 진행 중인 회차가 있으면 보관하지 않고 409와 그 회차 이름·번호를 알린다. 강좌·회차·학생 로그인은 그대로다.
- 수업을 끝낸 뒤에는 보관된다.
- 권한 판단을 지난 뒤 다른 요청이 강좌를 보관해도, 시작·이어서 하기가 보관된 강좌에 진행 중 회차를 만들지 않는다.
"""

from conftest import ORIGIN
from test_deck_serving import classroom_with_deck, enroll, entered_student

from app import session_lifecycle
from app.db import connect

ARCHIVED = "보관된 강좌는 수업을 시작할 수 없습니다."


def act(prof, cid, sid, what):
    return prof.post(f"/api/classrooms/{cid}/sessions/{sid}/{what}", headers=ORIGIN)


def archive(prof, cid):
    return prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN)


def state(world, cid, sid):
    with world.db() as db:
        classroom = db.execute("SELECT status, archived_at FROM classrooms WHERE id = ?", (cid,)).fetchone()
        session = db.execute("SELECT status FROM class_sessions WHERE id = ?", (sid,)).fetchone()
        events = [r["type"] for r in db.execute("SELECT type FROM events WHERE classroom_id = ? ORDER BY id", (cid,))]
    return classroom["status"], classroom["archived_at"], session["status"], events


def test_a_classroom_with_a_live_session_is_not_archived(world):
    prof, cid, sid, deck_id, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    assert act(prof, cid, sid, "start").status_code == 200
    res = archive(prof, cid)
    assert res.status_code == 409
    assert res.json() == {"detail": "1회차 수업이 진행 중입니다. 수업을 끝낸 뒤 보관해 주세요.", "live_session_id": sid}
    status, archived_at, session_status, events = state(world, cid, sid)
    assert (status, archived_at, session_status) == ("active", None, "live")
    assert "classroom_archived" not in events
    # 학생 로그인도 그대로라 수업을 계속 본다
    assert student.get(f"/decks/{deck_id}/index.html").status_code == 200


def test_after_ending_the_class_the_classroom_is_archived(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    act(prof, cid, sid, "start")
    assert archive(prof, cid).status_code == 409
    assert act(prof, cid, sid, "end").status_code == 200
    res = archive(prof, cid)
    assert res.status_code == 200 and res.json()["status"] == "archived"
    assert state(world, cid, sid)[0] == "archived"


def test_ended_or_scheduled_sessions_do_not_block_archiving(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "예정"}, headers=ORIGIN)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    assert archive(prof, cid).status_code == 200


def test_already_archived_is_still_reported_as_such(world):
    prof, cid, _, _, _ = classroom_with_deck(world)
    assert archive(prof, cid).status_code == 200
    res = archive(prof, cid)
    assert res.status_code == 409 and res.json()["detail"] == "이미 보관된 강좌입니다."


def _archive_after_the_guard(monkeypatch, world, cid):
    """권한 판단(강좌가 진행 중)은 지났고, 쓰기 직전에 다른 요청이 강좌를 보관한 상황을 만든다."""
    real = session_lifecycle.transaction

    def archive_first(db):
        with connect(world.settings.database_path) as other:
            other.execute(
                "UPDATE classrooms SET status = 'archived', archived_at = ? WHERE id = ?",
                (world.clock.now().isoformat(), cid),
            )
        return real(db)

    monkeypatch.setattr(session_lifecycle, "transaction", archive_first)


def test_start_does_not_go_live_in_a_classroom_archived_meanwhile(world, monkeypatch):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    _archive_after_the_guard(monkeypatch, world, cid)
    res = act(prof, cid, sid, "start")
    assert res.status_code == 409 and res.json()["detail"] == ARCHIVED
    _, _, session_status, events = state(world, cid, sid)
    assert session_status == "scheduled" and "session_started" not in events


def test_resume_does_not_go_live_in_a_classroom_archived_meanwhile(world, monkeypatch):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    act(prof, cid, sid, "start")
    act(prof, cid, sid, "end")
    _archive_after_the_guard(monkeypatch, world, cid)
    res = act(prof, cid, sid, "resume")
    assert res.status_code == 409 and res.json()["detail"] == ARCHIVED
    _, _, session_status, events = state(world, cid, sid)
    assert session_status == "ended" and "session_resumed" not in events
