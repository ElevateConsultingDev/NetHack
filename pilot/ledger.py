"""The tactic ledger: how often each tactic's prediction came true, from recorded runs.

    python3 -m pilot.ledger <run> [<run> ...] [--by symbol|target|fast|hp]

Reads `outcomes` from playground/batch/<run>.json (written by pilot/tactics.py's tracker).
A row is a tactic against a kind of monster; `dead20` is how often the pilot was dead within
20 turns of starting it, whatever the prediction said.
"""

from __future__ import annotations

import collections
import json
import os
import sys

BATCH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "playground", "batch")


def rows(runs: list) -> list:
    out = []
    for run in runs:
        with open(os.path.join(BATCH, f"{run}.json")) as f:
            for g in json.load(f)["games"]:
                end, died = int(g.get("turn") or 0), not g.get("stall")
                for o in g.get("outcomes") or []:
                    out.append({**o, "dead20": died and end - o["turn"] <= 20, "game": g["name"]})
    return out


def key(o: dict, by: str):
    if by == "hp":
        f = o["hp"] / max(o["hpmax"], 1)
        return "HP over 2/3" if f > 0.66 else "HP 1/3 to 2/3" if f > 0.33 else "HP under 1/3"
    if by == "fast":
        return "faster than me" if o["fast"] else "my speed or slower"
    return o.get(by) or "?"


def table(outcomes: list, by: str = "symbol", least: int = 15) -> list:
    groups = collections.defaultdict(list)
    for o in outcomes:
        groups[(o["tactic"], key(o, by))].append(o)
    out = []
    for (tactic, k), os_ in sorted(groups.items(), key=lambda kv: (kv[0][0], -len(kv[1]))):
        if len(os_) < least:
            continue
        n = len(os_)
        st = collections.Counter(o["status"] for o in os_)
        out.append((tactic, k, n, st["met"], st["not_met"], st["unknown"], st["ended_early"], sum(o["dead20"] for o in os_)))
    return out


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    by = sys.argv[sys.argv.index("--by") + 1] if "--by" in sys.argv else "symbol"
    args = [a for a in args if a != by]
    data = rows(args)
    print(f"{len(data)} tactic outcomes from {len(args)} runs, by {by}")
    print(f"{'tactic':9} {'against':20} {'tried':>6} {'met':>5} {'not':>5} {'unk':>5} {'early':>5}  {'met%':>5} {'dead20%':>7}")
    for tactic, k, n, met, notm, unk, early, dead in table(data, by):
        print(f"{tactic:9} {str(k):20} {n:6d} {met:5d} {notm:5d} {unk:5d} {early:5d}  {100 * met / n:5.0f} {100 * dead / n:7.1f}")
