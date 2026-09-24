"""Saved stalls as replayable scenarios (made by the batch runner).

    python3 -m pilot.scenario list
    python3 -m pilot.scenario run <name> [--brain rules|haiku] [--max-turns 5000]
    python3 -m pilot.scenario restore <name>     # then: ./nh <name> (and the pilot, if you like)

NetHack deletes a save when it's restored, so the copy in
playground/scenarios/ is never touched; each run restores a fresh copy.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import shutil

from .batch import SCENARIOS, PLAYGROUND, Game, prepare_playground, xlog_entries
from .brain import HaikuBrain, RuleBrain


def load(name: str) -> dict:
    with open(os.path.join(SCENARIOS, name + ".json")) as f:
        return json.load(f)


def restore(name: str) -> None:
    meta = load(name)
    os.makedirs(os.path.join(PLAYGROUND, "save"), exist_ok=True)
    shutil.copy2(os.path.join(SCENARIOS, meta["save"]), os.path.join(PLAYGROUND, "save", meta["save"]))


def main() -> None:
    p = argparse.ArgumentParser(description="Replay saved stalls")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    r = sub.add_parser("run")
    r.add_argument("name")
    r.add_argument("--brain", choices=("rules", "haiku"), default="rules")
    r.add_argument("--max-turns", type=int, default=5000, help="turns past the save point")
    rs = sub.add_parser("restore")
    rs.add_argument("name")
    args = p.parse_args()

    if args.cmd == "list":
        for path in sorted(glob.glob(os.path.join(SCENARIOS, "*.json"))):
            m = json.load(open(path))
            print(f"{m['name']:14} Dlvl {m['dlvl']} T{m['turn']} HP {m['hp']}  {m['why'][:70]}")
        return
    if args.cmd == "restore":
        restore(args.name)
        print(f"restored; run ./nh {args.name} (NETHACK_CONTROL points it at the pilot)")
        return

    prepare_playground()
    meta = load(args.name)
    restore(args.name)
    brain = HaikuBrain(log_path=os.path.join(PLAYGROUND, "pilot-brain.log")) if args.brain == "haiku" else RuleBrain()
    g = Game(args.name, "Valkyrie", brain, int(meta["turn"] or 0) + args.max_turns, 600, save_on_stall=False,
             out_dir=os.path.join(PLAYGROUND, "replays"))
    r = g.play()
    rec = xlog_entries().get(args.name) if not r["stall"] else None
    print(f"was: {meta['why']}")
    print(f"now: Dlvl {r['dlvl']} XL {r['xlvl']} T{r['turn']} "
          + (f"died: {rec['death']}" if rec else f"stalled: {r['stall']}" if r["stall"] else "ended"))
    turns = {k[7:]: v for k, v in r.get("stats", {}).items() if k.startswith("turns: ")}
    if turns:
        total = sum(turns.values())
        print("turns: " + ", ".join(f"{k} {v} ({100 * v // total}%)" for k, v in
                                   sorted(turns.items(), key=lambda kv: -kv[1])[:8]))
    other = {k: v for k, v in r.get("stats", {}).items() if not k.startswith("turns: ")}
    if other:
        print("stats: " + ", ".join(f"{k} {v}" for k, v in sorted(other.items())))
    # A replay that ends normally leaves no save; one that stalls was killed,
    # so its partial save (if any) is left alone and the original stays put.


if __name__ == "__main__":
    main()
