"""Stratigraph efficacy: does the brain get better as strata accumulate?

    python3 -m pilot.strat --brain qwen --cycles 4 [--train-seed 4000] [--test-seed 3000] [--games 32]

Test seeds are never reflected on. Each cycle: a training batch on fresh
seeds, reflect (a new stratum), then a test batch with the new
conclusions. Every test batch is compared with the no-conclusions test
arm, paired by seed with its margin of error: the learning curve.
Results append to memory/events/ as a design event, and to stdout.
"""

from __future__ import annotations

import argparse
import datetime as dt
import os
import shutil
import subprocess
import sys

from .batch import PLAYGROUND
from .brain import MEMORY, JOURNAL, BRANCHES

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def batch(brain: str, model: str | None, seed: int, games: int, parallel: int, no_journal: bool = False,
          conclusions: str | None = None, branches: str | None = None) -> str:
    cmd = [sys.executable, "-m", "pilot.batch", "--games", str(games), "--parallel", str(parallel), "--brain", brain,
           "--seed", str(seed), "--max-seconds", "3600"]
    if model:
        cmd += ["--model", model]
    if branches:
        cmd += ["--branches", branches]
    elif not no_journal and not conclusions:
        cmd.append("--with-conclusions")
    if conclusions:
        cmd += ["--conclusions", conclusions]
    out = subprocess.run(cmd, capture_output=True, text=True, cwd=HERE).stdout
    for line in out.splitlines():
        if line.startswith("details:"):
            return os.path.basename(line.split()[-1]).replace(".csv", "")
    raise SystemExit(f"batch failed:\n{out[-2000:]}")


def compare(a: str, b: str) -> str:
    out = subprocess.run([sys.executable, "-m", "pilot.compare", a, b], capture_output=True, text=True, cwd=HERE).stdout
    return "; ".join(l for l in out.splitlines() if l.startswith(("deepest change", "XL change")))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--brain", choices=("haiku", "qwen"), default="qwen")
    p.add_argument("--model")
    p.add_argument("--cycles", type=int, default=3)
    p.add_argument("--train-seed", type=int, default=4000)
    p.add_argument("--test-seed", type=int, default=3000)
    p.add_argument("--games", type=int, default=32, help="training batch size")
    p.add_argument("--test-games", type=int, help="test batch size (default: same as --games)")
    p.add_argument("--parallel", type=int, default=2)
    p.add_argument("--no-conclusions-run", help="an existing no-conclusions test run to compare against")
    p.add_argument("--mode", choices=("branches", "flat"), default="branches",
                   help="branches: the engine recalls matching leaves per call (default); flat: the whole file in the prompt")
    args = p.parse_args()
    tg = args.test_games or args.games

    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    log = [f"# Stratigraph efficacy ({args.mode} memory), {args.brain}{' ' + args.model if args.model else ''}: test seed {args.test_seed}, "
           f"train seed {args.train_seed}+, {args.games} training games and {tg} test games per batch", ""]
    base = args.no_conclusions_run or batch(args.brain, args.model, args.test_seed, tg, args.parallel, no_journal=True)
    log.append(f"- stratum 0 (no conclusions): test run {base}")
    def snapshot(k: int) -> dict:
        if args.mode == "branches":
            snap = os.path.join(PLAYGROUND, "batch", f"strat-{stamp}-s{k}.branches")
            shutil.copytree(BRANCHES, snap)
            return {"branches": snap}
        snap = os.path.join(PLAYGROUND, "batch", f"strat-{stamp}-s{k}.md")
        shutil.copy(JOURNAL, snap)
        return {"conclusions": snap}
    t0 = batch(args.brain, args.model, args.test_seed, tg, args.parallel, **snapshot(0))
    log.append(f"- stratum now: test run {t0}: {compare(base, t0)}")
    print("\n".join(log[-2:]), flush=True)
    for k in range(1, args.cycles + 1):
        train = batch(args.brain, args.model, args.train_seed + 100 * k, args.games, args.parallel)
        subprocess.run([sys.executable, "-m", "pilot.reflect", train], cwd=HERE, check=False)
        test = batch(args.brain, args.model, args.test_seed, tg, args.parallel, **snapshot(k))
        log.append(f"- stratum +{k}: trained on {train}, test run {test}: {compare(base, test)}")
        print(log[-1], flush=True)
    path = os.path.join(MEMORY, "events", f"{stamp}_stratigraph-efficacy-{args.brain}.md")
    with open(path, "w") as f:
        f.write(f"---\ntimestamp: {stamp}\nrun_id: {base}\nkind: design\n---\n\n" + "\n".join(log) + "\n")
    print(f"\nwrote {path}")


if __name__ == "__main__":
    main()
