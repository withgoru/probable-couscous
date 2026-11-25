"""002 T005: 회차의 슬라이드 묶음 올리기·바꾸기·지우기(AC5~AC7 서버, 오류 동작 "올리기 실패").

- 본문은 zip 파일 그대로, 파일 이름은 `filename` 질의 값이다(001의 CSV 올리기와 같은 방식).
- 받아들이면 회차 목록에 묶음(파일 이름, 올린 시각, 슬라이드 수)이 보인다(AC5).
- 템플릿 빌드가 아니거나 크기를 넘으면 아무것도 바뀌지 않고 AC6 문구가 온다.
- 진행 중인 회차에서는 바꾸기·지우기가 409다(AC7).
- 올리다 실패하면 이전 묶음이 그대로다. 회차를 지우면 묶음 파일도 지운다(T004에서 미룬 일).
"""

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from conftest import BASE, ORIGIN, FakeProvider, World
from fastapi.testclient import TestClient

from app.clock import ManualClock
from app.config import Settings
from app.main import create_app

FIXTURE = Path(__file__).parent / "fixtures" / "deck-small.zip"
BAD_DECK = "슬라이드 묶음을 읽을 수 없습니다. Slidev로 빌드한 폴더(dist)를 zip으로 묶어 올려 주세요."
TOO_BIG = "파일이 너무 큽니다. 100MB 이하로 올려 주세요."
LIVE = "수업 중에는 슬라이드를 바꿀 수 없습니다."
NO_PERMISSION = "이 강좌에 대한 권한이 없습니다."
ZIP = {"Content-Type": "application/zip", **ORIGIN}


@pytest.fixture
def world(tmp_path):
    clock = ManualClock(datetime(2026, 3, 1, 9, tzinfo=UTC))
    settings = Settings(
        base_url=BASE,
        professor_github_ids=(101, 202),
        github_client_id="cid",
        github_client_secret="secret",
        server_secret="s",
        database_path=tmp_path / "app.db",
        client_dist=tmp_path / "none",
    )
    app = create_app(settings, clock=clock, auth_provider=FakeProvider(), start_mail_worker=False)
    with TestClient(app, base_url=BASE):
        yield World(app=app, clock=clock, settings=settings)


def deck_root(world) -> Path:
    return world.settings.database_path.parent / "decks"


def setup(world, owner="kim"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "1회차"}, headers=ORIGIN).json()["id"]
    return prof, cid, sid


def upload(prof, cid, sid, data=None, filename="3주차.zip"):
    body = FIXTURE.read_bytes() if data is None else data
    return prof.put(f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": filename}, content=body, headers=ZIP)


def session_item(prof, cid, sid):
    return next(i for i in prof.get(f"/api/classrooms/{cid}/sessions").json()["items"] if i["id"] == sid)


def set_status(world, sid, status):
    with world.db() as db:
        db.execute(
            "UPDATE class_sessions SET status = ?, first_started_at = COALESCE(first_started_at, ?) WHERE id = ?",
            (status, "2026-03-01T09:00:00+00:00", sid),
        )


# --- 올리기 ----------------------------------------------------------------------------------


def test_upload_stores_the_deck_and_lists_it(world):
    prof, cid, sid = setup(world)
    assert session_item(prof, cid, sid)["deck"] is None  # 올리기 전: '비어 있음'
    world.clock.advance(minutes=5)
    res = upload(prof, cid, sid)
    assert res.status_code == 200, res.text
    deck = res.json()["deck"]
    assert deck["original_name"] == "3주차.zip"
    assert deck["slide_count"] == 4
    assert deck["uploaded_at"] == "2026-03-01T09:05:00+00:00"
    assert deck["size_bytes"] == FIXTURE.stat().st_size
    assert session_item(prof, cid, sid)["deck"] == deck  # AC5: 업로드됨, 파일 이름, 시각, 슬라이드 수
    index = deck_root(world) / str(cid) / str(deck["id"]) / "index.html"
    assert f"/decks/{deck['id']}/assets/" in index.read_text()


def test_filename_is_kept_short_and_without_folders(world):
    prof, cid, sid = setup(world)
    deck = upload(prof, cid, sid, filename="C:\\Users\\kim\\강의/3주차 " + "가" * 300 + ".zip").json()["deck"]
    assert "/" not in deck["original_name"] and "\\" not in deck["original_name"]
    assert deck["original_name"].startswith("3주차")
    assert len(deck["original_name"]) <= 120
    assert upload(prof, cid, sid, filename="").json()["deck"]["original_name"] == "slides.zip"


def test_not_a_template_build_is_refused_and_changes_nothing(world):
    prof, cid, sid = setup(world)
    first = upload(prof, cid, sid).json()["deck"]
    res = upload(prof, cid, sid, data=b"PK\x03\x04 broken")
    assert res.status_code == 422
    assert res.json()["detail"] == BAD_DECK
    assert session_item(prof, cid, sid)["deck"] == first


def test_too_big_is_refused_before_reading_everything(world, tmp_path):
    small = dataclasses.replace(world.settings, deck_max_bytes=1000)
    app = create_app(small, clock=world.clock, auth_provider=FakeProvider(), start_mail_worker=False)
    with TestClient(app, base_url=BASE):
        w = World(app=app, clock=world.clock, settings=small)
        prof, cid, sid = setup(w)
        res = upload(prof, cid, sid)
        assert res.status_code == 413
        assert res.json()["detail"] == "파일이 너무 큽니다. 1000바이트 이하로 올려 주세요."
        assert session_item(prof, cid, sid)["deck"] is None


def test_too_big_message_uses_megabytes_for_the_default_limit():
    from app.decks import too_big_message

    assert too_big_message(100 * 1024 * 1024) == TOO_BIG


def test_replacing_keeps_one_deck_and_removes_the_old_files(world):
    prof, cid, sid = setup(world)
    old = upload(prof, cid, sid).json()["deck"]
    new = upload(prof, cid, sid, filename="고친 슬라이드.zip").json()["deck"]
    assert new["id"] != old["id"]
    assert session_item(prof, cid, sid)["deck"]["id"] == new["id"]
    assert not (deck_root(world) / str(cid) / str(old["id"])).exists()
    assert (deck_root(world) / str(cid) / str(new["id"]) / "index.html").is_file()
    with world.db() as db:
        rows = db.execute("SELECT id, removed_at FROM decks WHERE session_id = ? ORDER BY id", (sid,)).fetchall()
    assert [(r["id"], r["removed_at"] is None) for r in rows] == [(old["id"], False), (new["id"], True)]


def test_a_failure_while_saving_keeps_the_previous_deck(world, monkeypatch):
    prof, cid, sid = setup(world)
    first = upload(prof, cid, sid).json()["deck"]

    def broken(self, classroom_id, deck_id, zip_path):
        raise OSError("disk full")

    monkeypatch.setattr("app.deck_store.DeckStore.install", broken)
    res = upload(prof, cid, sid)
    assert res.status_code == 500
    assert res.json()["detail"] == "올리지 못했습니다. 다시 올려 주세요."
    assert session_item(prof, cid, sid)["deck"] == first
    assert (deck_root(world) / str(cid) / str(first["id"]) / "index.html").is_file()
    with world.db() as db:  # 반쯤 만든 기록이 남지 않는다
        assert db.execute("SELECT COUNT(*) FROM decks WHERE session_id = ?", (sid,)).fetchone()[0] == 1


# --- 진행 중(AC7), 지우기 -----------------------------------------------------------------------


def test_class_started_while_uploading_keeps_the_previous_deck(world, monkeypatch):
    # 본문을 받는 사이에 수업이 시작되면, 바꾸기 직전에 다시 확인해 진행 중 회차의 묶음을 바꾸지 않는다(AC7)
    prof, cid, sid = setup(world)
    first = upload(prof, cid, sid).json()["deck"]
    from app.deck_store import DeckStore

    real = DeckStore.install

    def start_class_meanwhile(self, classroom_id, deck_id, zip_path):
        meta = real(self, classroom_id, deck_id, zip_path)
        set_status(world, sid, "live")
        return meta

    monkeypatch.setattr(DeckStore, "install", start_class_meanwhile)
    res = upload(prof, cid, sid)
    assert res.status_code == 409 and res.json()["detail"] == LIVE
    assert session_item(prof, cid, sid)["deck"] == first
    with world.db() as db:
        ids = [r["id"] for r in db.execute("SELECT id FROM decks WHERE session_id = ?", (sid,))]
    assert ids == [first["id"]]
    assert sorted(p.name for p in (deck_root(world) / str(cid)).iterdir()) == [str(first["id"])]


def test_live_session_deck_cannot_be_replaced_or_removed(world):
    prof, cid, sid = setup(world)
    first = upload(prof, cid, sid).json()["deck"]
    set_status(world, sid, "live")
    res = upload(prof, cid, sid)
    assert res.status_code == 409 and res.json()["detail"] == LIVE
    res = prof.delete(f"/api/classrooms/{cid}/sessions/{sid}/deck", headers=ORIGIN)
    assert res.status_code == 409 and res.json()["detail"] == LIVE
    assert session_item(prof, cid, sid)["deck"] == first
    set_status(world, sid, "ended")  # 종료 회차는 다시 바꿀 수 있다
    assert upload(prof, cid, sid).status_code == 200


def test_remove_deck(world):
    prof, cid, sid = setup(world)
    deck = upload(prof, cid, sid).json()["deck"]
    res = prof.delete(f"/api/classrooms/{cid}/sessions/{sid}/deck", headers=ORIGIN)
    assert res.status_code == 204
    assert session_item(prof, cid, sid)["deck"] is None
    assert not (deck_root(world) / str(cid) / str(deck["id"])).exists()
    again = prof.delete(f"/api/classrooms/{cid}/sessions/{sid}/deck", headers=ORIGIN)
    assert again.status_code == 404 and again.json()["detail"] == "이 회차에 올린 슬라이드가 없습니다."


def test_deleting_a_session_removes_its_deck_files(world):
    prof, cid, sid = setup(world)
    deck = upload(prof, cid, sid).json()["deck"]
    assert prof.delete(f"/api/classrooms/{cid}/sessions/{sid}", headers=ORIGIN).status_code == 204
    assert not (deck_root(world) / str(cid) / str(deck["id"])).exists()


def test_upload_and_remove_are_recorded(world):
    prof, cid, sid = setup(world)
    deck = upload(prof, cid, sid).json()["deck"]
    prof.delete(f"/api/classrooms/{cid}/sessions/{sid}/deck", headers=ORIGIN)
    with world.db() as db:
        rows = db.execute(
            "SELECT type, payload FROM events WHERE classroom_id = ? AND type LIKE 'deck_%' ORDER BY id", (cid,)
        ).fetchall()
    assert [(r["type"], json.loads(r["payload"])) for r in rows] == [
        ("deck_uploaded", {"session_id": sid, "deck_id": deck["id"]}),
        ("deck_removed", {"session_id": sid, "deck_id": deck["id"]}),
    ]


# --- 권한과 강좌 구분 ---------------------------------------------------------------------------


def test_other_professor_cannot_upload_and_body_is_not_read(world):
    _, cid, sid = setup(world)
    lee = world.client("lee")
    res = upload(lee, cid, sid)
    assert res.status_code == 403 and res.json()["detail"] == NO_PERMISSION
    assert world.client().put(f"/api/classrooms/{cid}/sessions/{sid}/deck", content=b"x", headers=ZIP).status_code == 401
    assert not deck_root(world).exists() or not any(deck_root(world).rglob("index.html"))


def test_session_of_another_classroom_is_not_found(world):
    prof, _, sid = setup(world)
    other = prof.post("/api/classrooms", json={"name": "다른"}, headers=ORIGIN).json()["id"]
    res = upload(prof, other, sid)
    assert res.status_code == 404 and res.json()["detail"] == "찾을 수 없는 회차입니다."
