import argparse
import asyncio
import logging
import os
import sys

from websockets.asyncio.server import serve

from ingest import Client, fetch_timeline_cached
from ingest.compute import enrich_frame_events
from replay import Scheduler
from ws import Hub

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("main")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Replay a LoL match timeline over WebSocket")
    p.add_argument("--match", help="Match ID to replay, e.g. NA1_4567891234")
    p.add_argument("--game-name", help="Riot ID gameName (used if --match omitted)")
    p.add_argument("--tag-line", help="Riot ID tagLine, e.g. NA1")
    p.add_argument("--region", default="americas", choices=["americas", "europe", "asia"])
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=8080)
    return p.parse_args()


async def main() -> None:
    args = parse_args()

    api_key = os.environ.get("RIOT_API_KEY")
    if not api_key:
        log.error(
            "RIOT_API_KEY env var not set -- get a dev key at "
            "https://developer.riotgames.com (expires every 24h)"
        )
        sys.exit(1)

    client = Client(api_key, args.region)

    match_id = args.match
    if not match_id:
        if not args.game_name or not args.tag_line:
            log.error("either --match, or both --game-name and --tag-line, must be provided")
            sys.exit(1)
        puuid = client.resolve_puuid(args.game_name, args.tag_line)
        ids = client.recent_match_ids(puuid, count=5)
        if not ids:
            log.error("no recent matches found for that Riot ID")
            sys.exit(1)
        match_id = ids[0]
        log.info("no --match given, using most recent match: %s", match_id)

    log.info("loading timeline for %s (cached after first fetch)...", match_id)
    events = fetch_timeline_cached(client, match_id)
    log.info("loaded %d events", len(events))

    scheduler = Scheduler(events)
    enrich_frame_events(events)
    hub = Hub(scheduler)

    # Scheduler.run() is started lazily by Hub on first client connection
    # (see ws/server.py) -- only the broadcast loop needs to run from the start.
    broadcast_task = asyncio.create_task(hub.broadcast())

    async with serve(hub.handle_connection, args.host, args.port):
        log.info(
            "listening on %s:%d (connect frontend to ws://%s:%d)",
            args.host, args.port, args.host, args.port,
        )
        await broadcast_task


if __name__ == "__main__":
    asyncio.run(main())
