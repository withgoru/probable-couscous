"""GitHubProvider: 토큰 교환과 프로필 조회. 요청 범위는 공개 프로필만(scope를 보내지 않는다, C11)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import ClassVar
from urllib.parse import parse_qs, urlparse

import pytest

from app.auth import AuthError, GitHubProfile, GitHubProvider, urllib_http


class FakeHttp:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        return self.responses.pop(0)


def provider(responses):
    http = FakeHttp(responses)
    return GitHubProvider("cid", "secret", http=http), http


def test_authorize_url_has_client_state_and_redirect_but_no_scope():
    p, _ = provider([])
    url = urlparse(p.authorize_url("st4te", "http://localhost:8000/api/auth/github/callback"))
    q = parse_qs(url.query)
    assert url.netloc == "github.com" and url.path == "/login/oauth/authorize"
    assert q["client_id"] == ["cid"]
    assert q["state"] == ["st4te"]
    assert q["redirect_uri"] == ["http://localhost:8000/api/auth/github/callback"]
    assert "scope" not in q  # 공개 프로필만 읽는다


def test_exchange_posts_code_then_reads_the_public_profile():
    p, http = provider([(200, {"access_token": "tok", "token_type": "bearer"}), (200, {"id": 101, "login": "kim"})])
    profile = p.exchange("the-code", "http://x/cb")
    assert profile == GitHubProfile(github_id=101, login="kim")

    (m1, u1, h1, b1), (m2, u2, h2, _) = http.calls
    assert (m1, u1) == ("POST", "https://github.com/login/oauth/access_token")
    assert h1["Accept"] == "application/json"
    assert b1 == {"client_id": "cid", "client_secret": "secret", "code": "the-code", "redirect_uri": "http://x/cb"}
    assert (m2, u2) == ("GET", "https://api.github.com/user")
    assert h2["Authorization"] == "Bearer tok"
    assert h2["User-Agent"]  # GitHub API는 User-Agent가 필요하다


def test_numeric_id_comes_back_as_int():
    p, _ = provider([(200, {"access_token": "t"}), (200, {"id": "202", "login": "x"})])
    assert p.exchange("c", "u").github_id == 202


@pytest.mark.parametrize(
    "responses",
    [
        [(200, {"error": "bad_verification_code"})],  # GitHub는 오류도 200으로 준다
        [(500, {})],
        [(200, {})],  # 토큰이 없다
        [(200, {"access_token": "t"}), (401, {"message": "Bad credentials"})],
        [(200, {"access_token": "t"}), (200, {"login": "no-id"})],
        [(200, {"access_token": "t"}), (200, {"id": "not-a-number", "login": "x"})],
        [(200, {"access_token": "t"}), (200, {"id": 5})],  # login이 없다
    ],
)
def test_bad_responses_raise_auth_error(responses):
    p, _ = provider(responses)
    with pytest.raises(AuthError):
        p.exchange("c", "u")


def test_network_errors_become_auth_error():
    def boom(*a):
        raise OSError("연결 실패")

    with pytest.raises(AuthError):
        GitHubProvider("cid", "secret", http=boom).exchange("c", "u")


# --- 실제 전송(urllib)을 로컬 가짜 서버로 확인 ---------------------------------


class Handler(BaseHTTPRequestHandler):
    seen: ClassVar[list] = []

    def _reply(self, status, payload):
        data = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        Handler.seen.append(("POST", self.path, dict(self.headers), self.rfile.read(length).decode()))
        self._reply(200, {"access_token": "abc"})

    def do_GET(self):
        Handler.seen.append(("GET", self.path, dict(self.headers), ""))
        if self.path == "/missing":
            self._reply(404, {"message": "Not Found"})
        else:
            self._reply(200, {"id": 7, "login": "kim"})

    def log_message(self, *args):
        pass


@pytest.fixture
def local_server():
    Handler.seen = []
    server = HTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}"
    server.shutdown()


def test_urllib_http_sends_form_body_and_parses_json(local_server):
    status, body = urllib_http("POST", local_server + "/token", {"Accept": "application/json"}, {"code": "a b", "x": "1"})
    assert (status, body) == (200, {"access_token": "abc"})
    _, _, headers, raw = Handler.seen[0]
    assert headers["Content-Type"] == "application/x-www-form-urlencoded"
    assert parse_qs(raw) == {"code": ["a b"], "x": ["1"]}


def test_urllib_http_returns_error_status_with_json_body(local_server):
    assert urllib_http("GET", local_server + "/missing", {}, None) == (404, {"message": "Not Found"})
    assert urllib_http("GET", local_server + "/user", {"Authorization": "Bearer t"}, None) == (200, {"id": 7, "login": "kim"})
    assert Handler.seen[-1][2]["Authorization"] == "Bearer t"
