"""Bridges the Scheduler's event queue to any number of connected
browser clients over WebSocket.
"""

import asyncio
import json
import logging

import websockets
from websockets.asyncio.server import ServerConnection

from replay import Scheduler

logger = logging.getLogger(__name__)

WRITE_TIMEOUT_SECONDS = 2.0


class Hub:
    def __init__(self, scheduler: Scheduler):
        self.scheduler = scheduler
        self.clients: set[ServerConnection] = set()
        # Guards against a real race: if scheduler.run() started before any
        # client connected, the very first event(s) would be emitted to zero
        # listeners and silently lost. Instead we start playback lazily on
        # the first connection, which also happens to give a nicer demo --
        # the replay begins the moment you open the page.
        self._scheduler_started = False

    async def broadcast(self) -> None:
        """Drains the scheduler's queue and pushes each event to every
        connected client. Runs as its own asyncio.Task alongside
        scheduler.run()."""
        while True:
            event = await self.scheduler.out.get()
            data = json.dumps(event.to_json_dict())

            # Send to all clients concurrently; a slow/stuck client gets
            # dropped via its own timeout rather than stalling everyone else.
            await asyncio.gather(
                *(self._send_with_timeout(client, data) for client in list(self.clients)),
                return_exceptions=True,
            )

    async def _send_with_timeout(self, client: ServerConnection, data: str) -> None:
        try:
            await asyncio.wait_for(client.send(data), timeout=WRITE_TIMEOUT_SECONDS)
        except (TimeoutError, websockets.ConnectionClosed):
            self.clients.discard(client)

    async def handle_connection(self, client: ServerConnection) -> None:
        """Registers a client and reads playback-control messages from it
        until it disconnects. Passed to websockets.serve()."""
        self.clients.add(client)
        if not self._scheduler_started:
            self._scheduler_started = True
            asyncio.create_task(self.scheduler.run())
        try:
            async for raw in client:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                await self._apply_control(msg)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(client)

    async def _apply_control(self, msg: dict) -> None:
        action = msg.get("action")
        if action == "speed":
            await self.scheduler.set_speed(float(msg.get("speed", 1.0)))
        elif action == "pause":
            await self.scheduler.set_paused(bool(msg.get("paused", False)))
        elif action == "seek":
            await self.scheduler.seek(int(msg.get("index", 0)))
