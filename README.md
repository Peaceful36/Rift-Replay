# Rift Replay

Replays a completed League of Legends match as if it were happening live — streaming timeline events at their original relative timing over WebSocket to a browser dashboard that tracks gold differential and win probability in real time.

![status](https://img.shields.io/badge/status-in%20progress-yellow)

---

## Why replay instead of live data

Riot's spectator endpoint (`spectator-v4`) only exposes **pre-game** information — champion picks, runes, summoner spells. There is no public endpoint for real-time in-game state (gold, positions, objectives) while a match is in progress.

So instead of streaming a live game, this project takes a **completed** match's timeline and replays it on a virtual clock. The timeline API returns two granularities in one payload:

- **Frames** — snapshots of every participant's gold, XP, level, and position, roughly every 60 seconds of game time
- **Events** — precisely-timestamped discrete moments (`CHAMPION_KILL`, `ELITE_MONSTER_KILL`, `ITEM_PURCHASED`, `BUILDING_KILL`, …)

Both are normalized into a single time-sorted stream and replayed together.

A side benefit: the demo runs any time, not just during a live match.

---

## Architecture

```
Riot API  ──▶  ingest  ──▶  compute  ──▶  scheduler  ──▶  ws hub  ──▶  browser
                 │                            ▲                          │
            disk cache                        └──── control messages ─────┘
                                                   (speed / pause / seek)
```

| Layer | Responsibility |
|---|---|
| `ingest/riot.py` | Fetches match-v5 timeline, normalizes Riot's nested JSON into a flat `Event` stream |
| `ingest/cache.py` | Caches fetched timelines to disk, keyed by match ID |
| `ingest/compute.py` | Enriches frame events with team gold, gold differential, win probability, and formatted game time |
| `replay/scheduler.py` | Emits events on a virtual clock; speed multiplier, pause, seek |
| `ws/server.py` | Broadcasts events to connected clients; receives playback control messages |
| `frontend/` | Vanilla JS dashboard with a live Chart.js win-probability curve |

**The key property:** the scheduler knows nothing about WebSockets, and the WebSocket hub knows nothing about Riot's data format. Each layer only touches the one adjacent to it. Adding a second data source means writing a new `ingest` module — nothing else changes.

---

## Setup

```bash
pip install -r requirements.txt
```

Get a development API key from [developer.riotgames.com](https://developer.riotgames.com).

```bash
# macOS / Linux
export RIOT_API_KEY=RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# Windows PowerShell
$env:RIOT_API_KEY = "RGAPI-xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

> Development keys expire every 24 hours and need to be regenerated.

## Running

```bash
# replay a specific match
python main.py --match NA1_5600789237 --region americas

# or auto-select your most recent match
python main.py --game-name YourName --tag-line NA1 --region americas
```

Then open `frontend/index.html` in a browser.

`--region` takes **regional** routing (`americas` / `europe` / `asia`), not platform routing (`na1` / `euw1` / `kr`). Match-v5 requires the former.

The first run fetches from Riot and caches to `.cache/<matchID>.json`; subsequent runs read from disk.

---

## Win probability

Win probability is estimated from team gold differential using a logistic function:

```
P(team 1 wins) = 1 / (1 + e^(−k · goldDiff))
```

A sigmoid was chosen over a linear scale for two reasons: it returns exactly 0.5 at an even gold count, and it saturates gracefully at the extremes rather than running past 0 or 1 — a 20k gold lead is close to decisive, but never literally certain.

The steepness constant `k = 0.0003` was picked by replaying real matches through four candidate values and checking behaviour at both ends:

| k | 1000g lead, early game | Response to a shrinking lead |
|---|---|---|
| 0.0001 | ~52% | Barely moves — too flat to be informative |
| **0.0003** | **~57%** | **Drops proportionally as the lead narrows** |
| 0.0005 | ~62% | Slightly overconfident early |
| 0.001 | ~73% | Stays >78% even after a lead is halved — too sticky |

**This is a tuned heuristic, not a trained model.** It was calibrated against two matches, uses gold differential as its only input, and ignores factors a real model would weight heavily — objective control, team composition scaling, and game duration. A proper version would regress historical match outcomes against gold-differential-over-time across a large sample.

---

## Design notes

**Lazy scheduler start.** The scheduler originally began emitting the moment it was constructed. If it started before any client connected, the first events were broadcast to zero listeners and lost silently. Playback now starts on the first WebSocket connection — which closes the race and has the nice side effect that the replay begins when you open the page.

**Control-message latency.** A speed change sent over the WebSocket may not affect the very next event, because that event's wait duration was already computed before the message arrived. This is inherent to the design rather than a bug — the scheduler doesn't retroactively adjust a sleep already in progress — and the smoke test accounts for it explicitly.

**Compute runs once, upfront.** Gold differential and win probability are calculated after ingestion and before the scheduler starts, then attached to each frame's payload. Nothing is recomputed per broadcast, and the frontend renders values rather than deriving them.

**Bounded per-client writes.** Each broadcast fans out concurrently with a per-connection write timeout, so one slow or stalled client can't hold up delivery to the others.

---

## Testing

```bash
python test_smoke.py
```

Exercises the scheduler and WebSocket hub end-to-end against synthetic events — no API key or network access required. Worth running before touching the ingestion layer, since it isolates the two trickiest pieces (event pacing, speed control) from Riot's API entirely.

---

## Limitations

- One match per process; no session registry for concurrent replays
- No persistence beyond the disk cache — a single immutable match doesn't need a database
- Win probability uses gold differential only
- Participants are identified by ID rather than champion name (champion data lives in the match endpoint, which isn't fetched)

## Roadmap

- [ ] Champion names and icons in place of participant IDs
- [ ] Playback controls in the UI instead of console commands
- [ ] Event feed panel alongside the chart (kills, objectives, buildings)
- [ ] Dual-axis chart showing gold differential and win probability together
- [ ] Support for multiple concurrent replay sessions

---

## Stack

Python · asyncio · websockets · requests · JavaScript · Chart.js · Riot Games API (match-v5)
