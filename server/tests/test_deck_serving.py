"""002 T006: 슬라이드 묶음 파일 내려주기와 발표자 노트(AC30, AC43, AC44).

- `/decks/{묶음}/…`는 그 강좌의 교수와, 그 강좌에 입장한 학생만 받는다(class.view). 다른 강좌 학생·로그인 안 함은 거절.
- 명단에서 빠졌거나 로그인이 끊긴 학생은 받지 못한다(AC44).
- 노트 파일(`classroom-deck.json`)은 내려주지 않는다. 노트는 교수 전용 API로만 받는다(AC30).
- 해시가 붙은 파일은 오래 캐시하고 `index.html`은 매번 확인한다. 다른 사이트가 얹지 못한다(plan 위험 6).
- 파일이 사라진 묶음은 "열 수 없음"이다(plan 위험 9, 오류 동작 "슬라이드 묶음이 열리지 않음").
"""

import json
import re
import shutil
from pathlib import Path

from conftest import ORIGIN

FIXTURE = Path(__file__).parent / "fixtures" / "deck-small.zip"
ZIP = {"Content-Type": "application/zip", **ORIGIN}
NOTES = ["노트 1: 인사하기", "노트 2: 하나씩 보여 준다", "노트 4: 정답은 마지막에"]
CANNOT_OPEN = "슬라이드를 열 수 없습니다. 묶음을 다시 올려 주세요."


def classroom_with_deck(world, owner="kim", name="웹"):
    prof = world.client(owner)
    cid = prof.post("/api/classrooms", json={"name": name}, headers=ORIGIN).json()["id"]
    sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "1회차"}, headers=ORIGIN).json()["id"]
    res = prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "a.zip"}, content=FIXTURE.read_bytes(), headers=ZIP
    )
    assert res.status_code == 200, res.text
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return prof, cid, sid, res.json()["deck"]["id"], token


def enroll(prof, cid, email, no="1"):
    res = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": "김철수", "email": email}, headers=ORIGIN)
    assert res.status_code == 201, res.text
    return res.json()["id"]


def entered_student(world, token, email):
    student = world.client()
    assert student.post(f"/api/join/{token}/email", json={"email": email}, headers=ORIGIN).json()["next"] == "code"
    world.app.state.mail_worker.process_due()
    code = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    assert student.post(f"/api/join/{token}/code", json={"email": email, "code": code}, headers=ORIGIN).status_code == 200
    assert student.post(f"/api/join/{token}/enter", headers=ORIGIN).status_code == 200
    return student


def asset_path(client, deck_id) -> str:
    index = client.get(f"/decks/{deck_id}/index.html").text
    return re.search(rf'src="(/decks/{deck_id}/assets/[^"]+\.js)"', index).group(1)


# --- 누가 받는가 ------------------------------------------------------------------------------


def test_owner_gets_the_deck_files(world):
    prof, _, _, deck_id, _ = classroom_with_deck(world)
    index = prof.get(f"/decks/{deck_id}/")
    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert f"/decks/{deck_id}/assets/" in index.text
    assert prof.get(f"/decks/{deck_id}/index.html").text == index.text
    js = prof.get(asset_path(prof, deck_id))
    assert js.status_code == 200
    assert "javascript" in js.headers["content-type"]


def test_entered_student_gets_the_deck_files(world):
    prof, cid, _, deck_id, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    assert student.get(f"/decks/{deck_id}/index.html").status_code == 200
    assert student.get(asset_path(prof, deck_id)).status_code == 200


def test_student_who_has_not_finished_entering_is_refused(world):
    prof, cid, _, deck_id, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    student = world.client()
    student.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN)
    world.app.state.mail_worker.process_due()
    code = re.search(r"\b(\d{6})\b", world.app.state.mailer.sent[-1].text).group(1)
    student.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": code}, headers=ORIGIN)
    # 코드는 확인했지만 '확인하고 입장'을 누르기 전
    assert student.get(f"/decks/{deck_id}/index.html").status_code in (401, 403)


def test_student_of_another_classroom_is_refused(world):
    prof, _, _, deck_id, _ = classroom_with_deck(world)
    _, other_cid, _, _, other_token = classroom_with_deck(world, name="다른 강좌")
    enroll(prof, other_cid, "lee@x.kr")
    outsider = entered_student(world, other_token, "lee@x.kr")
    res = outsider.get(f"/decks/{deck_id}/index.html")
    assert res.status_code == 403


def test_other_professor_and_anonymous_are_refused(world):
    _, _, _, deck_id, _ = classroom_with_deck(world)
    lee = world.client("lee")
    res = lee.get(f"/decks/{deck_id}/index.html")
    assert res.status_code == 403 and res.json()["detail"] == "이 강좌에 대한 권한이 없습니다."
    assert world.client().get(f"/decks/{deck_id}/index.html").status_code == 401


def test_removed_or_revoked_student_is_refused(world):
    # AC44: 명단에서 빠지거나 로그인이 끊긴 학생은 슬라이드를 받지 못한다
    prof, cid, _, deck_id, token = classroom_with_deck(world)
    kim = enroll(prof, cid, "kim@x.kr", "1")
    lee = enroll(prof, cid, "lee@x.kr", "2")
    kim_client = entered_student(world, token, "kim@x.kr")
    lee_client = entered_student(world, token, "lee@x.kr")
    assert prof.delete(f"/api/classrooms/{cid}/roster/{kim}", headers=ORIGIN).status_code in (200, 204)
    world.clock.advance(seconds=1)
    assert prof.post(f"/api/classrooms/{cid}/roster/{lee}/revoke-login", headers=ORIGIN).status_code == 200
    assert kim_client.get(f"/decks/{deck_id}/index.html").status_code in (401, 403)
    assert lee_client.get(f"/decks/{deck_id}/index.html").status_code in (401, 403)


def test_students_of_an_archived_classroom_are_refused_but_the_owner_is_not(world):
    prof, cid, _, deck_id, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    assert prof.post(f"/api/classrooms/{cid}/archive", headers=ORIGIN).status_code == 200
    assert student.get(f"/decks/{deck_id}/index.html").status_code == 403
    assert prof.get(f"/decks/{deck_id}/index.html").status_code == 200


# --- 무엇을 내려주지 않는가 ---------------------------------------------------------------------


def test_the_meta_file_with_notes_is_never_served(world):
    prof, cid, _, deck_id, token = classroom_with_deck(world)
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    for client in (prof, student):
        res = client.get(f"/decks/{deck_id}/classroom-deck.json")
        assert res.status_code == 404
        for note in NOTES:
            assert note not in res.text


def test_paths_outside_the_deck_are_refused(world):
    prof, cid, _, deck_id, _ = classroom_with_deck(world)
    db_file = world.settings.database_path
    for path in (f"/decks/{deck_id}/../../app.db", f"/decks/{deck_id}/%2e%2e/%2e%2e/app.db", f"/decks/{deck_id}/assets/../../{cid}"):
        res = prof.get(path)
        # 클라이언트가 '..'을 미리 풀어 다른 주소로 가면 화면 대체 경로(빌드 없음 503)가 받는다. 어느 쪽이든 파일은 안 나간다
        assert res.status_code in (404, 503), path
        assert db_file.read_bytes()[:16] not in res.content


def test_removed_or_unknown_deck_is_not_found(world):
    prof, cid, sid, deck_id, _ = classroom_with_deck(world)
    assert prof.delete(f"/api/classrooms/{cid}/sessions/{sid}/deck", headers=ORIGIN).status_code == 204
    assert prof.get(f"/decks/{deck_id}/index.html").status_code == 404
    assert prof.get("/decks/999999/index.html").status_code == 404
    assert prof.get(f"/decks/{deck_id}/nope.js").status_code == 404


def test_old_deck_stops_being_served_after_replacing(world):
    prof, cid, sid, old_id, _ = classroom_with_deck(world)
    new = prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "b.zip"}, content=FIXTURE.read_bytes(), headers=ZIP
    ).json()["deck"]
    assert prof.get(f"/decks/{old_id}/index.html").status_code == 404
    assert prof.get(f"/decks/{new['id']}/index.html").status_code == 200


# --- 응답 머리글 --------------------------------------------------------------------------------


def test_cache_and_framing_headers(world):
    prof, _, _, deck_id, _ = classroom_with_deck(world)
    index = prof.get(f"/decks/{deck_id}/index.html")
    assert index.headers["cache-control"] == "private, no-cache"
    asset = prof.get(asset_path(prof, deck_id))
    assert asset.headers["cache-control"] == "private, max-age=31536000, immutable"
    for res in (index, asset):
        assert res.headers["content-security-policy"] == "frame-ancestors 'self'"
        assert res.headers["x-content-type-options"] == "nosniff"


# --- 노트(AC30) --------------------------------------------------------------------------------


def test_notes_are_for_the_owner_only(world):
    prof, cid, sid, _, token = classroom_with_deck(world)
    res = prof.get(f"/api/classrooms/{cid}/sessions/{sid}/deck/notes")
    assert res.status_code == 200
    body = res.json()
    assert body["slide_count"] == 4
    assert [s["note"] for s in body["slides"]] == [NOTES[0], NOTES[1], "", NOTES[2]]
    assert body["slides"][1]["title"] == "2. 단계 세 개"
    assert res.headers["cache-control"] == "no-store"
    enroll(prof, cid, "kim@x.kr")
    student = entered_student(world, token, "kim@x.kr")
    assert student.get(f"/api/classrooms/{cid}/sessions/{sid}/deck/notes").status_code == 401  # 학생은 교수 경로를 못 쓴다
    lee = world.client("lee")
    assert lee.get(f"/api/classrooms/{cid}/sessions/{sid}/deck/notes").status_code == 403


def test_notes_without_a_deck(world):
    prof = world.client("kim")
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "1회차"}, headers=ORIGIN).json()["id"]
    res = prof.get(f"/api/classrooms/{cid}/sessions/{sid}/deck/notes")
    assert res.status_code == 404 and res.json()["detail"] == "이 회차에 올린 슬라이드가 없습니다."


# --- 파일이 사라진 묶음 --------------------------------------------------------------------------


def test_deck_whose_files_are_missing_cannot_be_opened(world):
    prof, cid, sid, deck_id, _ = classroom_with_deck(world)
    shutil.rmtree(world.settings.deck_root / str(cid) / str(deck_id))  # 백업에서 DB만 되살린 경우 등
    item = next(i for i in prof.get(f"/api/classrooms/{cid}/sessions").json()["items"] if i["id"] == sid)
    assert item["deck"]["available"] is False
    res = prof.get(f"/decks/{deck_id}/index.html")
    assert res.status_code == 410 and res.json()["detail"] == CANNOT_OPEN
    notes = prof.get(f"/api/classrooms/{cid}/sessions/{sid}/deck/notes")
    assert notes.status_code == 410 and notes.json()["detail"] == CANNOT_OPEN


def test_listed_deck_is_available_when_files_are_there(world):
    prof, cid, sid, _, _ = classroom_with_deck(world)
    item = next(i for i in prof.get(f"/api/classrooms/{cid}/sessions").json()["items"] if i["id"] == sid)
    assert item["deck"]["available"] is True
    assert json.dumps(item).count("note") == 0  # 회차 목록에 노트는 싣지 않는다


def test_a_link_inside_the_folder_cannot_reach_outside(tmp_path):
    # 올릴 때 링크는 거절하지만, 폴더에 링크가 생겨도(손으로 옮긴 백업 등) 폴더 밖 파일은 내주지 않는다
    from app.deck_files import _safe_target

    folder = tmp_path / "deck"
    (folder / "assets").mkdir(parents=True)
    (folder / "index.html").write_text("<html>")
    (folder / "assets" / "a-12345678.js").write_text("ok")
    secret = tmp_path / "secret.txt"
    secret.write_text("secret")
    (folder / "assets" / "leak.js").symlink_to(secret)
    assert _safe_target(folder, "") == folder / "index.html"
    assert _safe_target(folder, "assets/a-12345678.js") is not None
    assert _safe_target(folder, "assets/leak.js") is None
    assert _safe_target(folder, "assets/../../secret.txt") is None
    assert _safe_target(folder, "classroom-deck.json") is None
