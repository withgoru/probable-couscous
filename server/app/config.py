"""설정 로더. 환경 변수가 `.env` 파일보다 우선한다. 키 목록은 저장소 루트의 `.env.example`과 같아야 한다."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


class ConfigError(ValueError):
    """설정 값이 잘못됐을 때. 어느 키를 어떻게 고치는지 메시지에 담는다."""


@dataclass(frozen=True)
class Settings:
    professor_github_ids: tuple[int, ...] = ()
    github_client_id: str = ""
    github_client_secret: str = ""
    server_secret: str = ""
    base_url: str = "http://localhost:8000"
    resend_api_key: str = ""
    mail_from: str = ""
    mail_rate_per_sec: int = 8
    database_path: Path = REPO_ROOT / "server" / "data" / "app.db"
    client_dist: Path = REPO_ROOT / "client" / "build"

    @classmethod
    def env_names(cls) -> list[str]:
        return [f.name.upper() for f in fields(cls)]


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


def _to_int(key: str, value: str) -> int:
    try:
        return int(value.strip())
    except ValueError:
        raise ConfigError(f"{key}는 숫자여야 합니다. 현재 값: {value!r}") from None


def _to_id_list(key: str, value: str) -> tuple[int, ...]:
    parts = [p.strip() for p in value.split(",") if p.strip()]
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        raise ConfigError(f"{key}는 쉼표로 구분한 숫자(GitHub 숫자 ID)여야 합니다. 현재 값: {value!r}") from None


def load_settings(
    env: Mapping[str, str] | None = None,
    dotenv_path: Path | None = None,
) -> Settings:
    merged = _parse_dotenv(dotenv_path if dotenv_path is not None else REPO_ROOT / ".env")
    merged.update(os.environ if env is None else env)

    kwargs: dict[str, object] = {}
    for f in fields(Settings):
        key = f.name.upper()
        raw = merged.get(key, "")
        if raw.strip() == "":  # 비어 있으면 설정하지 않은 것으로 보고 기본값을 쓴다
            continue
        if f.name == "professor_github_ids":
            kwargs[f.name] = _to_id_list(key, raw)
        elif f.name == "mail_rate_per_sec":
            kwargs[f.name] = _to_int(key, raw)
        elif f.name in ("database_path", "client_dist"):
            kwargs[f.name] = Path(raw)
        else:
            kwargs[f.name] = raw
    return Settings(**kwargs)
