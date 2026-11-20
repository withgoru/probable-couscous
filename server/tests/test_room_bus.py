"""C15: RoomBus(방 발행/구독)의 프로세스 안 메모리 구현. 스레드에서 발행해도 안전하고, 느린 구독자는 메모리를 늘리지 않는다."""

import asyncio
import threading

from app.realtime import InMemoryRoomBus, admin_room


def run(coro):
    return asyncio.run(asyncio.wait_for(coro, timeout=5))


def test_a_subscriber_gets_what_is_published_to_its_room_in_order():
    async def scenario():
        bus = InMemoryRoomBus()
        sub = bus.subscribe("room-a")
        for i in range(3):
            bus.publish("room-a", {"type": "x", "n": i})
        return [await sub.get() for _ in range(3)]

    assert run(scenario()) == [{"type": "x", "n": 0}, {"type": "x", "n": 1}, {"type": "x", "n": 2}]


def test_rooms_are_isolated():
    async def scenario():
        bus = InMemoryRoomBus()
        a, b = bus.subscribe("room-a"), bus.subscribe("room-b")
        bus.publish("room-a", {"type": "only-a"})
        bus.publish("room-b", {"type": "only-b"})
        return await a.get(), await b.get()

    assert run(scenario()) == ({"type": "only-a"}, {"type": "only-b"})


def test_every_subscriber_of_a_room_gets_its_own_copy():
    async def scenario():
        bus = InMemoryRoomBus()
        one, two = bus.subscribe("r"), bus.subscribe("r")
        bus.publish("r", {"type": "x"})
        first, second = await one.get(), await two.get()
        first["changed"] = True  # 한쪽이 고쳐도 다른 쪽에 영향이 없다
        return first, second

    first, second = run(scenario())
    assert second == {"type": "x"} and first == {"type": "x", "changed": True}


def test_publishing_with_nobody_listening_is_fine():
    InMemoryRoomBus().publish("empty", {"type": "x"})


def test_a_closed_subscription_gets_nothing_and_the_room_is_forgotten():
    async def scenario():
        bus = InMemoryRoomBus()
        sub = bus.subscribe("r")
        assert bus.subscriber_count("r") == 1
        sub.close()
        sub.close()  # 두 번 닫아도 된다
        bus.publish("r", {"type": "x"})
        await asyncio.sleep(0.01)
        return bus.subscriber_count("r"), bus.rooms()

    assert run(scenario()) == (0, [])


def test_publishing_from_another_thread_reaches_a_subscriber_on_the_event_loop():
    async def scenario():
        bus = InMemoryRoomBus()
        sub = bus.subscribe("r")
        worker = threading.Thread(target=lambda: [bus.publish("r", {"type": "x", "n": i}) for i in range(20)])
        worker.start()
        got = [await sub.get() for _ in range(20)]
        worker.join()
        return [e["n"] for e in got]

    assert run(scenario()) == list(range(20))


def test_a_slow_subscriber_is_told_to_resync_instead_of_growing_without_bound():
    async def scenario():
        bus = InMemoryRoomBus(max_queue=5)
        slow = bus.subscribe("r")
        fast = bus.subscribe("r")
        for i in range(12):
            bus.publish("r", {"type": "x", "n": i})
            if i < 5:
                assert (await fast.get())["n"] == i  # 빠른 구독자는 계속 비운다
        await asyncio.sleep(0.01)
        first = await slow.get()
        bus.publish("r", {"type": "after"})
        await asyncio.sleep(0.01)
        return first, await slow.get()

    first, second = run(scenario())
    assert first == {"type": "resync"}  # 놓친 것을 알려 주고, 쌓인 것은 버린다
    assert second == {"type": "after"}  # 그 뒤로는 다시 정상이다


def test_the_admin_room_name_is_per_classroom():
    assert admin_room(3) != admin_room(4) and admin_room(3) == admin_room(3)
