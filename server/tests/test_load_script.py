"""T036: 동시 코드 요청 부하 측정 스크립트(`scripts/load_codes.py`)가 p95와 유실 건수를 출력한다(plan 위험 1).

200명 측정 결과는 notes.md에 기록한다. 여기서는 작은 규모(10명)로 스크립트가 끝까지 돌고 숫자를 내는지만 본다.
"""

import json
import subprocess
import sys
from pathlib import Path

SERVER_DIR = Path(__file__).resolve().parents[1]
SCRIPT = SERVER_DIR / "scripts" / "load_codes.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT), *args], check=False, cwd=SERVER_DIR, capture_output=True, text=True, timeout=120
    )


def test_it_prints_p95_and_the_lost_count():
    result = run("--students", "10")
    assert result.returncode == 0, result.stderr[-2000:]
    out = result.stdout
    assert "학생 10명" in out
    assert "p95" in out and "ms" in out
    assert "유실 0건" in out


def test_json_output_has_the_numbers_and_every_request_got_a_code():
    result = run("--students", "10", "--json")
    assert result.returncode == 0, result.stderr[-2000:]
    report = json.loads(result.stdout)
    assert report["students"] == 10
    assert report["lost"] == 0 and report["failures"] == {}
    assert report["latency_ms"]["p95"] >= report["latency_ms"]["p50"] > 0
    assert report["challenges_saved"] == 10 and report["mails_queued"] == 10  # 답한 요청은 DB에 남았다(C13)
    assert report["mails_sent"] == 10 and report["mail_drain_seconds"] > 0


def test_a_lost_request_makes_the_script_fail():
    # 받은 응답보다 적게 저장됐거나 실패 응답이 있으면 종료 코드가 0이 아니다(측정이 조용히 통과하지 않게)
    result = run("--students", "3", "--json", "--self-check-fail")
    assert result.returncode != 0
    assert json.loads(result.stdout)["lost"] > 0
