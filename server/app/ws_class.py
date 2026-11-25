"""수업 WebSocket `/ws/class/{classroom_id}`(002 AC13, AC15, AC17, AC20, AC25).

연결:
 1. 권한 판단(`guard_class`: 그 강좌의 교수이거나 입장한 학생, `class.view`)과 `Origin` 검사를 연결 전에 한다.
 2. 교수 연결은 `?role=projector`를 붙이면 프로젝터다(넘길 수 없고 현황을 받지 않는다). 학생은 무엇을 붙여도 학생이다.
 3. 구독을 먼저 걸고 `{"type": "ready", "role": …}`를 보낸다. 화면은 그 뒤 `GET …/live`로 상태를 통째로 받는다.

받는 것:
 - 교수 `goto{session_id, slide, click, req}`: 범위 검사 → DB 기록 → 보낸 화면에 `ack{req, version}` → 방에 `position`
   발행(C13). 같은 위치면 `ack`만 한다. 가장 멀리 간 위치는 줄지 않는다.
 - 학생 `mode{follow|browse}`: 연결마다 메모리에 두고, 바뀌면 교수 화면에만 `presence{follow, browse}`(숫자만, C7).
 - 그 밖은 `error{req, reason, message}`로 답하고 연결은 그대로 둔다.

내보내기(AC44, T011): 001의 빼기·로그인 끊기가 저장 뒤 방에 `member_revoked{membership_id, reason}`을 발행하면
그 학생의 연결만 `goodbye{reason, message}`를 받고 닫힌다(코드 4403). 다른 화면에는 이 발행을 보내지 않는다.

현황은 진실이 아니라 지금 붙어 있는 화면의 모습이라 DB에 쓰지 않는다(plan '동기화 현황').
"""

import asyncio
import contextlib
import json
import sqlite3
from dataclasses import dataclass, field
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, WebSocket
from starlette.concurrency import run_in_threadpool
from starlette.websockets import WebSocketDisconnect

from app.authz import Action, Granted
from app.class_access import guard_class
from app.classrooms import load_classroom
from app.db import get_db, transaction
from app.realtime import class_room

router = APIRouter()
ViewGuard = Annotated[Granted, Depends(guard_class(Action.CLASS_VIEW, load_classroom))]

MAX_CLICK = 999  # 서버는 슬라이드마다 단계 수를 모른다. 정수가 아닌 값과 터무니없는 값만 막는다
PROFESSOR_ONLY = "professor"  # 발행에 붙이면 교수 화면(프로젝터 제외)만 받는다
GOODBYE_CODE = 4403  # 명단에서 빠졌거나 로그인이 끊겨 닫는다. 화면은 이 코드면 다시 붙지 않고 입장 화면으로 간다
GOODBYES = {
    "removed": "수강생 명단에서 빠져 이 수업을 볼 수 없습니다. 교수님께 문의해 주세요.",
    "signed_out": "이 강좌에서 로그아웃되었습니다. 강좌 링크를 다시 열어 이메일 인증부터 해 주세요.",
}

ERRORS = {
    "bad_message": "알 수 없는 요청입니다. 화면을 새로 고쳐 주세요.",
    "not_allowed": "교수 수업 화면에서만 넘길 수 있습니다.",
    "not_live": "진행 중인 수업이 아닙니다. 화면을 새로 고쳐 주세요.",
    "out_of_range": "그 위치로 넘길 수 없습니다. 슬라이드 범위를 확인해 주세요.",
}

Role = Literal["professor", "projector", "student"]


# --- 동기화 현황 ------------------------------------------------------------------------------


@dataclass
class Presence:
    """강좌마다 학생 연결의 따라가기 상태. 이벤트 루프 안에서만 쓴다.

    학생 한 명(멤버십)은 한 번만 센다. 화면이 여러 개면 하나라도 따라가면 따라가는 중이다.
    """

    _modes: dict[int, dict[int, dict[int, str]]] = field(default_factory=dict)  # 강좌 → 멤버십 → 연결 → 상태

    def set(self, classroom_id: int, membership_id: int, conn: int, mode: str) -> None:
        self._modes.setdefault(classroom_id, {}).setdefault(membership_id, {})[conn] = mode

    def leave(self, classroom_id: int, membership_id: int, conn: int) -> None:
        members = self._modes.get(classroom_id, {})
        conns = members.get(membership_id, {})
        conns.pop(conn, None)
        if not conns:
            members.pop(membership_id, None)
        if not members:
            self._modes.pop(classroom_id, None)

    def counts(self, classroom_id: int) -> dict:
        follow = browse = 0
        for conns in self._modes.get(classroom_id, {}).values():
            if "follow" in conns.values():
                follow += 1
            else:
                browse += 1
        return {"type": "presence", "follow": follow, "browse": browse}


# --- 넘기기 ----------------------------------------------------------------------------------


class Refused(Exception):
    def __init__(self, reason: str) -> None:
        self.reason = reason


def _whole(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _goto(db: sqlite3.Connection, classroom_id: int, message: dict) -> tuple[int, dict | None]:
    """위치를 기록한다. (version, 발행할 position 또는 같은 위치면 None). 안 되면 `Refused`."""
    session_id, slide, click = message.get("session_id"), message.get("slide"), message.get("click")
    if not _whole(session_id):
        raise Refused("bad_message")
    with transaction(db):
        row = db.execute(
            "SELECT s.status, s.current_slide, s.current_click, s.furthest_slide, s.furthest_click, s.version, "
            "       d.slide_count "
            "  FROM class_sessions s "
            "  LEFT JOIN decks d ON d.session_id = s.id AND d.classroom_id = s.classroom_id AND d.removed_at IS NULL "
            " WHERE s.id = ? AND s.classroom_id = ?",
            (session_id, classroom_id),
        ).fetchone()
        if row is None or row["status"] != "live":
            raise Refused("not_live")
        last_slide = row["slide_count"] or 1  # 묶음이 없으면 첫 슬라이드뿐이다
        if not (_whole(slide) and _whole(click) and 1 <= slide <= last_slide and 0 <= click <= MAX_CLICK):
            raise Refused("out_of_range")
        current = (slide, click)
        if current == (row["current_slide"], row["current_click"]):
            return row["version"], None
        furthest = max(current, (row["furthest_slide"], row["furthest_click"]))  # 되돌아가도 줄지 않는다
        version = row["version"] + 1
        db.execute(
            "UPDATE class_sessions SET current_slide = ?, current_click = ?, furthest_slide = ?, furthest_click = ?, "
            "version = ? WHERE id = ? AND classroom_id = ?",
            (*current, *furthest, version, session_id, classroom_id),
        )
    position = {
        "type": "position",
        "session_id": session_id,
        "current": {"slide": current[0], "click": current[1]},
        "furthest": {"slide": furthest[0], "click": furthest[1]},
        "version": version,
    }
    return version, position


# --- 연결 ------------------------------------------------------------------------------------


class Screen:
    """연결 하나. 보내기는 한 번에 하나씩 한다(구독 전달과 응답이 같은 연결에 겹쳐 쓰지 않게)."""

    def __init__(self, websocket: WebSocket, role: Role, membership_id: int | None) -> None:
        self.websocket = websocket
        self.role = role
        self.membership_id = membership_id
        self._lock = asyncio.Lock()

    async def send(self, message: dict) -> None:
        async with self._lock:
            await self.websocket.send_json(message)


async def _pump(screen: Screen, sub) -> str:
    """구독한 발행을 화면에 보낸다. 이 학생을 내보내라는 발행이면 `goodbye`를 보내고 끝낸다."""
    while True:
        event = await sub.get()
        if event["type"] == "member_revoked":
            # 누가 빠졌는지는 그 학생의 연결에만 의미가 있다. 다른 화면에는 보내지 않는다(C9)
            if screen.role == "student" and event["membership_id"] == screen.membership_id:
                reason = event["reason"]
                await screen.send({"type": "goodbye", "reason": reason, "message": GOODBYES[reason]})
                return "goodbye"
            continue
        to = event.pop("to", None)
        if to == PROFESSOR_ONLY and screen.role != "professor":
            continue
        await screen.send(event)


def _role(websocket: WebSocket, granted: Granted) -> Role:
    if granted.actor.kind != "professor":
        return "student"
    return "projector" if websocket.query_params.get("role") == "projector" else "professor"


async def _receive(screen: Screen, granted: Granted, db: sqlite3.Connection, on_mode) -> None:
    websocket = screen.websocket
    classroom_id = granted.resource.id
    while True:
        frame = await websocket.receive()
        if frame["type"] == "websocket.disconnect":
            return
        try:
            message = json.loads(frame.get("text") or "")
        except ValueError:
            message = None
        if not isinstance(message, dict):
            await screen.send({"type": "error", "req": None, "reason": "bad_message", "message": ERRORS["bad_message"]})
            continue
        req = message.get("req")
        req = req if isinstance(req, str | int) and not isinstance(req, bool) and len(str(req)) <= 64 else None
        try:
            kind = message.get("type")
            if kind == "goto":
                if screen.role != "professor":
                    raise Refused("not_allowed")
                version, position = await run_in_threadpool(_goto, db, classroom_id, message)
                await screen.send({"type": "ack", "req": req, "version": version})  # DB 기록 뒤
                if position is not None:
                    websocket.app.state.bus.publish(class_room(classroom_id), position)
            elif kind == "mode" and screen.role == "student" and message.get("mode") in ("follow", "browse"):
                on_mode(message["mode"])
            else:
                raise Refused("bad_message")
        except Refused as refused:
            await screen.send({"type": "error", "req": req, "reason": refused.reason, "message": ERRORS[refused.reason]})


@router.websocket("/ws/class/{classroom_id}")
async def class_screen(
    websocket: WebSocket, granted: ViewGuard, db: Annotated[sqlite3.Connection, Depends(get_db)]
):
    # 브라우저는 WebSocket에도 쿠키를 같이 보낸다. 다른 사이트의 페이지가 그 쿠키로 연결하지 못하게 한다
    if websocket.headers.get("origin") != websocket.app.state.allowed_origin:
        await websocket.close(code=1008)
        return
    classroom_id = granted.resource.id
    bus = websocket.app.state.bus
    room = class_room(classroom_id)
    screen = Screen(websocket, _role(websocket, granted), granted.actor.membership_id)
    presence: Presence = websocket.app.state.presence
    conn = id(screen)
    membership_id = granted.actor.membership_id

    def announce() -> None:
        bus.publish(room, {**presence.counts(classroom_id), "to": PROFESSOR_ONLY})

    def on_mode(mode: str) -> None:
        presence.set(classroom_id, membership_id, conn, mode)
        announce()

    sub = bus.subscribe(room)
    try:
        await websocket.accept()
        await screen.send({"type": "ready", "role": screen.role})
        if screen.role == "professor":
            await screen.send(presence.counts(classroom_id))
        elif screen.role == "student":
            on_mode("follow")  # 처음에는 교수 화면을 따라가는 중이다(AC25)
        tasks = {
            asyncio.create_task(_pump(screen, sub)),
            asyncio.create_task(_receive(screen, granted, db, on_mode)),
        }
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        said_goodbye = False
        for task in done:
            # 화면이 끊어서 보내지 못한 것은 정상이다. 그 밖의 오류는 그대로 올린다
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                said_goodbye = task.result() == "goodbye"
        if said_goodbye:
            await websocket.close(code=GOODBYE_CODE)
    finally:
        sub.close()
        if screen.role == "student":
            presence.leave(classroom_id, membership_id, conn)
            announce()
