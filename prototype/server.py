"""실험용 허브. 교수 상태/공지를 시퀀스 번호와 함께 중계(DB 먼저 기록)하고, 재접속 시 놓친 것을 재전송.
학생 출석코드·퀴즈 제출은 SQLite에 먼저 기록한 뒤 ack. 슬라이드 정적 파일도 서빙."""
import json, sqlite3, os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles

DB = os.environ.get("PROTO_DB", "proto.db")
db = sqlite3.connect(DB, isolation_level=None, check_same_thread=False)
db.execute("PRAGMA journal_mode=WAL"); db.execute("PRAGMA synchronous=NORMAL")
db.executescript("""
CREATE TABLE IF NOT EXISTS msgs(seq INTEGER PRIMARY KEY AUTOINCREMENT, body TEXT);
CREATE TABLE IF NOT EXISTS attend(sid TEXT PRIMARY KEY, at REAL);
CREATE TABLE IF NOT EXISTS quiz(sid TEXT, q INTEGER, a TEXT, PRIMARY KEY(sid,q));
""")
CODE = "4827"
app = FastAPI()
clients: set[WebSocket] = set()
latest_state: dict | None = None

def store(msg: dict) -> dict:
    cur = db.execute("INSERT INTO msgs(body) VALUES(?)", (json.dumps(msg),))
    return {**msg, "seq": cur.lastrowid}

@app.websocket("/ws")
async def ws(sock: WebSocket, role: str = "student", since: int | None = None):
    global latest_state
    await sock.accept()
    clients.add(sock)
    if since is not None:  # 재접속: 놓친 메시지 재전송
        for _, body in db.execute("SELECT seq, body FROM msgs WHERE seq>? ORDER BY seq", (since,)).fetchall():
            await sock.send_text(json.dumps({**json.loads(body), "seq": _}))
    elif latest_state:
        await sock.send_text(json.dumps(latest_state))
    try:
        while True:
            m = json.loads(await sock.receive_text())
            t = m.get("t")
            if role == "prof":
                m = store(m)
                if t is None: latest_state = m
                data = json.dumps(m)
                for c in list(clients):
                    if c is not sock:
                        try: await c.send_text(data)
                        except Exception: clients.discard(c)
            elif t == "attend":
                ok = m.get("code") == CODE
                if ok: db.execute("INSERT OR IGNORE INTO attend VALUES(?,?)", (m["id"], __import__("time").time()))
                await sock.send_text(json.dumps({"t": "ack", "ref": m.get("ref"), "ok": ok}))
            elif t == "quiz":
                db.execute("INSERT OR REPLACE INTO quiz VALUES(?,?,?)", (m["id"], m["q"], m["a"]))
                await sock.send_text(json.dumps({"t": "ack", "ref": m.get("ref"), "ok": True}))
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(sock)

@app.get("/stats")
def stats():
    return {"attend": db.execute("SELECT COUNT(*) FROM attend").fetchone()[0],
            "quiz": db.execute("SELECT COUNT(*) FROM quiz").fetchone()[0],
            "msgs": db.execute("SELECT COUNT(*) FROM msgs").fetchone()[0]}

app.mount("/slides", StaticFiles(directory="slides/dist", html=True), name="slides")
