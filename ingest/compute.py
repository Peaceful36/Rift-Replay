from datetime import timedelta
import math
from ingest.riot import GAME_START
from replay.event import Event

K = 0.0003

def enrich_frame_events(events: list[Event]) -> None:
    """Compute derived values for each frame event in the timeline.
    This includes team gold, gold difference, win probability, and game time."""
    for event in events:
        if event.type == "frame":
            # check that all participantFrames are present
            for pid in ["1", "2", "3", "4", "5", "6", "7", "8", "9", "10"]:
                if pid not in event.data["participantFrames"]:
                    raise ValueError(f"Missing participant frame for pid {pid}")
            break
                
    for event in events:
        if event.type != "frame":
            continue
        
        # 1. compute team1_gold and team2_gold from event.data["participantFrames"]
        team1_gold = sum(frame["totalGold"] for pid, frame in event.data["participantFrames"].items() if int(pid) <= 5)
        team2_gold = sum(frame["totalGold"] for pid, frame in event.data["participantFrames"].items() if int(pid) > 5)

        # 2. compute gold_diff
        gold_diff = team1_gold - team2_gold

        # 3. compute win_probability using the sigmoid with k=0.0003
        win_probability = 1 / (1 + math.exp(-K * gold_diff))

        # 4. add both values into event.data
        event.data["team1_gold"] = team1_gold
        event.data["team2_gold"] = team2_gold
        event.data["gold_diff"] = gold_diff
        event.data["win_probability"] = win_probability

        # 5. compute game time
        elapsed = event.timestamp - GAME_START
        total_seconds = int(elapsed.total_seconds())
        minutes, seconds = divmod(total_seconds, 60)
        event.data["game_time"] = f"{minutes:02}:{seconds:02}"
