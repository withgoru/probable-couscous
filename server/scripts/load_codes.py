"""동시 코드 요청 부하 측정(plan 위험 1, T036).

실제 서버 프로세스(E2E 전용 서버 `client/e2e/server.py`: uvicorn, SQLite `synchronous=FULL`, 가짜 GitHub 로그인,
메모리 메일함)를 띄우고, 학생 N명이 각자 다른 기기(쿠키)로 초대 링크를 연 뒤 **같은 순간에** '인증 코드 받기'를 누른다.

출력:
- 응답 시간 p50·p95·최대(ms)
- 유실: 성공 응답(`next: code`)을 받지 못한 요청 + 성공이라고 답했는데 DB에 남지 않은 요청(C13)
- 메일 발송 대기열이 모두 빠질 때까지 걸린 시간(초당 상한, 기본 8건)

실행: server/ 에서 `python scripts/load_codes.py --students 200 [--json]`
유실이 있으면 종료 코드 1이다.
"""

import argparse
import asyncio
import json
import os
import socket
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx

SERVER_DIR = Path(__file__).resolve().parents[1]
E2E_SERVER = SERVER_DIR.parent / "client" / "e2e" / "server.py"


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def start_server(port: int, db: Path) -> subprocess.Popen:
    proc = subprocess.Popen(
        [sys.executable, str(E2E_SERVER), str(port), str(db)],
        cwd=SERVER_DIR,
        env={**os.environ, "PYTHONPATH": str(SERVER_DIR)},
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
    )
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise RuntimeError(f"서버가 뜨지 못했습니다: {proc.stderr.read().decode()[-2000:]}")
        try:
            if httpx.get(f"http://127.0.0.1:{port}/api/health", timeout=0.5).status_code == 200:
                return proc
        except httpx.HTTPError:
            time.sleep(0.1)
    proc.kill()
    raise RuntimeError("서버가 30초 안에 뜨지 않았습니다.")


def percentile(values: list[float], p: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    k = (len(ordered) - 1) * p
    lo, hi = int(k), min(int(k) + 1, len(ordered) - 1)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (k - lo)


def setup_classroom(base: str, n: int) -> tuple[str, list[str]]:
    """교수로 로그인해 강좌를 만들고 학생 n명을 CSV로 올린다. 초대 토큰과 학생 이메일을 돌려준다."""
    prof = httpx.Client(base_url=base, headers={"Origin": base}, follow_redirects=False)
    state = parse_qs(urlparse(prof.get("/api/auth/github/login").headers["location"]).query)["state"][0]
    prof.get(f"/api/auth/github/callback?code=kim&state={state}")
    cid = prof.post("/api/classrooms", json={"name": "부하 측정"}).json()["id"]
    emails = [f"student{i:03d}@load.test" for i in range(n)]
    csv = "학번,이름,이메일\n" + "".join(f"2026{i:04d},학생{i},{e}\n" for i, e in enumerate(emails))
    r = prof.post(f"/api/classrooms/{cid}/roster/import", content=csv.encode(), headers={"Content-Type": "text/csv"})
    if r.status_code != 200 or r.json()["added"] != n:
        raise RuntimeError(f"명단을 올리지 못했습니다: {r.status_code} {r.text[:200]}")
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return token, emails


async def fire(base: str, token: str, emails: list[str], broken: int) -> list[dict]:
    """학생마다 기기를 하나씩 준비하고(링크 열기), 모두 같은 순간에 코드를 요청한다."""
    limits = httpx.Limits(max_connections=None, max_keepalive_connections=None)
    clients = [httpx.AsyncClient(base_url=base, headers={"Origin": base}, timeout=60, limits=limits) for _ in emails]
    try:
        await asyncio.gather(*(c.get(f"/api/join/{token}") for c in clients))  # 기기 쿠키(측정 전)
        start = asyncio.Event()

        async def one(client: httpx.AsyncClient, email: str, i: int) -> dict:
            await start.wait()
            body = {"email": "not-an-email" if i < broken else email}
            t0 = time.perf_counter()
            try:
                r = await client.post(f"/api/join/{token}/email", json=body)
                ms = (time.perf_counter() - t0) * 1000
                ok = r.status_code == 200 and r.json().get("next") == "code"
                return {"ms": ms, "ok": ok, "failure": None if ok else f"HTTP {r.status_code}"}
            except httpx.HTTPError as err:
                return {"ms": (time.perf_counter() - t0) * 1000, "ok": False, "failure": type(err).__name__}

        tasks = [asyncio.create_task(one(c, e, i)) for i, (c, e) in enumerate(zip(clients, emails, strict=True))]
        await asyncio.sleep(0.2)  # 모두 기다리는 상태가 된 뒤에
        start.set()
        return await asyncio.gather(*tasks)
    finally:
        await asyncio.gather(*(c.aclose() for c in clients))


def wait_for_mails(base: str, emails: list[str], started: float, timeout: float) -> tuple[int, float]:
    """모든 학생에게 코드 메일이 나갈 때까지 기다린다. 나간 수와 처음 요청부터 걸린 시간(초)."""
    pending = set(emails)
    with httpx.Client(base_url=base) as c:
        while pending and time.perf_counter() - started < timeout:
            for e in list(pending):
                if c.get("/api/test/last-code", params={"to": e}).status_code == 200:
                    pending.discard(e)
            if pending:
                time.sleep(0.2)
    return len(emails) - len(pending), time.perf_counter() - started


def main() -> int:
    parser = argparse.ArgumentParser(description="동시 코드 요청 부하 측정")
    parser.add_argument("--students", type=int, default=200)
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    parser.add_argument("--self-check-fail", action="store_true", help=argparse.SUPPRESS)  # 유실을 일부러 만든다(스크립트 점검용)
    args = parser.parse_args()
    n = args.students

    workdir = Path(tempfile.mkdtemp(prefix="load-"))
    db = workdir / "app.db"
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port, db)
    try:
        token, emails = setup_classroom(base, n)
        started = time.perf_counter()
        results = asyncio.run(fire(base, token, emails, broken=1 if args.self_check_fail else 0))
        answered_ok = sum(r["ok"] for r in results)
        mails_sent, drain = wait_for_mails(base, [e for e, r in zip(emails, results, strict=True) if r["ok"]], started, timeout=max(60, n / 4))
        conn = sqlite3.connect(db)
        saved = conn.execute("SELECT COUNT(*) FROM login_challenges").fetchone()[0]
        queued = conn.execute("SELECT COUNT(*) FROM mail_outbox").fetchone()[0]
        conn.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    failures: dict[str, int] = {}
    for r in results:
        if r["failure"]:
            failures[r["failure"]] = failures.get(r["failure"], 0) + 1
    latencies = [r["ms"] for r in results if r["ok"]]
    lost = (n - answered_ok) + max(0, answered_ok - saved)
    report = {
        "students": n,
        "latency_ms": {
            "p50": round(percentile(latencies, 0.5), 1),
            "p95": round(percentile(latencies, 0.95), 1),
            "max": round(max(latencies, default=0), 1),
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0,
        },
        "lost": lost,
        "failures": failures,
        "challenges_saved": saved,
        "mails_queued": queued,
        "mails_sent": mails_sent,
        "mail_drain_seconds": round(drain, 1),
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        lat = report["latency_ms"]
        print(f"학생 {n}명이 같은 순간에 '인증 코드 받기'")
        print(f"응답 시간: p50 {lat['p50']}ms, p95 {lat['p95']}ms, 최대 {lat['max']}ms")
        print(f"유실 {lost}건 (실패 응답 {sum(failures.values())}건 {failures or ''}, 저장된 챌린지 {saved}건)")
        print(f"메일 발송: {mails_sent}/{answered_ok}통, 모두 나가기까지 {report['mail_drain_seconds']}초 (초당 상한)")
    return 1 if lost else 0


if __name__ == "__main__":
    sys.exit(main())
