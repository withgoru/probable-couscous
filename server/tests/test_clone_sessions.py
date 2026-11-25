"""002 T012: 분반 만들기·새 학기로 복제 때 회차와 슬라이드 묶음 복사(AC42, C5).

- 새 강좌에 원래 회차가 같은 이름·순서·'예정'으로 생긴다. 보낸 항목, 위치, 시작·종료 시각은 없다.
- 살아 있는 묶음은 새 강좌 폴더에 새 번호로 생긴다. 파일은 하드 링크(안 되면 복사)이고, 기준 경로가 든 파일만
  새 번호로 다시 쓴 사본이다. 원래 강좌 묶음을 지워도 복제본은 열린다.
- 도중에 실패하면 새 강좌도, 새 파일도 남지 않는다.
"""

import os
import re
import shutil

import pytest
from conftest import ORIGIN
from test_deck_serving import FIXTURE, ZIP

from app import deck_store


def make_source(world):
    """회차 셋: 묶음 있음(예정), 묶음 있음(끝남, 항목·위치 있음), 묶음 없음."""
    prof = world.client("kim")
    cid = prof.post("/api/classrooms", json={"name": "웹", "section_name": "월수반"}, headers=ORIGIN).json()["id"]
    ids = []
    for title in ("1회차", "2회차", "3회차"):
        ids.append(prof.post(f"/api/classrooms/{cid}/sessions", json={"title": title}, headers=ORIGIN).json()["id"])
    decks = {}
    for sid in ids[:2]:
        res = prof.put(
            f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": f"{sid}.zip"},
            content=FIXTURE.read_bytes(), headers=ZIP,
        )
        assert res.status_code == 200, res.text
        decks[sid] = res.json()["deck"]["id"]
    ended = ids[1]
    prof.post(f"/api/classrooms/{cid}/sessions/{ended}/start", headers=ORIGIN)
    prof.post(f"/api/classrooms/{cid}/sessions/{ended}/items", json={"body": "자료", "client_key": "a"}, headers=ORIGIN)
    with world.db() as db:
        db.execute("UPDATE class_sessions SET current_slide = 3, furthest_slide = 4 WHERE id = ?", (ended,))
    prof.post(f"/api/classrooms/{cid}/sessions/{ended}/end", headers=ORIGIN)
    # 순서를 바꿔 둔다: 복제본도 같은 순서여야 한다
    with world.db() as db:
        db.execute("UPDATE class_sessions SET sort_order = 10 WHERE id = ?", (ids[0],))
    return prof, cid, ids, decks


def clone(prof, cid, **body):
    return prof.post(f"/api/classrooms/{cid}/clone", json=body, headers=ORIGIN)


def sessions(world, cid):
    with world.db() as db:
        return [
            dict(r)
            for r in db.execute("SELECT * FROM class_sessions WHERE classroom_id = ? ORDER BY sort_order, id", (cid,))
        ]


def live_decks(world, cid):
    with world.db() as db:
        return {
            r["session_id"]: dict(r)
            for r in db.execute("SELECT * FROM decks WHERE classroom_id = ? AND removed_at IS NULL", (cid,))
        }


def test_sessions_are_copied_as_scheduled_with_the_same_titles_and_order(world):
    prof, cid, _, _ = make_source(world)
    world.clock.advance(hours=3)
    res = clone(prof, cid, name="웹", section_name="화목반")
    assert res.status_code == 201
    new = res.json()["id"]
    copied = sessions(world, new)
    assert [s["title"] for s in copied] == ["2회차", "3회차", "1회차"]
    assert [s["title"] for s in copied] == [s["title"] for s in sessions(world, cid)]
    assert [s["sort_order"] for s in copied] == [s["sort_order"] for s in sessions(world, cid)]  # 순서 값도 같다
    for s in copied:
        assert s["status"] == "scheduled"
        assert (s["current_slide"], s["current_click"], s["furthest_slide"], s["furthest_click"]) == (1, 0, 1, 0)
        assert s["first_started_at"] is None and s["started_at"] is None and s["ended_at"] is None
        assert s["version"] == 0
        assert s["created_at"] == world.clock.now().isoformat()
    listed = prof.get(f"/api/classrooms/{new}/sessions").json()["items"]
    assert all(i["can_delete"] for i in listed)  # 한 번도 시작하지 않은 회차다
    with world.db() as db:
        assert db.execute("SELECT COUNT(*) FROM session_items WHERE classroom_id = ?", (new,)).fetchone()[0] == 0


def test_decks_are_copied_into_the_new_classroom_and_open(world):
    prof, cid, ids, decks = make_source(world)
    world.clock.advance(hours=1)  # 올린 시각은 원본 그대로여야 한다
    new = clone(prof, cid).json()["id"]
    by_title = {s["title"]: s["id"] for s in sessions(world, new)}
    copied = live_decks(world, new)
    assert set(copied) == {by_title["1회차"], by_title["2회차"]}  # 묶음 없는 3회차는 묶음 없이
    original = live_decks(world, cid)
    for title, source_sid in (("1회차", ids[0]), ("2회차", ids[1])):
        deck = copied[by_title[title]]
        old = original[source_sid]
        assert deck["id"] not in decks.values()
        assert (deck["original_name"], deck["slide_count"], deck["size_bytes"], deck["uploaded_at"]) == (
            old["original_name"], old["slide_count"], old["size_bytes"], old["uploaded_at"]
        )
        folder = world.app.state.deck_store.path_for(new, deck["id"])
        assert folder.is_dir()
        index = prof.get(f"/decks/{deck['id']}/index.html")
        assert index.status_code == 200
        assert f"/decks/{deck['id']}/assets/" in index.text
        assert f"/decks/{old['id']}/" not in index.text  # 원래 묶음을 가리키지 않는다
        script = re.search(rf'src="(/decks/{deck["id"]}/assets/[^"]+\.js)"', index.text).group(1)
        assert prof.get(script).status_code == 200
        notes = prof.get(f"/api/classrooms/{new}/sessions/{by_title[title]}/deck/notes").json()
        assert notes["slide_count"] == 4 and notes["deck_id"] == deck["id"]


def test_files_without_the_base_path_are_hard_linked(world):
    prof, cid, ids, decks = make_source(world)
    new = clone(prof, cid).json()["id"]
    store = world.app.state.deck_store
    deck = next(d for d in live_decks(world, new).values() if d["original_name"] == f"{ids[0]}.zip")
    old_folder, new_folder = store.path_for(cid, decks[ids[0]]), store.path_for(new, deck["id"])
    linked = rewritten = 0
    for path in old_folder.rglob("*"):
        if not path.is_file():
            continue
        twin = new_folder / path.relative_to(old_folder)
        assert twin.is_file()
        if f"/decks/{decks[ids[0]]}/".encode() in path.read_bytes():
            assert not os.path.samefile(path, twin)  # 기준 경로가 든 파일은 따로 쓴 사본
            rewritten += 1
        else:
            assert os.path.samefile(path, twin)
            linked += 1
    assert linked > 0 and rewritten > 0


def test_copies_when_hard_links_are_not_possible(world, monkeypatch):
    prof, cid, _, _ = make_source(world)

    def no_link(*_a, **_k):
        raise OSError("다른 디스크")

    monkeypatch.setattr(deck_store.os, "link", no_link)
    new = clone(prof, cid).json()["id"]
    for deck in live_decks(world, new).values():
        assert prof.get(f"/decks/{deck['id']}/index.html").status_code == 200


def test_removing_the_original_deck_leaves_the_copy_open(world):
    prof, cid, ids, decks = make_source(world)
    new = clone(prof, cid).json()["id"]
    assert prof.delete(f"/api/classrooms/{cid}/sessions/{ids[0]}/deck", headers=ORIGIN).status_code == 204
    shutil.rmtree(world.app.state.deck_store.path_for(cid, decks[ids[1]]))
    for deck in live_decks(world, new).values():
        index = prof.get(f"/decks/{deck['id']}/index.html")
        assert index.status_code == 200
        script = re.search(rf'src="(/decks/{deck["id"]}/assets/[^"]+\.js)"', index.text).group(1)
        assert prof.get(script).status_code == 200


def test_only_the_current_deck_is_copied(world):
    prof, cid, ids, _ = make_source(world)
    prof.put(
        f"/api/classrooms/{cid}/sessions/{ids[0]}/deck", params={"filename": "new.zip"},
        content=FIXTURE.read_bytes(), headers=ZIP,
    )
    new = clone(prof, cid).json()["id"]
    with world.db() as db:
        rows = db.execute("SELECT original_name, removed_at FROM decks WHERE classroom_id = ?", (new,)).fetchall()
    assert sorted(r["original_name"] for r in rows) == sorted(["new.zip", f"{ids[1]}.zip"])
    assert all(r["removed_at"] is None for r in rows)
    assert [s["title"] for s in sessions(world, new)] == ["2회차", "3회차", "1회차"]  # 회차가 겹쳐 생기지 않는다


def test_a_source_deck_whose_files_are_gone_is_left_out(world):
    # 파일이 사라진 묶음(오류 동작 "열리지 않음")은 복사할 수 없다: 회차만 묶음 없이 생기고 복제는 성공한다
    prof, cid, ids, decks = make_source(world)
    shutil.rmtree(world.app.state.deck_store.path_for(cid, decks[ids[0]]))
    res = clone(prof, cid)
    assert res.status_code == 201
    new = res.json()["id"]
    by_title = {s["title"]: s["id"] for s in sessions(world, new)}
    assert set(live_decks(world, new)) == {by_title["2회차"]}


def test_a_failure_while_copying_leaves_nothing_behind(world, monkeypatch):
    prof, cid, _, _ = make_source(world)
    store = world.app.state.deck_store
    before = {p for p in store.root.rglob("*")}
    with world.db() as db:
        classrooms_before = db.execute("SELECT COUNT(*) FROM classrooms").fetchone()[0]
    calls = []
    real = store.copy

    def fails_second_time(*args):
        calls.append(args)
        if len(calls) == 2:
            raise OSError("디스크가 가득 찼다")
        return real(*args)

    monkeypatch.setattr(store, "copy", fails_second_time)
    res = clone(prof, cid)
    assert res.status_code == 500
    assert res.json()["detail"] == "강좌를 복제하지 못했습니다. 잠시 뒤 다시 시도해 주세요."
    with world.db() as db:
        assert db.execute("SELECT COUNT(*) FROM classrooms").fetchone()[0] == classrooms_before
    assert {p for p in store.root.rglob("*")} == before  # 첫 번째로 복사한 묶음 파일도 지웠다


def test_a_classroom_without_sessions_clones_as_before(world):
    prof = world.client("kim")
    cid = prof.post("/api/classrooms", json={"name": "빈 강좌"}, headers=ORIGIN).json()["id"]
    new = clone(prof, cid)
    assert new.status_code == 201
    assert sessions(world, new.json()["id"]) == []


def test_an_archived_classroom_clones_its_sessions_too(world):
    prof, cid, _, _ = make_source(world)
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    new = clone(prof, cid).json()["id"]
    assert len(sessions(world, new)) == 3 and len(live_decks(world, new)) == 2


def test_the_source_is_unchanged(world):
    prof, cid, _, _ = make_source(world)
    before = (sessions(world, cid), live_decks(world, cid))
    clone(prof, cid)
    assert (sessions(world, cid), live_decks(world, cid)) == before


@pytest.mark.parametrize("who", ["lee", None])
def test_only_the_owner_clones(world, who):
    _prof, cid, _, _ = make_source(world)
    assert clone(world.client(who) if who else world.client(), cid).status_code in (401, 403)
