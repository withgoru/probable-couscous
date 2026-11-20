"""여러 테스트가 같이 쓰는 도구: 가짜 GitHub 제공자와, 로그인한 교수 클라이언트를 만들어 주는 World."""

from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import parse_qs, quote, urlparse

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.auth import AuthError, GitHubProfile
from app.clock import ManualClock
from app.config import Settings
from app.db import connect
from app.main import create_app

BASE = "http://localhost:8000"
ORIGIN = {"Origin": BASE}
PROFILES = {
    "kim": GitHubProfile(github_id=101, login="kim"),
    "lee": GitHubProfile(github_id=202, login="lee"),
    "stranger": GitHubProfile(github_id=999, login="stranger"),
}


class FakeProvider:
    def authorize_url(self, state, redirect_uri):
        return f"https://fake.github/authorize?state={state}&redirect_uri={quote(redirect_uri)}"

    def exchange(self, code, redirect_uri):
        if code not in PROFILES:
            raise AuthError("코드를 확인하지 못했습니다.")
        return PROFILES[code]


@dataclass
class World:
    app: FastAPI
    clock: ManualClock
    settings: Settings

    def client(self, who: str | None = None) -> TestClient:
        """쿠키가 따로인 클라이언트. who가 있으면 그 교수로 로그인한 상태다."""
        client = TestClient(self.app, base_url=BASE, follow_redirects=False)
        if who:
            start = client.get("/api/auth/github/login")
            state = parse_qs(urlparse(start.headers["location"]).query)["state"][0]
            done = client.get(f"/api/auth/github/callback?code={who}&state={state}")
            assert done.headers["location"] == "/courses", f"{who} 로그인 실패: {done.headers['location']}"
        return client

    def db(self):
        return connect(self.settings.database_path)


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
    with TestClient(app, base_url=BASE):  # 시작 때 마이그레이션이 적용되도록 한 번 연다
        yield World(app=app, clock=clock, settings=settings)
