"""수업 동기화와 첫 로딩 측정(002 plan 위험 1·4, AC25, T030).

실제 서버 프로세스(E2E 전용 서버 `client/e2e/server.py`: uvicorn, SQLite `synchronous=FULL`, 가짜 GitHub 로그인,
메모리 메일함)를 띄우고, 테스트용 슬라이드 묶음으로 수업을 시작한다. 학생 N명이 각자 다른 기기(쿠키)로 입장해
수업 WebSocket에 붙는다.

재는 것:
- 첫 로딩: 모든 학생이 같은 순간에 슬라이드 묶음의 첫 화면에 필요한 파일(index.html과 그것이 바로 부르는 JS·CSS)을 받는 시간.
  나중에 불러오는 조각과 그림은 들어가지 않아 실제보다 작다(아래 한계). 실제 묶음은 `--deck`으로 잰다
- 동기화: 교수가 넘길 때(WebSocket `goto`를 보낸 순간)부터 각 학생 연결에 그 위치(`position`)가 닿기까지의 시간
- 유실: 넘기기마다 위치를 받지 못한 학생 수의 합 + 마지막 위치가 DB에 남지 않았으면 1(C13)
- 첫 로딩 실패: 묶음을 받지 못한 학생 수(그 학생은 슬라이드를 볼 수 없다)

이 스크립트는 프로토콜 수준이다. 브라우저가 iframe에 그리는 시간은 들어가지 않는다. 실제 휴대폰·여러 컴퓨터로 재는 방법은
002 notes.md를 본다.

실행: server/ 에서 `python scripts/load_class.py --students 200 [--moves 10] [--json]`
유실이나 첫 로딩 실패가 있으면 종료 코드 1이다.
"""

import argparse
import asyncio
import json
import re
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import httpx
from websockets.asyncio.client import connect

sys.path.insert(0, str(Path(__file__).resolve().parent))
from load_codes import free_port, percentile, start_server  # 같은 폴더의 001 측정 스크립트

SERVER_DIR = Path(__file__).resolve().parents[1]
DECK = SERVER_DIR / "tests" / "fixtures" / "deck-small.zip"
# 테스트용 묶음(4장, 단계 0·3·0·1)에서 교수가 차례로 넘기는 위치. 끝에 닿으면 처음부터 다시 돈다
POSITIONS = [(2, 0), (2, 1), (2, 2), (2, 3), (3, 0), (4, 0), (4, 1), (1, 0)]
GAP_SECONDS = 0.3  # 넘기기 사이(교수가 빠르게 넘기는 정도)
BROWSER_CONNECTIONS = 6  # 휴대폰 브라우저가 한 서버에 동시에 여는 연결 수(HTTP/1.1)


def professor(base: str) -> httpx.Client:
    prof = httpx.Client(base_url=base, headers={"Origin": base}, follow_redirects=False, timeout=60)
    state = parse_qs(urlparse(prof.get("/api/auth/github/login").headers["location"]).query)["state"][0]
    prof.get(f"/api/auth/github/callback?code=kim&state={state}")
    return prof


def setup_class(prof: httpx.Client, n: int, deck: Path, preload: bool = False) -> dict:
    """강좌·명단·회차·묶음을 만들고 수업을 시작한다. 미리 받기면 묶음을 공개하고 시작은 학생이 미리 받은 뒤로 미룬다."""
    cid = prof.post("/api/classrooms", json={"name": "동기화 측정"}).json()["id"]
    emails = [f"sync{i:03d}@load.test" for i in range(n)]
    csv = "학번,이름,이메일\n" + "".join(f"2026{i:04d},학생{i},{e}\n" for i, e in enumerate(emails))
    r = prof.post(f"/api/classrooms/{cid}/roster/import", content=csv.encode(), headers={"Content-Type": "text/csv"})
    if r.status_code != 200 or r.json()["added"] != n:
        raise RuntimeError(f"명단을 올리지 못했습니다: {r.status_code} {r.text[:200]}")
    sid = prof.post(f"/api/classrooms/{cid}/sessions", json={"title": "측정"}).json()["id"]
    r = prof.put(
        f"/api/classrooms/{cid}/sessions/{sid}/deck", params={"filename": "deck.zip"},
        content=deck.read_bytes(), headers={"Content-Type": "application/zip"},
    )
    if r.status_code != 200:
        raise RuntimeError(f"묶음을 올리지 못했습니다: {r.status_code} {r.text[:200]}")
    deck_id = r.json()["deck"]["id"]
    if preload:
        prof.put(f"/api/classrooms/{cid}/sessions/{sid}/deck/visibility", json={"public": True}).raise_for_status()
    elif prof.post(f"/api/classrooms/{cid}/sessions/{sid}/start").status_code != 200:
        raise RuntimeError("수업을 시작하지 못했습니다.")
    token = prof.get(f"/api/classrooms/{cid}/invite").json()["token"]
    return {"cid": cid, "sid": sid, "deck_id": deck_id, "token": token, "emails": emails}


async def enter(base: str, token: str, email: str) -> httpx.AsyncClient:
    """학생 한 명이 자기 기기로 입장한다(이메일 → 코드 → 입장). 쿠키가 든 클라이언트를 돌려준다."""
    # 브라우저처럼 한 서버에 연결을 6개까지만 연다(HTTP/1.1). 학생마다 연결을 더 열면 측정 컴퓨터가 몰림을 만든다
    limits = httpx.Limits(max_connections=BROWSER_CONNECTIONS, max_keepalive_connections=BROWSER_CONNECTIONS)
    c = httpx.AsyncClient(base_url=base, headers={"Origin": base}, timeout=120, limits=limits)
    await c.get(f"/api/join/{token}")
    r = await c.post(f"/api/join/{token}/email", json={"email": email})
    if r.json().get("next") != "code":
        raise RuntimeError(f"코드를 받지 못했습니다: {email} {r.text[:200]}")
    deadline = time.monotonic() + 120
    code = None
    while code is None and time.monotonic() < deadline:  # 메일은 초당 상한이 있어 차례로 나간다
        got = await c.get("/api/test/last-code", params={"to": email})
        code = got.json()["code"] if got.status_code == 200 else None
        if code is None:
            await asyncio.sleep(0.2)
    if code is None:
        raise RuntimeError(f"코드 메일이 오지 않았습니다: {email}")
    r = await c.post(f"/api/join/{token}/code", json={"email": email, "code": code})
    if r.status_code != 200:
        raise RuntimeError(f"코드를 확인하지 못했습니다: {email} {r.text[:200]}")
    if (await c.post(f"/api/join/{token}/enter")).status_code != 200:
        raise RuntimeError(f"입장하지 못했습니다: {email}")
    return c


def deck_files(index_html: str, deck_id: int) -> list[str]:
    """첫 화면에 필요한 파일: index.html이 부르는 같은 묶음의 JS·CSS(나머지 슬라이드 조각은 넘길 때 받는다)."""
    found = re.findall(rf'(?:src|href)="(/decks/{deck_id}/[^"]+\.(?:js|css))"', index_html)
    return sorted(set(found))


async def first_load(client: httpx.AsyncClient, deck_id: int, start: asyncio.Event, cached: bool = False) -> dict:
    """{ms, bytes, files, failure}. 모두 같은 순간에 시작한다(수업 시작에 학생들이 한꺼번에 받는다).
    받지 못하면(연결 끊김, 오류 응답) 멈추지 않고 실패로 센다. 그 학생은 슬라이드를 볼 수 없다."""
    await start.wait()
    t0 = time.perf_counter()
    try:
        index = await client.get(f"/decks/{deck_id}/index.html")
        index.raise_for_status()
        # 미리 받았으면 해시 파일은 브라우저 캐시에 있다(서버가 공개 묶음에 오래 캐시하라고 한다): 첫 화면만 받는다
        files = [] if cached else deck_files(index.text, deck_id)
        responses = await asyncio.gather(*(client.get(f) for f in files))
        for r in responses:
            r.raise_for_status()
    except httpx.HTTPError as err:
        return {"ms": (time.perf_counter() - t0) * 1000, "bytes": 0, "files": 0, "failure": type(err).__name__}
    size = len(index.content) + sum(len(r.content) for r in responses)
    return {"ms": (time.perf_counter() - t0) * 1000, "bytes": size, "files": 1 + len(files), "failure": None}


def ws_url(base: str, cid: int) -> str:
    return base.replace("http://", "ws://") + f"/ws/class/{cid}"


def cookie_header(client: httpx.Client | httpx.AsyncClient) -> str:
    return "; ".join(f"{k}={v}" for k, v in client.cookies.items())


async def until(ws, type_: str, timeout: float = 30) -> dict:
    while True:
        message = json.loads(await asyncio.wait_for(ws.recv(), timeout))
        if message["type"] == type_:
            return message
        if message["type"] == "error":  # 넘기기를 거절했다: 기다리지 않고 이유를 알린다
            raise RuntimeError(f"서버가 거절했습니다: {message.get('reason')} {message.get('message')}")


async def measure_sync(base: str, setup: dict, students: list[httpx.AsyncClient], prof: httpx.Client, moves: int,
                       drop_one: bool) -> tuple[list[float], int, int]:
    """(지연 ms 목록, 받은 수, 유실 수). 학생마다 연결을 열고, 교수 연결로 moves번 넘긴다."""
    url = ws_url(base, setup["cid"])
    sockets = []
    for s in students:  # 한꺼번에 열면 측정 컴퓨터가 막힐 수 있어 차례로 연다(측정 전 단계)
        ws = await connect(url, additional_headers={"Origin": base, "Cookie": cookie_header(s)}, open_timeout=30)
        await until(ws, "ready")
        sockets.append(ws)
    teacher = await connect(url, additional_headers={"Origin": base, "Cookie": cookie_header(prof)}, open_timeout=30)
    await until(teacher, "ready")
    if drop_one:
        await sockets[0].close()  # 스크립트 점검용: 한 학생이 받지 못한다

    sent: dict[int, float] = {}
    received: list[dict[int, float]] = [{} for _ in sockets]

    async def listen(i: int, ws) -> None:
        try:
            async for raw in ws:
                message = json.loads(raw)
                if message["type"] == "position":
                    received[i][message["version"]] = time.perf_counter()
        except Exception:  # noqa: BLE001  닫힌 연결은 받지 못한 것으로 센다
            return

    listeners = [asyncio.create_task(listen(i, ws)) for i, ws in enumerate(sockets)]
    versions = []
    try:
        for k in range(moves):
            slide, click = POSITIONS[k % len(POSITIONS)]
            t0 = time.perf_counter()
            await teacher.send(json.dumps({"type": "goto", "session_id": setup["sid"], "slide": slide, "click": click, "req": f"m{k}"}))
            ack = await until(teacher, "ack")
            sent[ack["version"]] = t0
            versions.append(ack["version"])
            await asyncio.sleep(GAP_SECONDS)
        await asyncio.sleep(1.0)  # 마지막 넘기기가 닿을 시간(그 뒤에 닿은 것은 유실로 센다)
    finally:
        for task in listeners:
            task.cancel()
        await asyncio.gather(*listeners, return_exceptions=True)
        for ws in [*sockets, teacher]:
            await ws.close()

    latencies, got, lost = [], 0, 0
    for per in received:
        for v in versions:
            if v in per:
                latencies.append((per[v] - sent[v]) * 1000)
                got += 1
            else:
                lost += 1
    return latencies, got, lost


async def preload_all(base: str, students: list[httpx.AsyncClient], deck_id: int) -> None:
    """기다리는 동안 학생들이 공개 묶음을 미리 받는다(T038). 입장 시각이 서로 달라 몰리지 않으므로 동시 수를 줄인다."""
    gate = asyncio.Semaphore(20)

    async def one(client: httpx.AsyncClient) -> None:
        async with gate:
            index = await client.get(f"/decks/{deck_id}/index.html")
            index.raise_for_status()
            for f in deck_files(index.text, deck_id):
                (await client.get(f)).raise_for_status()

    await asyncio.gather(*(one(s) for s in students))


async def run(base: str, setup: dict, prof: httpx.Client, moves: int, drop_one: bool, preload: bool = False) -> dict:
    limits = asyncio.Semaphore(50)  # 입장은 측정 전 단계라 동시 수를 조금 줄인다

    async def guarded(email: str) -> httpx.AsyncClient:
        async with limits:
            return await enter(base, setup["token"], email)

    students = await asyncio.gather(*(guarded(e) for e in setup["emails"]))
    try:
        if preload:
            await preload_all(base, students, setup["deck_id"])
            if prof.post(f"/api/classrooms/{setup['cid']}/sessions/{setup['sid']}/start").status_code != 200:
                raise RuntimeError("수업을 시작하지 못했습니다.")
        # 첫 로딩은 새 연결로 잰다(입장 때 열어 둔 연결을 다시 쓰다 서버가 닫은 연결에 걸리지 않게). 쿠키만 옮긴다
        limits = httpx.Limits(max_connections=BROWSER_CONNECTIONS, max_keepalive_connections=BROWSER_CONNECTIONS)
        fresh = [
            httpx.AsyncClient(base_url=base, headers={"Origin": base}, timeout=120, limits=limits, cookies=s.cookies)
            for s in students
        ]
        try:
            start = asyncio.Event()
            loads = [asyncio.create_task(first_load(f, setup["deck_id"], start, cached=preload)) for f in fresh]
            await asyncio.sleep(0.2)
            start.set()
            load_results = await asyncio.gather(*loads)
        finally:
            await asyncio.gather(*(f.aclose() for f in fresh))
        latencies, got, lost = await measure_sync(base, setup, students, prof, moves, drop_one)
    finally:
        await asyncio.gather(*(s.aclose() for s in students))
    return {"loads": load_results, "latencies": latencies, "got": got, "lost": lost}


def main() -> int:
    parser = argparse.ArgumentParser(description="수업 동기화와 첫 로딩 측정")
    parser.add_argument("--students", type=int, default=200)
    parser.add_argument("--moves", type=int, default=10, help="교수가 넘기는 횟수")
    parser.add_argument("--deck", type=Path, default=DECK, help="올릴 슬라이드 묶음 zip(기본: 테스트용 4장 묶음)")
    parser.add_argument("--preload", action="store_true", help="기다리는 동안 공개 묶음을 미리 받은 뒤 수업을 시작한다(T038)")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    parser.add_argument("--self-check-fail", action="store_true", help=argparse.SUPPRESS)  # 유실을 일부러 만든다(스크립트 점검용)
    args = parser.parse_args()
    n, moves = args.students, args.moves

    workdir = Path(tempfile.mkdtemp(prefix="load-class-"))
    db = workdir / "app.db"
    port = free_port()
    base = f"http://127.0.0.1:{port}"
    proc = start_server(port, db)
    try:
        prof = professor(base)
        setup = setup_class(prof, n, args.deck, args.preload)
        result = asyncio.run(run(base, setup, prof, moves, args.self_check_fail, args.preload))
        conn = sqlite3.connect(db)
        row = conn.execute(
            "SELECT current_slide, current_click FROM class_sessions WHERE id = ?", (setup["sid"],)
        ).fetchone()
        conn.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)

    last = POSITIONS[(moves - 1) % len(POSITIONS)] if moves else (1, 0)
    saved = tuple(row) == last
    lost = result["lost"] + (0 if saved else 1)
    latencies = result["latencies"]
    loaded = [r for r in result["loads"] if r["failure"] is None]
    load_failures: dict[str, int] = {}
    for r in result["loads"]:
        if r["failure"]:
            load_failures[r["failure"]] = load_failures.get(r["failure"], 0) + 1
    load_ms = [r["ms"] for r in loaded]
    deck_bytes = loaded[0]["bytes"] if loaded else 0
    deck_count = loaded[0]["files"] if loaded else 0
    report = {
        "students": n,
        "moves": moves,
        "preload": args.preload,
        "sync_ms": {
            "p50": round(percentile(latencies, 0.5), 1),
            "p95": round(percentile(latencies, 0.95), 1),
            "max": round(max(latencies, default=0), 1),
            "mean": round(statistics.fmean(latencies), 1) if latencies else 0,
        },
        "deliveries": result["got"],
        "lost": lost,
        "final_position_saved": saved,
        "first_load_ms": {
            "p50": round(percentile(load_ms, 0.5), 1),
            "p95": round(percentile(load_ms, 0.95), 1),
            "max": round(max(load_ms, default=0), 1),
        },
        "first_load_failures": load_failures,
        "deck_bytes": deck_bytes,
        "deck_files": deck_count,
    }
    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        s, f = report["sync_ms"], report["first_load_ms"]
        print(f"학생 {n}명, 교수가 {moves}번 넘김{' (기다리는 동안 공개 묶음을 미리 받음)' if args.preload else ''}")
        print(f"동기화(넘기기 → 학생 연결에 도착): p50 {s['p50']}ms, p95 {s['p95']}ms, 최대 {s['max']}ms")
        print(f"유실 {lost}건 (받음 {result['got']}/{n * moves}, 마지막 위치 DB 저장 {'예' if saved else '아니오'})")
        print(
            f"첫 로딩(묶음 첫 화면 {deck_count}개 파일, {deck_bytes / 1024:.0f}KB를 모두 같은 순간에): "
            f"p50 {f['p50']}ms, p95 {f['p95']}ms, 최대 {f['max']}ms"
        )
        print(f"첫 로딩 실패 {sum(load_failures.values())}건 {load_failures or ''}")
    return 1 if lost or load_failures else 0


if __name__ == "__main__":
    sys.exit(main())
