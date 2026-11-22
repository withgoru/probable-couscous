"""C13(T032): 서버를 다시 시작해도 상태가 그대로 남는다(스펙 '오류와 예외 동작'의 서버 재시작 항목).

"다시 시작"은 같은 DB 파일로 앱을 새로 만드는 것이다. 이 서버는 실행 중 상태를 앱 객체(실시간 버스, 메일 작업)에만 두고
모듈 전역에는 두지 않으므로, 앱을 새로 만들면 메모리는 모두 처음 상태가 된다. 그 위에서 DB에서 다시 읽어
명단, 챌린지, 로그인 유지, 입장 요청, 대기 중인 인증, 교수 로그인, 닉네임, 보내지 못한 메일이 이어지는지 본다.
"""

import re
from dataclasses import dataclass
from urllib.parse import parse_qs, urlparse

import pytest
from conftest import BASE, ORIGIN, FakeProvider
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.mail import OutboxMailer
from app.main import create_app


@dataclass
class Server:
    """한 번 띄운 서버. stop() 하면 종료 처리(lifespan)를 거치고, 메모리에 있던 것은 버려진다."""

    app: FastAPI
    runner: TestClient
    stopped: bool = False

    def client(self, cookies_from: TestClient | None = None) -> TestClient:
        c = TestClient(self.app, base_url=BASE, follow_redirects=False)
        if cookies_from is not None:  # 브라우저는 서버가 다시 떠도 쿠키를 그대로 갖고 있다
            for cookie in cookies_from.cookies.jar:
                c.cookies.set(cookie.name, cookie.value, domain=cookie.domain, path=cookie.path)
        return c

    def stop(self) -> None:
        if not self.stopped:
            self.stopped = True
            self.runner.__exit__(None, None, None)


@pytest.fixture
def boot(world):
    """world와 같은 설정·DB·시계로 서버를 새로 띄운다. 띄울 때마다 새 앱, 새 메일함, 새 실시간 버스다."""
    servers: list[Server] = []

    def start() -> Server:
        app = create_app(world.settings, clock=world.clock, auth_provider=FakeProvider(), mailer=OutboxMailer(), start_mail_worker=False)
        runner = TestClient(app, base_url=BASE)
        runner.__enter__()  # 시작 처리: 마이그레이션 적용
        server = Server(app, runner)
        servers.append(server)
        return server

    yield start
    for s in servers:
        s.stop()


def login(server: Server, who="kim") -> TestClient:
    c = server.client()
    start = c.get("/api/auth/github/login")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    assert c.get(f"/api/auth/github/callback?code={who}&state={state}").headers["location"] == "/courses"
    return c


def mailed_code(server: Server) -> str:
    server.app.state.mail_worker.process_due()
    return re.search(r"\b(\d{6})\b", server.app.state.mailer.sent[-1].text).group(1)


def restart(server: Server, boot) -> Server:
    server.stop()
    fresh = boot()
    assert fresh.app is not server.app and fresh.app.state.bus is not server.app.state.bus
    return fresh


# --- 한 번에 모두: 수업 중에 서버가 다시 떴다 -------------------------------------------------------------------------


@pytest.mark.constitution
def test_c13_everything_a_class_depends_on_survives_a_restart(boot):
    a = boot()
    prof = login(a)
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    for no, name, email in (("1", "김철수", "kim@x.kr"), ("2", "이영희", "lee@x.kr"), ("3", "최지은", "choi@x.kr")):
        assert prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": no, "name": name, "email": email}, headers=ORIGIN).status_code == 201

    # 김철수: 로그인 유지로 입장했다
    kim = a.client()
    kim.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN)
    nickname = kim.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": mailed_code(a)}, headers=ORIGIN).json()["nickname"]
    assert kim.post(f"/api/join/{token}/enter", headers=ORIGIN).status_code == 200

    # 이영희: 코드를 받았지만 아직 입력하지 않았다
    lee = a.client()
    lee.post(f"/api/join/{token}/email", json={"email": "lee@x.kr"}, headers=ORIGIN)
    lee_code = mailed_code(a)

    # 최지은: 메일이 오지 않아 교수님께 알렸다
    choi = a.client()
    choi.post(f"/api/join/{token}/email", json={"email": "choi@x.kr"}, headers=ORIGIN)
    choi.post(f"/api/join/{token}/notify-professor", json={"email": "choi@x.kr"}, headers=ORIGIN)

    # 박민수: 명단에 없어 입장 요청을 보냈다
    a.client().post(f"/api/join/{token}/request-access", json={"email": "park@x.kr", "name": "박민수", "student_no": "9"}, headers=ORIGIN)

    pending_before = prof.get(f"/api/classrooms/{cid}/pending-auth").json()["items"]

    b = restart(a, boot)
    prof, kim, lee, choi = (b.client(cookies_from=c) for c in (prof, kim, lee, choi))

    # 교수 로그인과 명단
    assert prof.get("/api/me").status_code == 200
    roster = prof.get(f"/api/classrooms/{cid}/roster").json()
    assert [e["name"] for e in roster["entries"]] == ["김철수", "이영희", "최지은"]
    assert [e["entered"] for e in roster["entries"]] == [True, False, False]
    # 로그인 유지: 이메일·코드 없이 바로 입장, 닉네임은 같다
    assert kim.get(f"/api/join/{token}/me").json() == {"state": "entered", "nickname": nickname, "classroom": "웹"}
    # 챌린지: 다시 뜨기 전에 받은 코드로 입장할 수 있다
    assert lee.post(f"/api/join/{token}/code", json={"email": "lee@x.kr", "code": lee_code}, headers=ORIGIN).status_code == 200
    # 입장 요청
    assert [r["name"] for r in prof.get(f"/api/classrooms/{cid}/join-requests").json()["requests"]] == ["박민수"]
    # 대기 중인 인증: 같은 코드가 보이고, 학생은 그 코드로 입장한다
    pending_after = prof.get(f"/api/classrooms/{cid}/pending-auth").json()["items"]
    assert [(p["name"], p["code"]) for p in pending_after] == [(p["name"], p["code"]) for p in pending_before]
    code = pending_after[0]["code"]
    assert choi.post(f"/api/join/{token}/code", json={"email": "choi@x.kr", "code": code}, headers=ORIGIN).status_code == 200


# --- 항목별 ------------------------------------------------------------------------------------------------------------


def test_the_professor_stays_logged_in_and_logout_still_ends_it(boot):
    a = boot()
    prof = login(a)
    b = restart(a, boot)
    prof = b.client(cookies_from=prof)
    assert prof.get("/api/me").json()["login"] == "kim"
    assert prof.post("/api/auth/logout", headers=ORIGIN).status_code in (200, 204)
    assert prof.get("/api/me").status_code == 401


def test_a_login_started_before_the_restart_can_finish_after_it(boot):
    # GitHub 로그인 화면에 가 있는 사이 서버가 다시 떠도 돌아와서 로그인이 끝난다(로그인 확인 값은 쿠키에 있다)
    a = boot()
    c = a.client()
    state = parse_qs(urlparse(c.get("/api/auth/github/login").headers["location"]).query)["state"][0]
    b = restart(a, boot)
    c = b.client(cookies_from=c)
    assert c.get(f"/api/auth/github/callback?code=kim&state={state}").headers["location"] == "/courses"


def test_wrong_tries_and_the_resend_wait_are_remembered(boot, world):
    a = boot()
    prof = login(a)
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": "1", "name": "김", "email": "kim@x.kr"}, headers=ORIGIN)
    s = a.client()
    s.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN)
    code = mailed_code(a)
    wrong = "000000" if code != "000000" else "111111"
    s.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": wrong}, headers=ORIGIN)
    b = restart(a, boot)
    s = b.client(cookies_from=s)
    again = s.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": wrong}, headers=ORIGIN)
    assert again.json()["detail"]["remaining"] == 3  # 다시 뜨기 전의 1번에 이어서 센다
    too_soon = s.post(f"/api/join/{token}/resend", json={"email": "kim@x.kr"}, headers=ORIGIN)
    assert too_soon.status_code == 429  # 60초 간격도 이어진다


def test_a_mail_queued_before_the_restart_is_sent_after_it(boot):
    # 코드 메일 요청은 DB에 먼저 쌓인다(C13). 보내기 전에 서버가 다시 떠도 새 서버가 보낸다
    a = boot()
    prof = login(a)
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": "1", "name": "김", "email": "kim@x.kr"}, headers=ORIGIN)
    s = a.client()
    assert s.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN).json()["next"] == "code"
    assert a.app.state.mailer.sent == []  # 아직 보내지 않았다
    b = restart(a, boot)
    s = b.client(cookies_from=s)
    code = mailed_code(b)
    assert b.app.state.mailer.sent[-1].to == "kim@x.kr"
    assert s.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": code}, headers=ORIGIN).status_code == 200


def test_a_cut_login_and_an_archive_stay_in_force(boot, world):
    a = boot()
    prof = login(a)
    cid = prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN).json()["id"]
    cid2 = prof.post("/api/classrooms", json={"name": "앱"}, headers=ORIGIN).json()["id"]
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    token2 = prof.get(f"/api/classrooms/{cid2}/invite").json()["token"]
    entry = prof.post(f"/api/classrooms/{cid}/roster", json={"student_no": "1", "name": "김", "email": "kim@x.kr"}, headers=ORIGIN).json()["id"]
    prof.post(f"/api/classrooms/{cid2}/roster", json={"student_no": "1", "name": "김", "email": "kim@x.kr"}, headers=ORIGIN)
    s = a.client()
    s.post(f"/api/join/{token}/email", json={"email": "kim@x.kr"}, headers=ORIGIN)
    s.post(f"/api/join/{token}/code", json={"email": "kim@x.kr", "code": mailed_code(a)}, headers=ORIGIN)
    s.post(f"/api/join/{token}/enter", headers=ORIGIN)
    s.post(f"/api/join/{token2}/enter", headers=ORIGIN)
    world.clock.advance(minutes=1)  # 끊기는 인증한 뒤의 일이다
    prof.post(f"/api/classrooms/{cid}/roster/{entry}/revoke-login", headers=ORIGIN)
    prof.post(f"/api/classrooms/{cid2}/archive", headers=ORIGIN)
    b = restart(a, boot)
    s = b.client(cookies_from=s)
    assert s.get(f"/api/join/{token}/me").json() == {"state": "login"}  # 끊긴 로그인은 끊긴 채
    assert s.get(f"/api/join/{token2}/me").status_code == 403  # 보관은 보관된 채


def test_starting_again_does_not_apply_migrations_twice_or_change_data(boot, world):
    a = boot()
    prof = login(a)
    prof.post("/api/classrooms", json={"name": "웹"}, headers=ORIGIN)
    db = world.db()
    before = [tuple(r) for r in db.execute("SELECT * FROM schema_migrations ORDER BY 1")]
    a.stop()
    for _ in range(2):
        boot().stop()
    db = world.db()
    assert [tuple(r) for r in db.execute("SELECT * FROM schema_migrations ORDER BY 1")] == before
    assert db.execute("SELECT COUNT(*) FROM classrooms").fetchone()[0] == 1
