"""AC1~AC4의 서버 쪽: GitHub 로그인, 허용 목록(숫자 ID), 로그인 상태, 로그아웃, Origin 검사."""

import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlparse

import pytest
from fastapi.testclient import TestClient

from app.auth import SESSION_COOKIE, STATE_COOKIE, AuthError, GitHubProfile
from app.clock import ManualClock
from app.config import Settings
from app.db import connect
from app.main import create_app

BASE = "http://localhost:8000"
ORIGIN = {"Origin": BASE}
PROFILES = {
    "kim": GitHubProfile(github_id=101, login="kim"),
    "kim-renamed": GitHubProfile(github_id=101, login="kim-new-name"),
    "stranger": GitHubProfile(github_id=999, login="stranger"),
    "impostor": GitHubProfile(github_id=555, login="kim"),  # 허용된 사람과 같은 이름이지만 다른 숫자 ID
}


class FakeProvider:
    def __init__(self):
        self.exchanges = []

    def authorize_url(self, state, redirect_uri):
        return f"https://fake.github/authorize?state={state}&redirect_uri={quote(redirect_uri)}"

    def exchange(self, code, redirect_uri):
        self.exchanges.append(code)
        if code not in PROFILES:
            raise AuthError("코드를 확인하지 못했습니다.")
        return PROFILES[code]


@pytest.fixture
def env(tmp_path):
    clock = ManualClock(datetime(2026, 3, 1, 9, tzinfo=UTC))
    provider = FakeProvider()
    settings = Settings(
        base_url=BASE,
        professor_github_ids=(101,),
        github_client_id="cid",
        github_client_secret="secret",
        server_secret="s",
        database_path=tmp_path / "app.db",
        client_dist=tmp_path / "none",
    )
    app = create_app(settings, clock=clock, auth_provider=provider)
    with TestClient(app, base_url=BASE, follow_redirects=False) as client:
        yield client, clock, provider, settings


def login(client, code):
    start = client.get("/api/auth/github/login")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    return client.get(f"/api/auth/github/callback?code={code}&state={state}")


def rows(settings, sql):
    db = connect(settings.database_path)
    try:
        return db.execute(sql).fetchall()
    finally:
        db.close()


# --- 로그인 시작 ----------------------------------------------------------------


def test_login_redirects_to_github_with_state_and_callback_url(env):
    client, _, _, _ = env
    res = client.get("/api/auth/github/login")
    assert res.status_code == 302
    q = parse_qs(urlparse(res.headers["location"]).query)
    assert q["redirect_uri"] == [f"{BASE}/api/auth/github/callback"]
    assert len(q["state"][0]) >= 32
    cookie = res.headers["set-cookie"].lower()
    assert f"{STATE_COOKIE}=" in cookie and "httponly" in cookie and "samesite=lax" in cookie
    assert "secure" not in cookie  # 개발 주소(http)에서는 Secure를 붙이지 않는다


def test_cookies_are_secure_when_the_service_runs_on_https(tmp_path):
    settings = Settings(base_url="https://class.example.kr", github_client_id="c", github_client_secret="s",
                        database_path=tmp_path / "a.db", client_dist=tmp_path / "n")
    with TestClient(create_app(settings, auth_provider=FakeProvider()), base_url="https://class.example.kr",
                    follow_redirects=False) as client:
        assert "secure" in client.get("/api/auth/github/login").headers["set-cookie"].lower()


def test_login_says_what_to_fix_when_github_is_not_configured(tmp_path):
    settings = Settings(database_path=tmp_path / "a.db", client_dist=tmp_path / "n")
    with TestClient(create_app(settings), base_url=BASE, follow_redirects=False) as client:
        res = client.get("/api/auth/github/login")
    assert res.status_code == 503
    assert "GITHUB_CLIENT_ID" in res.json()["detail"]


# --- AC1: 허용된 계정 ---------------------------------------------------------------


def test_allowed_account_gets_a_session_and_lands_on_courses(env):
    client, _, provider, settings = env
    res = login(client, "kim")
    assert res.status_code == 302 and res.headers["location"] == "/courses"
    assert SESSION_COOKIE in client.cookies
    cookie = next(c for c in res.headers.get_list("set-cookie") if c.startswith(SESSION_COOKIE)).lower()
    assert "httponly" in cookie and "samesite=lax" in cookie
    assert [dict(r) for r in rows(settings, "SELECT github_id, login FROM professors")] == [{"github_id": 101, "login": "kim"}]
    assert provider.exchanges == ["kim"]


def test_me_returns_the_logged_in_professor_and_is_not_cacheable(env):
    client, _, _, _ = env
    login(client, "kim")
    res = client.get("/api/me")
    assert res.status_code == 200
    assert res.json() == {"github_id": 101, "login": "kim"}
    assert "no-store" in res.headers["cache-control"]


def test_session_token_is_stored_only_as_a_hash(env):
    client, _, _, settings = env
    login(client, "kim")
    raw = client.cookies[SESSION_COOKIE]
    stored = [r["token_hash"] for r in rows(settings, "SELECT token_hash FROM professor_sessions")]
    assert len(stored) == 1 and stored[0] != raw
    assert re.fullmatch(r"[0-9a-f]{64}", stored[0])
    assert raw not in str([tuple(r) for r in rows(settings, "SELECT * FROM professor_sessions")])


def test_login_name_is_refreshed_but_identity_is_the_numeric_id(env):
    client, _, _, settings = env
    login(client, "kim")
    client.cookies.clear()
    login(client, "kim-renamed")  # 같은 숫자 ID, 바뀐 로그인 이름
    got = [dict(r) for r in rows(settings, "SELECT github_id, login FROM professors")]
    assert got == [{"github_id": 101, "login": "kim-new-name"}]


# --- AC2: 허용 목록 밖 ------------------------------------------------------------------


def test_account_not_on_the_allow_list_is_refused_without_a_session(env):
    client, _, _, settings = env
    res = login(client, "stranger")
    assert res.status_code == 302 and res.headers["location"] == "/login?error=not_allowed"
    assert SESSION_COOKIE not in client.cookies
    assert rows(settings, "SELECT * FROM professors") == []
    assert rows(settings, "SELECT * FROM professor_sessions") == []
    assert client.get("/api/me").status_code == 401


def test_allow_list_is_by_numeric_id_not_by_login_name(env):
    client, _, _, _ = env
    res = login(client, "impostor")  # 이름은 허용된 사람과 같다
    assert res.headers["location"] == "/login?error=not_allowed"


# --- state 검증과 실패 처리 ---------------------------------------------------------------


def test_wrong_state_is_refused_and_github_is_not_called(env):
    client, _, provider, _ = env
    client.get("/api/auth/github/login")
    res = client.get("/api/auth/github/callback?code=kim&state=forged")
    assert res.headers["location"] == "/login?error=state"
    assert provider.exchanges == []
    assert SESSION_COOKIE not in client.cookies


def test_callback_without_state_cookie_is_refused(env):
    client, _, provider, _ = env
    res = client.get("/api/auth/github/callback?code=kim&state=anything")
    assert res.headers["location"] == "/login?error=state"
    assert provider.exchanges == []


def test_state_is_single_use(env):
    client, _, provider, _ = env
    start = client.get("/api/auth/github/login")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    client.get(f"/api/auth/github/callback?code=kim&state={state}")
    client.cookies.pop(SESSION_COOKIE)
    again = client.get(f"/api/auth/github/callback?code=kim&state={state}")
    assert again.headers["location"] == "/login?error=state"
    assert provider.exchanges == ["kim"]


def test_user_denying_access_at_github_goes_back_to_login(env):
    client, _, provider, _ = env
    start = client.get("/api/auth/github/login")
    state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
    res = client.get(f"/api/auth/github/callback?error=access_denied&state={state}")
    assert res.headers["location"] == "/login?error=cancelled"
    assert provider.exchanges == []


def test_github_failure_goes_back_to_login_instead_of_a_server_error(env):
    client, _, _, _ = env
    res = login(client, "unknown-code")
    assert res.status_code == 302 and res.headers["location"] == "/login?error=github"


# --- AC3: 로그인하지 않은 요청 ------------------------------------------------------------


def test_requests_without_a_valid_session_get_401(env):
    client, _, _, _ = env
    res = client.get("/api/me")
    assert res.status_code == 401 and "로그인" in res.json()["detail"]
    client.cookies.set(SESSION_COOKIE, "garbage")
    assert client.get("/api/me").status_code == 401


# --- AC4: 로그아웃 ----------------------------------------------------------------------


def test_logout_revokes_the_session_immediately(env):
    client, _, _, settings = env
    login(client, "kim")
    token = client.cookies[SESSION_COOKIE]
    res = client.post("/api/auth/logout", headers=ORIGIN)
    assert res.status_code == 204
    assert rows(settings, "SELECT revoked_at FROM professor_sessions")[0]["revoked_at"] is not None
    client.cookies.set(SESSION_COOKIE, token)  # 훔친 토큰을 다시 써도
    assert client.get("/api/me").status_code == 401


def test_logout_without_a_session_is_harmless(env):
    client, _, _, _ = env
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 204


def test_session_expires_after_14_days(env):
    client, clock, _, _ = env
    login(client, "kim")
    clock.advance(days=13)
    assert client.get("/api/me").status_code == 200
    clock.advance(days=2)
    assert client.get("/api/me").status_code == 401


# --- Origin 검사 ------------------------------------------------------------------------


def test_mutating_requests_need_the_service_origin(env):
    client, _, _, _ = env
    login(client, "kim")
    assert client.post("/api/auth/logout").status_code == 403  # Origin 없음
    assert client.post("/api/auth/logout", headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.post("/api/auth/logout", headers={"Origin": "http://localhost:9999"}).status_code == 403
    assert client.get("/api/me").status_code == 200  # 거부된 요청은 세션을 건드리지 않았다
    assert client.post("/api/auth/logout", headers=ORIGIN).status_code == 204


def test_origin_rejection_explains_what_happened(env):
    client, _, _, _ = env
    res = client.post("/api/auth/logout", headers={"Origin": "https://evil.example"})
    assert res.status_code == 403 and "출처" in res.json()["detail"]


def test_reading_requests_do_not_need_an_origin(env):
    client, _, _, _ = env
    assert client.get("/api/health").status_code == 200
