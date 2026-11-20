"""FastAPI 앱 조립. 클라이언트 빌드 결과를 같은 서버가 `/`에서 내려준다(같은 출처)."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse

from app.auth import AuthProvider, GitHubProvider
from app.classrooms import router as classrooms_router
from app.clock import Clock, SystemClock
from app.config import Settings, load_settings
from app.db import MIGRATIONS_DIR, connect, migrate
from app.invites import router as invites_router
from app.join import router as join_router
from app.join_requests import router as join_requests_router
from app.mail import Mailer, MailWorker, OutboxMailer
from app.pending_auth import router as pending_auth_router
from app.realtime import InMemoryRoomBus, RoomBus
from app.routes_auth import router as auth_router
from app.ws_admin import router as ws_admin_router

log = logging.getLogger(__name__)
NOT_BUILT = "클라이언트가 아직 빌드되지 않았습니다. client 폴더에서 npm run build를 실행하세요."
BAD_ORIGIN = "허용되지 않은 출처의 요청입니다. 서비스 주소에서 다시 시도해 주세요."
MUTATING = {"POST", "PUT", "PATCH", "DELETE"}


def _safe_file(dist: Path, relative: str) -> Path | None:
    """dist 밖으로 나가는 경로는 파일로 인정하지 않는다."""
    root = dist.resolve()
    candidate = (root / relative).resolve()
    if candidate.is_file() and candidate.is_relative_to(root):
        return candidate
    return None


def _origin_of(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}"


def create_app(
    settings: Settings | None = None,
    clock: Clock | None = None,
    auth_provider: AuthProvider | None = None,
    mailer: Mailer | None = None,
    start_mail_worker: bool = True,
    bus: RoomBus | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    clock = clock or SystemClock()
    if auth_provider is None and settings.github_client_id and settings.github_client_secret:
        auth_provider = GitHubProvider(settings.github_client_id, settings.github_client_secret)

    mailer = mailer or OutboxMailer()
    mail_worker = MailWorker(
        lambda: connect(settings.database_path), mailer, settings.server_secret, clock, settings.mail_rate_per_sec
    )

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        # 서버가 뜰 때마다 DB를 열어 아직 적용하지 않은 마이그레이션을 적용한다(C13)
        conn = connect(settings.database_path)
        try:
            migrate(conn, MIGRATIONS_DIR, clock)
        finally:
            conn.close()
        if isinstance(mailer, OutboxMailer):
            log.warning("메일 발송이 설정되지 않아 메일을 실제로 보내지 않고 메모리에만 모읍니다. 학생은 교수 대체 경로로 입장합니다.")
        if start_mail_worker:
            mail_worker.start()
        try:
            yield
        finally:
            mail_worker.stop()

    app = FastAPI(title="강의 상호작용 도구", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json", swagger_ui_oauth2_redirect_url=None,
                  lifespan=lifespan)
    app.state.settings = settings
    app.state.clock = clock
    app.state.mailer = mailer
    app.state.bus = bus or InMemoryRoomBus()
    app.state.mail_worker = mail_worker
    app.state.auth_provider = auth_provider  # 설정이 없으면 None. 로그인 시작이 안내와 함께 503을 준다
    allowed_origin = _origin_of(settings.base_url)
    app.state.allowed_origin = allowed_origin

    @app.middleware("http")
    async def check_origin(request: Request, call_next):
        # 변경 요청(POST, PUT, PATCH, DELETE)은 서비스 주소에서 온 것만 받는다. SameSite=Lax에 더한 두 번째 방어
        if request.method in MUTATING and request.headers.get("origin") != allowed_origin:
            return JSONResponse(status_code=403, content={"detail": BAD_ORIGIN})
        return await call_next(request)

    # 아래의 모든 경로를 받는 클라이언트 라우트보다 먼저 등록한다
    app.include_router(auth_router)
    app.include_router(classrooms_router)
    app.include_router(invites_router)
    app.include_router(join_router)
    app.include_router(join_requests_router)
    app.include_router(pending_auth_router)
    app.include_router(ws_admin_router)

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/{full_path:path}", include_in_schema=False)
    def client_app(full_path: str):
        if full_path == "api" or full_path.startswith("api/"):
            raise HTTPException(status_code=404, detail="찾을 수 없는 API 주소입니다.")
        dist = settings.client_dist
        asset = _safe_file(dist, full_path) if full_path else None
        if asset is not None:
            return FileResponse(asset)
        index = _safe_file(dist, "index.html")
        if index is None:
            raise HTTPException(status_code=503, detail=NOT_BUILT)
        return FileResponse(index)

    return app
