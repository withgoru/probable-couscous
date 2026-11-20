"""교수 관리 화면의 WebSocket `/ws/admin/{classroom_id}`(AC40, AC45).

서버가 보내기만 한다(클라이언트가 보내는 것은 무시). 순서:
 1. 권한 판단(`guard`: 교수 로그인과 강좌 소유)과 `Origin` 검사를 연결 전에 한다. 실패하면 연결 단계의 HTTP 응답으로 끝난다.
 2. 구독을 먼저 걸고 `{"type": "ready"}`를 보낸다. 화면은 `ready`를 받은 뒤 HTTP 목록을 불러오면 그 사이 변화도 놓치지 않는다.
 3. 이후 이벤트를 번호만 담아 보낸다. 받은 화면은 목록을 HTTP로 다시 불러온다(그래야 코드 열람이 기록된다).
"""

import asyncio
import contextlib
from typing import Annotated

from fastapi import APIRouter, Depends, WebSocket
from starlette.websockets import WebSocketDisconnect

from app.authz import Action, Granted, guard
from app.classrooms import load_classroom
from app.realtime import admin_room

router = APIRouter()
ManageGuard = Annotated[Granted, Depends(guard(Action.CLASSROOM_MANAGE, load_classroom))]


async def _pump(websocket: WebSocket, sub) -> None:
    while True:
        await websocket.send_json(await sub.get())


async def _watch(websocket: WebSocket) -> None:
    """클라이언트가 끊을 때까지 기다린다(보내는 내용은 쓰지 않는다)."""
    while True:
        message = await websocket.receive()
        if message["type"] == "websocket.disconnect":
            return


@router.websocket("/ws/admin/{classroom_id}")
async def admin_screen(websocket: WebSocket, granted: ManageGuard):
    # 브라우저는 WebSocket에도 쿠키를 같이 보낸다. 다른 사이트의 페이지가 교수의 쿠키로 연결하지 못하게 한다
    if websocket.headers.get("origin") != websocket.app.state.allowed_origin:
        await websocket.close(code=1008)
        return
    sub = websocket.app.state.bus.subscribe(admin_room(granted.resource.id))
    try:
        await websocket.accept()
        await websocket.send_json({"type": "ready"})
        tasks = {asyncio.create_task(_pump(websocket, sub)), asyncio.create_task(_watch(websocket))}
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        for task in done:
            # 클라이언트가 끊어서 보내지 못한 것은 정상이다. 그 밖의 오류는 그대로 올린다
            with contextlib.suppress(WebSocketDisconnect, RuntimeError):
                task.result()
    finally:
        sub.close()
