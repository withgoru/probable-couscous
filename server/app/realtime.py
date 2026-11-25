"""교수 화면 실시간(C13, C15): `RoomBus`(방 발행/구독)와 그 프로세스 안 메모리 구현.

- 발행은 어느 스레드에서 불러도 된다. 라우트 함수는 스레드풀에서, WebSocket은 이벤트 루프에서 돌기 때문이다.
- 구독자마다 큐가 있고, 가득 차면(느린 화면) 쌓인 이벤트를 버리고 `{"type": "resync"}` 하나로 대신한다. 서버 메모리가 늘지 않는다.
- 이벤트는 종류와 번호만 싣는다. 개인정보와 코드는 싣지 않는다. 화면은 받으면 HTTP로 다시 불러온다.
- 여러 서버로 늘릴 때는 이 인터페이스의 구현만 바꾼다. 지금은 만들지 않는다(C15).
"""

import asyncio
import copy
import logging
import threading
from typing import Protocol

from starlette.requests import HTTPConnection

log = logging.getLogger(__name__)

DEFAULT_MAX_QUEUE = 100
RESYNC = {"type": "resync"}


def admin_room(classroom_id: int) -> str:
    """강좌 하나의 교수 관리 화면이 구독하는 방."""
    return f"admin:{classroom_id}"


def class_room(classroom_id: int) -> str:
    """강좌 하나의 수업 방(002). 교수 수업 화면·프로젝터·학생 화면이 구독한다."""
    return f"class:{classroom_id}"


class Subscription:
    """한 구독자. 이벤트 루프 안에서 만들고 `get()`으로 하나씩 받는다."""

    def __init__(self, bus: "InMemoryRoomBus", room: str, max_queue: int) -> None:
        self._bus = bus
        self._room = room
        self._loop = asyncio.get_running_loop()
        self._queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue)
        self._overflow = False
        self._closed = False

    def _deliver(self, event: dict) -> bool:
        """어느 스레드에서든 부른다. 루프가 이미 닫혔으면 False."""
        try:
            self._loop.call_soon_threadsafe(self._put, event)
        except RuntimeError:
            return False
        return True

    def _put(self, event: dict) -> None:  # 이벤트 루프 안에서 실행된다
        if self._closed:
            return
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._overflow = True

    async def get(self) -> dict:
        if self._overflow:  # 놓친 것이 있다: 쌓인 것을 버리고 다시 불러오라고 알린다
            self._overflow = False
            while not self._queue.empty():
                self._queue.get_nowait()
            return dict(RESYNC)
        return await self._queue.get()

    def close(self) -> None:
        self._closed = True
        self._bus._remove(self._room, self)


class RoomBus(Protocol):
    def publish(self, room: str, event: dict) -> None: ...

    def subscribe(self, room: str) -> Subscription: ...


class InMemoryRoomBus:
    def __init__(self, max_queue: int = DEFAULT_MAX_QUEUE) -> None:
        self.max_queue = max_queue
        self._rooms: dict[str, list[Subscription]] = {}
        self._lock = threading.Lock()

    def subscribe(self, room: str) -> Subscription:
        sub = Subscription(self, room, self.max_queue)
        with self._lock:
            self._rooms.setdefault(room, []).append(sub)
        return sub

    def publish(self, room: str, event: dict) -> None:
        with self._lock:
            subs = list(self._rooms.get(room, ()))
        for sub in subs:
            if not sub._deliver(copy.deepcopy(event)):
                self._remove(room, sub)  # 루프가 닫힌 구독자

    def _remove(self, room: str, sub: Subscription) -> None:
        with self._lock:
            subs = self._rooms.get(room)
            if subs and sub in subs:
                subs.remove(sub)
            if not subs:
                self._rooms.pop(room, None)

    def subscriber_count(self, room: str) -> int:
        with self._lock:
            return len(self._rooms.get(room, ()))

    def rooms(self) -> list[str]:
        with self._lock:
            return sorted(self._rooms)


def _publish(request: HTTPConnection, room: str, type_: str, data: dict) -> None:
    try:
        request.app.state.bus.publish(room, {"type": type_, **data})
    except Exception:
        log.exception("화면에 알리지 못했습니다(%s). 저장은 끝났습니다.", type_)


def publish_admin(request: HTTPConnection, classroom_id: int, type_: str, **data: object) -> None:
    """교수 관리 화면에 알린다. 이미 저장된 변화에 대해 **저장이 끝난 뒤에** 부른다.

    알리다 실패해도 처리 결과는 바꾸지 않는다(저장은 끝났고 화면은 다시 접속하면 목록을 새로 받는다).
    """
    _publish(request, admin_room(classroom_id), type_, data)


def publish_class(request: HTTPConnection, classroom_id: int, type_: str, **data: object) -> None:
    """수업 방에 알린다. `publish_admin`과 같이 **DB에 기록이 끝난 뒤에** 부르고, 실패해도 결과는 그대로다."""
    _publish(request, class_room(classroom_id), type_, data)
