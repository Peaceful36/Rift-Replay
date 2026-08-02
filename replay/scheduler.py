"""Replay scheduler: emits pre-loaded events on a virtual clock.
"""

import asyncio
from datetime import timedelta

from .event import Event

MAX_WAIT_SECONDS = 5.0  # cap so one huge gap in source data doesn't stall a demo
PAUSE_POLL_SECONDS = 0.2


class Scheduler:
    def __init__(self, events: list[Event]):
        self.events = events
        self.pos = 0
        self.speed = 1.0
        self.paused = False
        self._lock = asyncio.Lock()
        self.out: asyncio.Queue[Event] = asyncio.Queue(maxsize=16)

    async def set_speed(self, speed: float) -> None:
        async with self._lock:
            self.speed = speed

    async def set_paused(self, paused: bool) -> None:
        async with self._lock:
            self.paused = paused

    async def seek(self, index: int) -> None:
        async with self._lock:
            self.pos = max(0, min(index, len(self.events)))

    async def _current_speed(self) -> float:
        async with self._lock:
            return 0.0 if self.paused else self.speed

    async def _wait_for(self, pos: int) -> float:
        """Seconds to sleep before emitting the event at index pos."""
        if pos == 0:
            return 0.0

        speed = await self._current_speed()
        if speed <= 0:
            return PAUSE_POLL_SECONDS

        gap: timedelta = self.events[pos].timestamp - self.events[pos - 1].timestamp
        gap_seconds = max(gap.total_seconds(), 0.0)
        scaled = gap_seconds / speed
        return min(scaled, MAX_WAIT_SECONDS)

    async def run(self) -> None:
        """Drives playback until all events are emitted or the task is
        cancelled. Intended to be run as its own asyncio.Task."""
        while True:
            async with self._lock:
                pos = self.pos
            if pos >= len(self.events):
                return

            wait = await self._wait_for(pos)
            if wait > 0:
                await asyncio.sleep(wait)

            async with self._lock:
                if self.pos != pos:
                    # a seek moved us while we were sleeping -- restart
                    # the loop rather than emitting a stale event
                    continue
                event = self.events[self.pos]
                self.pos += 1

            await self.out.put(event)
