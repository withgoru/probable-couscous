"""C6, C7: 기록(events)은 추가만 하고, 이메일·이름·학번을 내용에 넣지 않는다."""

import json
from datetime import UTC, datetime

import pytest
from conftest import ORIGIN

from app.events import record_event

NOW = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


@pytest.fixture
def cid(world):
    return world.client("kim").post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]


def test_an_event_records_who_what_when_and_which_student(world, cid):
    db = world.db()
    event_id = record_event(db, cid, "join_request_approved", "professor", 101, 5, {"request_id": 9}, NOW)
    row = db.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    assert (row["classroom_id"], row["type"], row["actor_kind"], row["actor_ref"], row["subject_roster_entry_id"]) == (
        cid, "join_request_approved", "professor", 101, 5,
    )
    assert json.loads(row["payload"]) == {"request_id": 9} and row["created_at"] == NOW.isoformat()


def test_the_subject_may_be_empty(world, cid):
    db = world.db()
    event_id = record_event(db, cid, "join_request_rejected", "professor", 101, None, {}, NOW)
    assert db.execute("SELECT subject_roster_entry_id FROM events WHERE id = ?", (event_id,)).fetchone()[0] is None


@pytest.mark.parametrize(
    "payload",
    [{"email": "a@x.kr"}, {"name": "김"}, {"student_no": "1"}, {"note": "kim@x.kr"}, {"deep": {"x": ["a@b.kr"]}}, {"Email": "x"}],
)
def test_personal_data_in_the_payload_is_refused(world, cid, payload):
    with pytest.raises(ValueError, match="개인정보"):
        record_event(world.db(), cid, "x", "professor", 101, None, payload, NOW)
    assert world.db().execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0


def test_an_event_cannot_be_changed_or_removed_afterwards(world, cid):
    db = world.db()
    event_id = record_event(db, cid, "x", "system", None, None, {}, NOW)
    with pytest.raises(Exception, match="추가만"):
        db.execute("UPDATE events SET type = 'y' WHERE id = ?", (event_id,))
    with pytest.raises(Exception, match="추가만"):
        db.execute("DELETE FROM events WHERE id = ?", (event_id,))
