"""
Tunes the sigmoid steepness constant (k) for win-probability estimation
by replaying real cached match data through several candidate k values
and checking whether the resulting probability curve behaves sensibly:
- stays close to 50% early game (when leads are genuinely uncertain)
- swings decisively toward the actual winner by late game

This reads directly from the .cache/<matchID>.json file your ingest
layer already produces -- no need to re-fetch from Riot.

Usage:
    python tune_k.py --cache path/to/.cache/NA1_5600789237.json --winner 1

    --winner is which team (1 = participantIds 1-5, 2 = participantIds
    6-10) actually won. You have to supply this yourself -- match-v5's
    *timeline* endpoint (which is what you're caching) doesn't include
    the final win/loss result, only the match-v5 *match* endpoint does,
    which you haven't fetched. If you don't know, check the match on
    op.gg or in your own match history.
"""

import argparse
import json
import math


def sigmoid_prob(gold_diff: float, k: float) -> float:
    """Probability team 1 wins, given team1_gold - team2_gold and steepness k."""
    return 1 / (1 + math.exp(-k * gold_diff))


def team_gold_diff(participant_frames: dict) -> float:
    team1 = sum(participant_frames[str(i)]["totalGold"] for i in range(1, 6))
    team2 = sum(participant_frames[str(i)]["totalGold"] for i in range(6, 11))
    return team1 - team2


def load_frames(cache_path: str) -> list[tuple[float, float]]:
    """Returns [(game_time_minutes, gold_diff), ...] for every frame event
    in the cached timeline, in order."""
    with open(cache_path) as f:
        events = json.load(f)

    frames = []
    for e in events:
        if e["type"] != "frame":
            continue
        diff = team_gold_diff(e["data"]["participantFrames"])
        # e["timestamp"] is an ISO string like "1970-01-01T00:12:00+00:00" --
        # minutes since game start is embedded in the H:M:S portion.
        # Simplest robust extraction: parse out hours/minutes from the string.
        _, time_part = e["timestamp"].split("T")
        h, m, s = time_part.split("+")[0].split(":")
        minutes = int(h) * 60 + int(m) + float(s) / 60
        frames.append((minutes, diff))
    return frames


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--cache", required=True, help="Path to cached match JSON")
    parser.add_argument("--winner", type=int, choices=[1, 2], required=True,
                         help="Which team actually won (1 or 2)")
    parser.add_argument("--k-values", type=float, nargs="+",
                         default=[0.0001, 0.0003, 0.0005, 0.001],
                         help="Candidate k values to test")
    args = parser.parse_args()

    frames = load_frames(args.cache)
    if not frames:
        print("No frame events found in cache file -- is the path correct?")
        return

    print(f"Loaded {len(frames)} frame snapshots. Actual winner: Team {args.winner}\n")

    for k in args.k_values:
        print(f"--- k = {k} ---")
        # Print at a handful of representative points: start, quarter marks, end
        checkpoints = [0, len(frames) // 4, len(frames) // 2, 3 * len(frames) // 4, len(frames) - 1]
        for idx in checkpoints:
            minutes, diff = frames[idx]
            prob_team1 = sigmoid_prob(diff, k)
            print(f"  {minutes:5.1f} min | gold_diff={diff:+6.0f} | "
                  f"P(Team 1 wins)={prob_team1:.2%}")

        # Final-frame check: did the model end up confidently favoring
        # the actual winner? This is the real pass/fail signal for this k.
        final_minutes, final_diff = frames[-1]
        final_prob_team1 = sigmoid_prob(final_diff, k)
        final_prob_winner = final_prob_team1 if args.winner == 1 else (1 - final_prob_team1)
        verdict = "GOOD" if final_prob_winner > 0.65 else "TOO FLAT" if final_prob_winner < 0.55 else "OK"
        print(f"  Final probability assigned to actual winner: {final_prob_winner:.2%}  [{verdict}]\n")


if __name__ == "__main__":
    main()
