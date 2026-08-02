"""Riot API client: fetches a completed match's timeline from match-v5
and normalizes it into the replay package's unified Event type.
"""

from datetime import datetime, timedelta, timezone

import requests

from replay import Event

# Match-v5 uses *regional* routing (americas/europe/asia), not platform
# routing (na1/euw1/kr) -- a common gotcha when first working with this API.
REGIONAL_HOST = {
    "americas": "https://americas.api.riotgames.com",
    "europe": "https://europe.api.riotgames.com",
    "asia": "https://asia.api.riotgames.com",
}

# Arbitrary virtual epoch. The scheduler only cares about relative gaps
# between event timestamps, not wall-clock accuracy, so this just needs
# to be consistent across all events within one match.
GAME_START = datetime(1970, 1, 1, tzinfo=timezone.utc)


class RiotAuthError(Exception):
    pass


class RiotRateLimitError(Exception):
    pass


class Client:
    def __init__(self, api_key: str, region: str):
        if region not in REGIONAL_HOST:
            raise ValueError(f"unknown region {region!r} (want americas/europe/asia)")
        self.api_key = api_key
        self.region = region
        self.session = requests.Session()
        self.session.headers["X-Riot-Token"] = api_key

    def _get(self, url: str) -> dict | list:
        resp = self.session.get(url, timeout=10)
        if resp.status_code == 429:
            raise RiotRateLimitError("rate limited by Riot API (429) -- back off and retry")
        if resp.status_code in (401, 403):
            raise RiotAuthError(
                f"auth failed ({resp.status_code}) -- dev keys expire every 24h, "
                "regenerate at developer.riotgames.com"
            )
        resp.raise_for_status()
        return resp.json()

    def resolve_puuid(self, game_name: str, tag_line: str) -> str:
        """Look up a player's PUUID from their Riot ID (gameName + tagLine,
        e.g. 'Faker' + 'KR1'). PUUID is the region-agnostic ID needed for
        the match history lookup below."""
        host = REGIONAL_HOST[self.region]
        url = f"{host}/riot/account/v1/accounts/by-riot-id/{game_name}/{tag_line}"
        data = self._get(url)
        return data["puuid"]

    def recent_match_ids(self, puuid: str, count: int = 5) -> list[str]:
        """Returns up to `count` recent match IDs, most recent first."""
        host = REGIONAL_HOST[self.region]
        url = f"{host}/lol/match/v5/matches/by-puuid/{puuid}/ids?count={count}"
        return self._get(url)

    def fetch_timeline(self, match_id: str) -> list[Event]:
        """Fetch and normalize a completed match's timeline into a single
        time-sorted event stream, ready for replay.Scheduler."""
        host = REGIONAL_HOST[self.region]
        url = f"{host}/lol/match/v5/matches/{match_id}/timeline"
        payload = self._get(url)

        events: list[Event] = []
        for frame in payload["info"]["frames"]:
            frame_ts = GAME_START + timedelta(milliseconds=frame["timestamp"])
            events.append(
                Event(
                    type="frame",
                    timestamp=frame_ts,
                    data={"participantFrames": frame["participantFrames"]},
                )
            )

            for raw_event in frame.get("events", []):
                event_ts = GAME_START + timedelta(
                    milliseconds=raw_event.get("timestamp", frame["timestamp"])
                )
                events.append(
                    Event(
                        type=str(raw_event.get("type", "UNKNOWN")),
                        timestamp=event_ts,
                        data=raw_event,
                    )
                )

        events.sort(key=lambda e: e.timestamp)
        return events
