"""C13(T032): 서버 프로세스가 갑자기 죽어도(종료 처리 없이 SIGKILL) 성공으로 답한 쓰기는 남는다.

`test_restart.py`는 같은 프로세스에서 앱을 새로 만들어(정상 종료 뒤) 확인한다. 여기서는 실제 uvicorn 프로세스를 띄워
요청을 처리하게 한 뒤 강제로 죽이고, 같은 DB로 새 프로세스를 띄워 확인한다. `synchronous=FULL`(C13)이 지키는 부분이다.
"""

import os
import re
import signal
import socket
import subprocess
import sys
import textwrap
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

SERVER_DIR = Path(__file__).resolve().parents[1]

# 테스트용 서버: 가짜 GitHub 로그인, 메일은 보내지 않고 내용만 개발용 경로로 보인다(이 테스트 안에서만 쓰는 스크립트)
SCRIPT = textwrap.dedent(
    """
    import sys
    from pathlib import Path

    import uvicorn

    from app.auth import GitHubProfile
    from app.config import Settings
    from app.mail import OutboxMailer
    from app.main import create_app

    port, db = int(sys.argv[1]), Path(sys.argv[2])

    class Fake:
        def authorize_url(self, state, redirect_uri):
            return f"{redirect_uri}?code=kim&state={state}"

        def exchange(self, code, redirect_uri):
            return GitHubProfile(github_id=101, login="kim")

    settings = Settings(
        base_url=f"http://127.0.0.1:{port}", professor_github_ids=(101,), github_client_id="c",
        github_client_secret="s", server_secret="restart-test", database_path=db, client_dist=db.parent / "none",
    )
    mailer = OutboxMailer()
    app = create_app(settings, auth_provider=Fake(), mailer=mailer)

    @app.get("/api/test/last-mail")
    def last_mail():
        return {"text": mailer.sent[-1].text if mailer.sent else None}

    app.router.routes.insert(0, app.router.routes.pop())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    """
)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Process:
    def __init__(self, port: int, db: Path):
        self.port = port
        self.proc = subprocess.Popen(
            [sys.executable, "-c", SCRIPT, str(port), str(db)],
            cwd=SERVER_DIR,
            env={**os.environ, "PYTHONPATH": str(SERVER_DIR)},
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
        self.base = f"http://127.0.0.1:{port}"
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            if self.proc.poll() is not None:
                raise RuntimeError(f"서버가 뜨지 못했습니다: {self.proc.stderr.read().decode()[-2000:]}")
            try:
                if httpx.get(f"{self.base}/api/health", timeout=0.5).status_code == 200:
                    return
            except httpx.HTTPError:
                time.sleep(0.1)
        self.kill()
        raise RuntimeError("서버가 20초 안에 뜨지 않았습니다.")

    def client(self, cookies: httpx.Cookies | None = None) -> httpx.Client:
        return httpx.Client(base_url=self.base, headers={"Origin": self.base}, cookies=cookies, follow_redirects=False)

    def kill(self) -> None:
        if self.proc.poll() is None:
            self.proc.send_signal(signal.SIGKILL)  # 종료 처리 없이 바로 죽인다
            self.proc.wait(timeout=10)


@pytest.fixture
def servers():
    started: list[Process] = []
    yield started
    for p in started:
        p.kill()


@pytest.mark.constitution
def test_c13_answered_writes_survive_a_killed_process(servers, tmp_path):
    db, port = tmp_path / "app.db", free_port()
    a = Process(port, db)
    servers.append(a)

    prof = a.client()
    state = parse_qs(urlparse(prof.get("/api/auth/github/login").headers["location"]).query)["state"][0]
    assert prof.get(f"/api/auth/github/callback?code=kim&state={state}").headers["location"] == "/courses"
    cid = prof.post("/api/classrooms", json={"name": "웹"}).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    for no, name, email in (("1", "김철수", "kim@x.kr"), ("2", "이영희", "lee@x.kr")):
        assert prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}).status_code == 201

    kim = a.client()
    assert kim.get(f"/api/join/{token}").status_code == 200  # 기기 쿠키
    assert kim.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}).json()["next"] == "code"
    deadline = time.monotonic() + 10  # 메일 작업 스레드가 보낼 때까지
    while not (text := kim.get("/api/test/last-mail").json()["text"]) and time.monotonic() < deadline:
        time.sleep(0.1)
    code = re.search(r"\b(\d{6})\b", text).group(1)
    nickname = kim.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": code}).json()["nickname"]
    assert kim.post(f"/api/join/{token}/enter").status_code == 200

    lee = a.client()
    lee.get(f"/api/join/{token}")
    lee.post(f"/api/join/{token}/email", json={"email": "lee@x.kr"})
    assert lee.post(f"/api/join/{token}/notify-professor", json={"email": "lee@x.kr"}).status_code == 200
    a.client().post(f"/api/join/{token}/request-access", json={"email": "park@x.kr", "name": "박민수", "student_no": "9"})
    pending_code = prof.get(f"/api/classrooms/{cid}/pending-auth").json()["items"][0]["code"]

    a.kill()  # 답을 받은 뒤 바로 죽인다. 종료 처리는 없다
    b = Process(port, db)
    servers.append(b)

    prof, kim, lee = (b.client(cookies=c.cookies) for c in (prof, kim, lee))
    assert prof.get("/api/me").status_code == 200
    assert [e["name"] for e in prof.get(f"/api/classrooms/{cid}/roster").json()["entries"]] == ["김철수", "이영희"]
    assert kim.get(f"/api/join/{token}/me").json() == {"state": "entered", "nickname": nickname, "classroom": "웹"}
    assert [r["name"] for r in prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"]] == ["박민수"]
    assert prof.get(f"/api/classrooms/{cid}/pending-auth").json()["items"][0]["code"] == pending_code
    assert lee.post(f"/api/join/{token}/code", json={"email": "lee@x.kr", "code": pending_code}).status_code == 200
