import asyncio
import json
import threading

import pytest

from backend.services.broadcaster import StatsBroadcaster


@pytest.mark.asyncio
async def test_broadcaster_subscribe_and_unsubscribe():
    broadcaster = StatsBroadcaster()
    broadcaster.set_loop(asyncio.get_running_loop())

    assert broadcaster.get_subscriber_count() == 0

    q = await broadcaster.subscribe()
    assert broadcaster.get_subscriber_count() == 1

    await broadcaster.unsubscribe(q)
    assert broadcaster.get_subscriber_count() == 0


@pytest.mark.asyncio
async def test_broadcaster_subscribe_initial_data():
    broadcaster = StatsBroadcaster()
    broadcaster.set_loop(asyncio.get_running_loop())

    initial = {"cpu": {"temp": 45}}
    q = await broadcaster.subscribe(initial_data=initial)

    item = await asyncio.wait_for(q.get(), timeout=1.0)
    assert item == f"data: {json.dumps(initial)}\n\n"

    await broadcaster.unsubscribe(q)


@pytest.mark.asyncio
async def test_broadcaster_broadcast_delivery():
    broadcaster = StatsBroadcaster()
    broadcaster.set_loop(asyncio.get_running_loop())

    q1 = await broadcaster.subscribe()
    q2 = await broadcaster.subscribe()

    data = {"status": "OK", "fans": [1200, 1100]}
    broadcaster.broadcast(data)

    # Allow loop to process call_soon_threadsafe
    await asyncio.sleep(0.01)

    item1 = await asyncio.wait_for(q1.get(), timeout=1.0)
    item2 = await asyncio.wait_for(q2.get(), timeout=1.0)

    expected = f"data: {json.dumps(data)}\n\n"
    assert item1 == expected
    assert item2 == expected

    await broadcaster.unsubscribe(q1)
    await broadcaster.unsubscribe(q2)


@pytest.mark.asyncio
async def test_broadcaster_bounded_queue_drops_oldest():
    broadcaster = StatsBroadcaster()
    broadcaster.set_loop(asyncio.get_running_loop())

    q = await broadcaster.subscribe()

    # Fill queue past capacity (maxsize=10)
    for i in range(15):
        broadcaster.broadcast({"count": i})
        await asyncio.sleep(0.001)

    # Queue should have at most 10 items
    assert q.qsize() <= 10

    # The latest items should be preserved
    items = []
    while not q.empty():
        items.append(await q.get())

    last_data = json.loads(items[-1].removeprefix("data: ").strip())
    assert last_data["count"] == 14

    await broadcaster.unsubscribe(q)


@pytest.mark.asyncio
async def test_broadcaster_multithreaded_broadcast():
    broadcaster = StatsBroadcaster()
    broadcaster.set_loop(asyncio.get_running_loop())

    q = await broadcaster.subscribe()

    def worker():
        broadcaster.broadcast({"source": "thread_worker", "val": 42})

    t = threading.Thread(target=worker)
    t.start()
    t.join()

    await asyncio.sleep(0.01)
    item = await asyncio.wait_for(q.get(), timeout=1.0)
    parsed = json.loads(item.removeprefix("data: ").strip())
    assert parsed["source"] == "thread_worker"
    assert parsed["val"] == 42

    await broadcaster.unsubscribe(q)
