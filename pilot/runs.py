"""The batch bookkeeping that kept getting retyped as shell one-liners.

    python3 -m pilot.runs list [--brain rules|haiku|qwen] [--seed N] [-n 10]
    python3 -m pilot.runs show <run>            # summary: depth, XL, buckets, brain calls/failures/seconds
    python3 -m pilot.runs baseline --seed N [--brain rules] [--games 64]   # latest matching run id
    python3 -m pilot.runs pair --seed N [--games 64] [--parallel 16] [--baseline RUN]
        # run a rules batch and compare it with the latest baseline for that seed (the keep/drop step)
"""

from __future__ import annotations

import argparse
import collections
import glob
import json
import os
import subprocess
import sys

from .batch import PLAYGROUND

BATCH = os.path.join(PLAYGROUND, "batch")
HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(run: str) -> dict:
    with open(os.path.join(BATCH, f"{run}.json")) as f:
        return json.load(f)


def runs(brain: str | None = None, seed: int | None = None, games: int | None = None, journal: bool | None = None) -> list[dict]:
    """All runs, newest first, filtered."""
    out = []
    for path in sorted(glob.glob(os.path.join(BATCH, "2*.json")), reverse=True):
        try:
            d = json.load(open(path))
        except (OSError, ValueError):
            continue
        if brain and d.get("brain") != brain:
            continue
        if seed is not None and d.get("seed") != seed:
            continue
        if games is not None and len(d.get("games", [])) != games:
            continue
        if journal is not None and bool(d.get("journal", True)) != journal:
            continue
        out.append(d)
    return out


def summary(d: dict) -> str:
    g = d["games"]
    n = len(g) or 1
    avg = lambda k: sum(float(x.get(k) or 0) for x in g) / n
    buckets = collections.Counter(x["bucket"] for x in g)
    brain = ""
    if d.get("brain") != "rules":
        brain = (f"; brain {sum(x.get('brain_calls', 0) for x in g)} calls, {sum(x.get('brain_failures', 0) for x in g)} failed, "
                 f"{sum(x.get('brain_seconds', 0) for x in g)} s")
    return (f"{d['run']} {d.get('brain')}{' ' + str(d.get('model')) if d.get('model') else ''} seed {d.get('seed')} "
            f"{'no-conclusions ' if d.get('journal') is False else ''}{len(g)} games: deepest {avg('maxlvl'):.2f} XL {avg('xlvl'):.2f} "
            f"turns {avg('turn'):.0f}{brain}\n  " + ", ".join(f"{k} {v}" for k, v in buckets.most_common()))


def run_batch(args: list[str]) -> str:
    """Run pilot.batch with the given arguments and return the run id, or fail loudly."""
    out = subprocess.run([sys.executable, "-m", "pilot.batch", *args], capture_output=True, text=True, cwd=HERE)
    for line in out.stdout.splitlines():
        if line.startswith("details:"):
            return os.path.basename(line.split()[-1]).replace(".csv", "")
    raise SystemExit(f"batch produced no result:\n{(out.stdout + out.stderr)[-3000:]}")


def compare(a: str, b: str) -> str:
    return subprocess.run([sys.executable, "-m", "pilot.compare", a, b], capture_output=True, text=True, cwd=HERE).stdout


def main() -> None:
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    ls = sub.add_parser("list")
    ls.add_argument("--brain")
    ls.add_argument("--seed", type=int)
    ls.add_argument("-n", type=int, default=10)
    sh = sub.add_parser("show")
    sh.add_argument("run")
    bl = sub.add_parser("baseline")
    bl.add_argument("--seed", type=int, required=True)
    bl.add_argument("--brain", default="rules")
    bl.add_argument("--games", type=int, default=64)
    pr = sub.add_parser("pair")
    pr.add_argument("--seed", type=int, default=1000)
    pr.add_argument("--games", type=int, default=64)
    pr.add_argument("--parallel", type=int, default=16)
    pr.add_argument("--baseline", help="run id to compare against (default: latest rules run on this seed and size)")
    pr.add_argument("--max-seconds", default="600")
    args = p.parse_args()

    if args.cmd == "list":
        for d in runs(args.brain, args.seed)[:args.n]:
            print(summary(d))
    elif args.cmd == "show":
        print(summary(load(args.run)))
    elif args.cmd == "baseline":
        found = runs(args.brain, args.seed, args.games)
        print(found[0]["run"] if found else "")
    elif args.cmd == "pair":
        base = args.baseline or (runs("rules", args.seed, args.games) or [{}])[0].get("run")
        if not base:
            raise SystemExit("no baseline run for that seed; run a batch first or pass --baseline")
        new = run_batch(["--games", str(args.games), "--parallel", str(args.parallel), "--brain", "rules",
                         "--seed", str(args.seed), "--max-seconds", args.max_seconds])
        out = compare(base, new)
        same = sum(1 for l in out.splitlines() if " SAME " in l)
        print(f"baseline {base} -> {new} ({same} of {args.games} games identical)")
        print("\n".join(l for l in out.splitlines() if l.startswith(("before", "after", "deepest change", "XL change"))))


if __name__ == "__main__":
    main()
