"""E2E(Playwright) 전용 서버. 운영 서버가 아니다.

- 빌드한 클라이언트(client/build)를 FastAPI가 같은 출처에서 내려준다(운영과 같은 구성).
- 교수 로그인은 가짜 GitHub(누르면 바로 kim으로 로그인)이고, 메일은 실제로 보내지 않고 메모리(OutboxMailer)에 모은다.
- 테스트만 쓰는 경로 `GET /api/test/last-code?to=이메일`이 그 주소로 마지막에 보낸 코드를 알려 준다(plan: 메일은 OutboxMailer로 확인).
- 실행할 때마다 새 임시 DB로 시작한다.

실행: python e2e/server.py <포트>  (server/ 의 패키지가 설치된 파이썬으로)
"""

import re
import sys
import tempfile
from pathlib import Path

import uvicorn
from fastapi import HTTPException

from app.auth import GitHubProfile
from app.config import Settings
from app.mail import OutboxMailer
from app.main import create_app

CLIENT_DIR = Path(__file__).resolve().parents[1]


class FakeGitHub:
    def authorize_url(self, state: str, redirect_uri: str) -> str:
        return f"{redirect_uri}?code=kim&state={state}"

    def exchange(self, code: str, redirect_uri: str) -> GitHubProfile:
        return GitHubProfile(github_id=101, login="kim")


def build_app(port: int):
    db = Path(tempfile.mkdtemp(prefix="e2e-")) / "app.db"
    settings = Settings(
        base_url=f"http://127.0.0.1:{port}",
        professor_github_ids=(101,),
        github_client_id="e2e",
        github_client_secret="e2e",
        server_secret="e2e-only-secret",
        database_path=db,
        client_dist=CLIENT_DIR / "build",
    )
    mailer = OutboxMailer()
    app = create_app(settings, auth_provider=FakeGitHub(), mailer=mailer)

    @app.get("/api/test/last-code")
    def last_code(to: str):
        for message in reversed(mailer.sent):
            if message.to == to:
                return {"code": re.search(r"\b(\d{6})\b", message.text).group(1)}
        raise HTTPException(status_code=404, detail="아직 보낸 메일이 없습니다.")

    app.router.routes.insert(0, app.router.routes.pop())  # 클라이언트 라우트(모든 경로)보다 먼저
    return app


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
    uvicorn.run(build_app(port), host="127.0.0.1", port=port, log_level="warning")
