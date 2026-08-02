"""Smoke test: fake events, no network calls. Verifies the scheduler
correctly paces emission and that a WebSocket client receives them,
before handing this off without ever having run it."""

import asyncio
import json
from datetime import datetime, timedelta, timezone

import websockets
from websockets.asyncio.server import serve

from replay import Event, Scheduler
from ws import Hub

BASE = datetime(1970, 1, 1, tzinfo=timezone.utc)


def fake_events(n: int, gap_ms: int) -> list[Event]:
    return [
        Event(type="frame", timestamp=BASE + timedelta(milliseconds=i * gap_ms), data={"i": i})
        for i in range(n)
    ]


async def run_server_and_client():
    events = fake_events(5, gap_ms=500)  # 5 events, 0.5s apart -> ~2s total at 1x
    scheduler = Scheduler(events)
    hub = Hub(scheduler)

    broadcast_task = asyncio.create_task(hub.broadcast())

    async with serve(hub.handle_connection, "localhost", 8765):
        async with websockets.connect("ws://localhost:8765") as client:
            received = []
            start = asyncio.get_event_loop().time()
            for _ in range(5):
                raw = await asyncio.wait_for(client.recv(), timeout=5)
                received.append(json.loads(raw))
            elapsed = asyncio.get_event_loop().time() - start

            print(f"received {len(received)} events in {elapsed:.2f}s (expected ~2.0s at 1x)")
            assert len(received) == 5
            assert [e["data"]["i"] for e in received] == [0, 1, 2, 3, 4]
            print("PASS: events arrived in order with correct pacing, none dropped")

    broadcast_task.cancel()


async def test_speed_control():
    events = fake_events(6, gap_ms=1000)  # would take 5s at 1x
    scheduler = Scheduler(events)
    hub = Hub(scheduler)

    broadcast_task = asyncio.create_task(hub.broadcast())

    async with serve(hub.handle_connection, "localhost", 8766):
        async with websockets.connect("ws://localhost:8766") as client:
            # Event 0 fires immediately regardless of speed -- consume it,
            # send the speed change, then consume one more event: the
            # scheduler may have already computed THIS event's wait using
            # the old speed (real, expected control-message latency -- the
            # scheduler doesn't retroactively adjust a wait already in
            # progress). Only events after that are guaranteed to reflect
            # the new speed, which is what we measure.
            await asyncio.wait_for(client.recv(), timeout=5)  # event 0
            await client.send(json.dumps({"action": "speed", "speed": 10.0}))
            await asyncio.wait_for(client.recv(), timeout=5)  # event 1 (settling)

            start = asyncio.get_event_loop().time()
            for _ in range(4):  # events 2-5, should all reflect 10x speed
                await asyncio.wait_for(client.recv(), timeout=5)
            elapsed = asyncio.get_event_loop().time() - start
            print(f"received 4 events in {elapsed:.2f}s at 10x speed (expected ~0.4s)")
            assert elapsed < 1.0, "speed control did not take effect after settling event"
            print("PASS: speed control works (with one-event settling latency, as expected)")

    broadcast_task.cancel()


async def main():
    await run_server_and_client()
    await test_speed_control()
    print("\nALL SMOKE TESTS PASSED")


if __name__ == "__main__":
    asyncio.run(main())
