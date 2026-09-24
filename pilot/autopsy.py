"""Autopsy: rank the real causes of lost games across many runs.

    python3 -m pilot.autopsy <run> [<run> ...]
    python3 -m pilot.autopsy --drill <run>/<name> <from_turn> <to_turn>   # replay, print each step

The bucket a game ends in (Weak, no way on, melee) names the symptom.
Both large wins so far (engulfed pilots read as a 1x1 room, loot and
explore ping-ponging at a shop door) were found by looking for EFFORT
WITHOUT PROGRESS instead: turns passing while depth, XL and the known
map all stop changing. This reads each game's 50-turn progress trace,
finds such windows, and groups them by what the engine was doing.
"""

from __future__ import annotations

import collections
import json
import os
import sys

from .batch import PLAYGROUND

MIN_WINDOW = 300   # turns of no progress before it counts
MAP_GROWTH = 4     # known squares gained per 50 turns that still counts as "no progress"


def windows(trace: list) -> list[dict]:
    """Maximal runs of trace points with no new depth or XL and (almost) no
    new map. Each: start, end turn, dominant activity, hunger at the end."""
    out, cur = [], None
    for prev, pt in zip(trace, trace[1:]):
        turn, dlvl, xl, hp, hunger, known, act = pt
        stuck = dlvl == prev[1] and xl == prev[2] and (known or 0) - (prev[5] or 0) < MAP_GROWTH
        if stuck:
            if cur is None:
                cur = {"start": prev[0], "acts": collections.Counter(), "hunger": hunger}
            cur["end"], cur["hunger"] = turn, hunger
            cur["acts"][act or "?"] += 1
        elif cur is not None:
            out.append(cur)
            cur = None
    if cur is not None:
        cur["terminal"] = True
        out.append(cur)
    for w in out:
        w["turns"] = w["end"] - w["start"]
        w["activity"] = w["acts"].most_common(1)[0][0]
        w.setdefault("terminal", False)
    return [w for w in out if w["turns"] >= MIN_WINDOW]


def drill(which: str, lo: int, hi: int) -> None:
    """Replay a seeded rules game and print, for turns lo..hi, the position,
    the keys sent and the engine's note: what a stall window looks like."""
    from .batch import Game, prepare_playground, RuleBrain
    run, name = which.split("/")
    with open(os.path.join(PLAYGROUND, "batch", f"{run}.json")) as f:
        rec = next(g for g in json.load(f)["games"] if g["name"] == name)
    prepare_playground()
    g = Game(f"D{name[1:]}", rec.get("role", "Valkyrie"), RuleBrain(), hi, 900, save_on_stall=False,
             out_dir=os.path.join(PLAYGROUND, "replays"), seed=rec["seed"])
    shown, last = 0, None
    orig = g.channel.on_state

    def on_state(s):
        nonlocal shown, last
        turn = s.get("status", {}).get("turn", 0)
        if lo <= turn <= hi and shown == 0:
            for y, row in enumerate(s.get("map", [])):
                if row.strip():
                    print(f"{y:2d} {row.rstrip()}")
            shown = 1
        orig(s)
        if lo <= turn <= hi and g.keys and g.keys[-1] != last and shown < 60:
            last = g.keys[-1]
            shown += 1
            print(f"T{turn} @{s.get('player')} {last[1]!r:8} {g.engine.note[:70]}")
    g.channel.on_state = on_state
    g.play()


def main() -> None:
    if sys.argv[1:2] == ["--drill"]:
        drill(sys.argv[2], int(sys.argv[3]), int(sys.argv[4]))
        return
    games = []
    for run in sys.argv[1:]:
        with open(os.path.join(PLAYGROUND, "batch", f"{run}.json")) as f:
            games += json.load(f)["games"]
    total_turns = sum(int(g.get("turn") or 0) for g in games)
    causes: dict[str, dict] = collections.defaultdict(lambda: {"games": set(), "turns": 0, "terminal": 0,
                                                              "endings": collections.Counter(), "examples": []})
    stuck_turns = 0
    for g in games:
        for w in windows(g.get("trace") or []):
            c = causes[w["activity"]]
            c["games"].add(g["name"])
            c["turns"] += w["turns"]
            stuck_turns += w["turns"]
            if w["terminal"]:
                c["terminal"] += 1
                c["endings"][g["bucket"]] += 1
            if len(c["examples"]) < 4:
                c["examples"].append(f"{g['name']} T{w['start']}-{w['end']} ({w['hunger'] or 'fed'}, {g['bucket']})")
    print(f"{len(games)} games, {total_turns} turns; {stuck_turns} turns ({100 * stuck_turns // max(total_turns, 1)}%) "
          f"in windows of {MIN_WINDOW}+ turns with no new depth, XL or map.\n")
    print(f"{'activity during the stall':28} {'games':>5} {'turns':>7} {'ended game':>10}  endings when it ended the game")
    for act, c in sorted(causes.items(), key=lambda kv: -kv[1]["turns"]):
        endings = ", ".join(f"{k} {v}" for k, v in c["endings"].most_common(3))
        print(f"{act[:28]:28} {len(c['games']):>5} {c['turns']:>7} {c['terminal']:>10}  {endings}")
    print("\nExamples (name, turn range, hunger, how the game ended):")
    for act, c in sorted(causes.items(), key=lambda kv: -kv[1]["turns"])[:8]:
        print(f"  {act}: " + "; ".join(c["examples"]))

    # Deaths: how far past (or short of) their level the character was.
    deaths = [g for g in games if g.get("death")]
    gap = collections.Counter(int(g["dlvl"] or 0) - int(g["xlvl"] or 0) for g in deaths)
    print(f"\n{len(deaths)} deaths; dlvl minus XL at death: " + ", ".join(f"{k:+d}: {v}" for k, v in sorted(gap.items())))
    killers = collections.Counter((g["death"] or "").replace("killed by ", "").replace("poisoned by ", "")
                                  .replace("an ", "").replace("a ", "").split(";")[0] for g in deaths)
    print("top killers: " + ", ".join(f"{k} {v}" for k, v in killers.most_common(12)))


if __name__ == "__main__":
    main()
