"""002 T030: 수업 동기화와 첫 로딩 측정 스크립트(`scripts/load_class.py`, plan 위험 1·4, AC25).

학생 N명이 실제 서버 프로세스에 입장해 수업 WebSocket에 붙고, 교수가 넘길 때마다 위치가 학생에게 닿는 시간과
수업 시작에 묶음을 받는 시간을 잰다. 200명 결과와 여러 컴퓨터로 재는 방법은 notes.md에 쓴다.
여기서는 작은 규모(10명)로 스크립트가 끝까지 돌고 숫자를 내는지, 유실이 있으면 실패하는지만 본다(001 `test_load_script.py` 방식).
"""

import json
import subprocess
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SERVER_DIR / "scripts" / "load_class.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], check=False, cwd=SERVER_DIR, capture_output=True, text=True, timeout=240
    )


def test_it_prints_sync_latency_lost_count_and_first_load():
    result = run("--students", "10", "--moves", "3")
    assert result.returncode == 0, result.stderr[-2000:]
    out = result.stdout
    assert "학생 10명" in out
    assert "p50" in out and "p95" in out and "최대" in out and "ms" in out
    assert "유실 0건" in out
    assert "첫 로딩" in out
    assert "첫 로딩 실패 0건" in out


def test_json_output_has_the_numbers():
    result = run("--students", "10", "--moves", "3", "--json")
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)
    assert report["students"] == 10 and report["moves"] == 3
    sync = report["sync_ms"]
    assert sync["max"] >= sync["p95"] >= sync["p50"] > 0
    assert report["deliveries"] == 30  # 학생 10명 × 넘기기 3번, 모두 받았다
    assert report["lost"] == 0
    assert report["final_position_saved"] is True  # 마지막 위치가 DB에 남았다(C13)
    load = report["first_load_ms"]
    assert load["max"] >= load["p95"] >= load["p50"] > 0
    assert report["deck_bytes"] > 0 and report["deck_files"] > 0
    assert report["first_load_failures"] == {}  # 모든 학생이 묶음을 받았다


def test_a_lost_delivery_makes_the_script_fail():
    # 넘기기를 받지 못한 학생이 있으면 종료 코드가 0이 아니다(측정이 조용히 통과하지 않게)
    result = run("--students", "3", "--moves", "2", "--json", "--self-check-fail")
    assert result.returncode != 0
    assert json.loads(result.stdout)["lost"] > 0


def test_preload_measures_only_the_first_screen_at_class_start():
    # T038: 기다리는 동안 공개 묶음을 미리 받으면, 수업 시작에는 첫 화면(index.html)만 다시 받는다
    result = run("--students", "10", "--moves", "2", "--preload", "--json")
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)
    assert report["preload"] is True
    assert report["deck_files"] == 1  # 해시 파일은 캐시에 있다
    assert report["first_load_failures"] == {} and report["lost"] == 0
