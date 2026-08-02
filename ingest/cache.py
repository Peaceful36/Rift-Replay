"""Disk cache so repeated dev runs don't re-hit Riot's rate limits
"""

import json
from dataclasses import asdict
from datetime import datetime
from pathlib import Path

from replay import Event
from .riot import Client

CACHE_DIR = Path(".cache")


def _cache_path(match_id: str) -> Path:
    safe = match_id.replace("/", "_")
    return CACHE_DIR / f"{safe}.json"


def _event_to_dict(e: Event) -> dict:
    d = asdict(e)
    d["timestamp"] = e.timestamp.isoformat()
    return d


def _event_from_dict(d: dict) -> Event:
    return Event(type=d["type"], timestamp=datetime.fromisoformat(d["timestamp"]), data=d["data"])


def fetch_timeline_cached(client: Client, match_id: str) -> list[Event]:
    path = _cache_path(match_id)

    if path.exists():
        try:
            raw = json.loads(path.read_text())
            return [_event_from_dict(d) for d in raw]
        except (json.JSONDecodeError, KeyError):
            pass  # corrupt/stale cache -- fall through and re-fetch

    events = client.fetch_timeline(match_id)

    CACHE_DIR.mkdir(exist_ok=True)
    path.write_text(json.dumps([_event_to_dict(e) for e in events]))

    return events
