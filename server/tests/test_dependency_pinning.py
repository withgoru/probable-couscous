"""C17: 의존성은 버전을 고정하고 lockfile을 커밋한다. 서버와 클라이언트 모두 확인한다."""

import json
import re
import tomllib
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PY_PIN = re.compile(r"^([A-Za-z0-9_.\-]+)(\[[^\]]+\])?==([0-9][^\s;#]*)")
NPM_EXACT = re.compile(r"^\d+\.\d+\.\d+([-+][0-9A-Za-z.\-+]+)?$")


def unpinned_python(requirements: list[str]) -> list[str]:
    return [r for r in requirements if not PY_PIN.match(r.strip())]


def unpinned_npm(versions: dict[str, str]) -> list[str]:
    return [f"{name}@{v}" for name, v in versions.items() if not NPM_EXACT.match(v)]


def test_checker_flags_ranges():
    # 검사 함수 자체가 범위 지정(^, >=, ~)을 잡아내는지 확인한다
    assert unpinned_python(["fastapi>=0.1", "uvicorn==0.54.0"]) == ["fastapi>=0.1"]
    assert unpinned_npm({"a": "^1.0.0", "b": "1.0.0", "c": "~2.0.0"}) == ["a@^1.0.0", "c@~2.0.0"]


@pytest.mark.constitution
def test_server_dependencies_are_pinned_and_locked():
    project = tomllib.loads((REPO_ROOT / "server" / "pyproject.toml").read_text())["project"]
    direct = list(project["dependencies"])
    for extra in project.get("optional-dependencies", {}).values():
        direct += extra
    assert unpinned_python(direct) == []

    lock = (REPO_ROOT / "server" / "constraints.txt").read_text()
    locked = {
        m.group(1).lower().replace("_", "-"): m.group(3)
        for line in lock.splitlines()
        if (m := PY_PIN.match(line.strip()))
    }
    for req in direct:
        m = PY_PIN.match(req)
        name = m.group(1).lower().replace("_", "-")
        assert locked.get(name) == m.group(3), f"constraints.txt에 {req}가 같은 버전으로 없다"


@pytest.mark.constitution
def test_client_dependencies_are_pinned_and_locked():
    pkg = json.loads((REPO_ROOT / "client" / "package.json").read_text())
    versions = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert unpinned_npm(versions) == []
    assert (REPO_ROOT / "client" / "package-lock.json").is_file()


@pytest.mark.constitution
def test_slides_template_dependencies_are_pinned_and_locked():
    # 교수 컴퓨터에서만 쓰는 슬라이드 템플릿(002 T001)도 같은 규칙을 따른다
    pkg = json.loads((REPO_ROOT / "slides-template" / "package.json").read_text())
    versions = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
    assert versions
    assert unpinned_npm(versions) == []
    assert (REPO_ROOT / "slides-template" / "package-lock.json").is_file()
