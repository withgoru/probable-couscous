"""교수 로그인(GitHub OAuth)과 로그인 상태에 쓰는 도구.

- 요청 범위는 공개 프로필만 읽는다. scope를 보내지 않아 이메일을 읽지 않는다(C11).
- 로그인 이름은 바뀔 수 있어 허용 목록은 숫자 ID로 비교한다(routes_auth).
- 로그인 상태 토큰은 쿠키에만 있고 DB에는 해시만 저장한다.
- 외부 호출은 표준 urllib로 두 번뿐이다(토큰 교환, 프로필 조회). 의존성을 늘리지 않는다(C17).
"""

from __future__ import annotations

import hashlib
import json
import secrets
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import timedelta
from typing import Protocol
from urllib.parse import urlencode

SESSION_COOKIE = "session"
STATE_COOKIE = "oauth_state"
SESSION_LIFETIME = timedelta(days=14)
STATE_MAX_AGE_SECONDS = 600

AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
TOKEN_URL = "https://github.com/login/oauth/access_token"
USER_URL = "https://api.github.com/user"
USER_AGENT = "classroom-tool"


class AuthError(Exception):
    """제공자(GitHub)와 주고받다 실패했을 때."""


@dataclass(frozen=True)
class GitHubProfile:
    github_id: int
    login: str


class AuthProvider(Protocol):
    """교수 로그인 제공자. 지금은 GitHub 하나만 구현한다(C15)."""

    def authorize_url(self, state: str, redirect_uri: str) -> str: ...

    def exchange(self, code: str, redirect_uri: str) -> GitHubProfile: ...


HttpFn = Callable[[str, str, dict[str, str], dict[str, str] | None], tuple[int, dict]]


def urllib_http(
    method: str, url: str, headers: dict[str, str], body: dict[str, str] | None
) -> tuple[int, dict]:
    data = urlencode(body).encode() if body is not None else None
    request_headers = dict(headers)
    if data is not None:
        request_headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=request_headers, method=method)
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            status, raw = response.status, response.read()
    except urllib.error.HTTPError as err:
        status, raw = err.code, err.read()
    try:
        payload = json.loads(raw or b"{}")
    except ValueError:
        payload = {}
    return status, payload if isinstance(payload, dict) else {}


class GitHubProvider:
    def __init__(self, client_id: str, client_secret: str, http: HttpFn = urllib_http) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._http = http

    def authorize_url(self, state: str, redirect_uri: str) -> str:
        query = urlencode({"client_id": self._client_id, "redirect_uri": redirect_uri, "state": state})
        return f"{AUTHORIZE_URL}?{query}"

    def exchange(self, code: str, redirect_uri: str) -> GitHubProfile:
        try:
            status, body = self._http(
                "POST",
                TOKEN_URL,
                {"Accept": "application/json", "User-Agent": USER_AGENT},
                {
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "code": code,
                    "redirect_uri": redirect_uri,
                },
            )
            token = body.get("access_token")
            if status != 200 or "error" in body or not token:
                raise AuthError("GitHub가 로그인 코드를 받아들이지 않았습니다.")
            status, user = self._http(
                "GET",
                USER_URL,
                {
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/vnd.github+json",
                    "User-Agent": USER_AGENT,
                },
                None,
            )
        except OSError as err:
            raise AuthError("GitHub에 연결하지 못했습니다.") from err
        if status != 200:
            raise AuthError("GitHub 프로필을 읽지 못했습니다.")
        try:
            return GitHubProfile(github_id=int(user["id"]), login=str(user["login"]))
        except (KeyError, TypeError, ValueError):
            raise AuthError("GitHub 프로필 형식이 예상과 다릅니다.") from None


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
