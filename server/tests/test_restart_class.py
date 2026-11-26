"""002 T013(C13): 수업 중에 서버 프로세스가 갑자기 죽어도(SIGKILL) 수업 상태가 그대로 남는다.

001 `test_restart_process.py`와 같이 실제 uvicorn 프로세스를 띄워 수업을 시작하고, WebSocket으로 넘기고, 보내고 거둔
뒤 강제로 죽인다. 같은 DB로 새 프로세스를 띄우면 진행 중 회차, 현재 위치, 묶음의 공개 여부, 항목과 거둔 상태,
`version`이 그대로이고 수업을 이어 갈 수 있다.
"""

import json
import re
import time
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from test_restart_process import Process, free_port, servers  # noqa: F401  (servers는 fixture)
from websockets.sync.client import connect as ws_connect

FIXTURE = Path(__file__).parent / "fixtures" / "deck-small.zip"


def login(server):
    prof = server.client()
    state = parse_qs(urlparse(prof.get("/api/auth/github/login").headers["location"]).query)["state"][0]
    assert prof.get(f"/api/auth/github/callback?code=kim&state={state}").headers["location"] == "/courses"
    return prof


def enter(server, token, email):
    student = server.client()
    assert student.get(f"/api/join/{token}").status_code == 200  # 기기 쿠키
    assert student.post(f"/api/join/{token}/email", json={"email": email}).json()["next"] == "code"
    deadline = time.monotonic() + 10  # 메일 작업 스레드가 보낼 때까지
    while not (text := student.get("/api/test/last-mail").json()["text"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    code = re.search(r"\b(\d{6})\b", text).group(1)
    assert student.post(f"/api/join/{token}/code", json={"email": email, "code": code}).status_code == 200
    assert student.post(f"/api/join/{token}/enter").status_code == 200
    return student


@contextmanager
def socket(server, client, cid):
    """그 사람의 쿠키로 수업 WebSocket에 붙어 `ready`까지 받는다."""
    cookie = "; ".join(f"{name}={value}" for name, value in client.cookies.items())
    with ws_connect(
        f"ws://127.0.0.1:{server.port}/ws/class/{cid}",
        additional_headers={"Origin": server.base, "Cookie": cookie},
        open_timeout=10,
    ) as ws:
        assert json.loads(ws.recv(timeout=10))["type"] == "ready"
        yield ws


def until(ws, type_):
    while True:
        message = json.loads(ws.recv(timeout=10))
        if message["type"] == type_:
            return message


def goto(ws, sid, slide, click, req):
    ws.send(json.dumps({"type": "goto", "session_id": sid, "slide": slide, "click": click, "req": req}))
    return until(ws, "ack")


@pytest.mark.constitution
def test_c13_a_class_survives_a_killed_process(servers, tmp_path):  # noqa: F811
    db, port = tmp_path / "app.db", free_port()
    a = Process(port, db)
    servers.append(a)

    prof = login(a)
    cid = prof.post("/api/classrooms", json={"name": "웹"}).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    assert prof.post(
        f"/api/classrooms/{cid}/roster", json={"student_no": "1", "name": "김철수", "email": "kim@x.kr"}
    ).status_code == 201
    student = enter(a, token, "kim@x.kr")
    sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "1회차"}).json()["id"]
    upload = prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck",
        params={"filename": "a.zip"},
        content=FIXTURE.read_bytes(),
        headers={"Content-Type": "application/zip"},
    )
    assert upload.status_code == 200, upload.text
    deck_id = upload.json()["deck"]["id"]
    assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/start").status_code == 200

    with socket(a, prof, cid) as ws:
        goto(ws, sid, 3, 1, "a")
        assert goto(ws, sid, 2, 0, "b")["version"] == 3  # 되돌아왔다
    kept = prof.post(f"/api/classrooms/{cid}/sessions/{sid}/items", json={"body": "과제", "client_key": "k1"}).json()
    gone = prof.post(
        f"/api/classrooms/{cid}/sessions/{sid}/items", json={"url": "https://example.com/x", "client_key": "k2"}
    ).json()
    assert prof.post(f"/api/classrooms/{cid}/sessions/{sid}/items/{gone['item']['id']}/retract").status_code == 200
    assert prof.put(f"/api/classrooms/{cid}/sessions/{sid}/deck/visibility", json={"public": True}).status_code == 200
    before = prof.get(f"/api/class/{cid}/sessions/{sid}/live").json()
    assert before["session"]["version"] == 7

    a.kill()  # 답을 받은 뒤 바로 죽인다. 종료 처리는 없다
    b = Process(port, db)
    servers.append(b)
    prof, student = (b.client(cookies=c.cookies) for c in (prof, student))

    after = prof.get(f"/api/class/{cid}/sessions/{sid}/live").json()
    assert after == before  # 상태 전체가 그대로다
    assert after["session"]["status"] == "live"
    assert after["current"] == {"slide": 2, "click": 0}
    assert after["deck"]["public"] is True
    assert [(i["id"], i["retracted_at"] is not None) for i in after["items"]] == [
        (kept["item"]["id"], False),
        (gone["item"]["id"], True),
    ]
    assert prof.get(f"/api/class/{cid}/sessions").json()["live_session_id"] == sid

    seen = student.get(f"/api/class/{cid}/sessions/{sid}/live").json()
    assert [i["id"] for i in seen["items"]] == [kept["item"]["id"]]  # 거둔 항목은 다시 나타나지 않는다
    assert student.get(f"/decks/{deck_id}/index.html").status_code == 200

    # 수업을 그대로 이어 간다: 새 프로세스의 WebSocket으로 넘기면 학생이 받고, 버전은 이어서 오른다
    with socket(b, prof, cid) as teacher, socket(b, student, cid) as phone:
        assert goto(teacher, sid, 4, 0, "c")["version"] == 8
        assert until(phone, "position")["current"] == {"slide": 4, "click": 0}
