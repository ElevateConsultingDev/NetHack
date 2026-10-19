"""Sweep: many standing-order or flag variants on one seed set, ranked against a baseline.

    python3 -m pilot.sweep '<json list>' --base RUN [--seed 1000] [--games 128] [--name NAME]
    python3 -m pilot.sweep --base RUN --runs 'label=RUN,label=RUN' [--name NAME]   # table from finished runs
    python3 -m pilot.sweep --check

Each list item is {"label": "...", "orders": {...}, "env": {...}} (orders and env optional).
Each variant is one `pilot.batch` run on the same seeds as the baseline, so games pair by index.
Prints a table sorted by depth gain (mean and SE), XL change and bucket counts, and writes
playground/batch/sweep-NAME.json. A SWEEP sends at most its best two to the full pair.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import subprocess
import sys
import time

from .batch import PLAYGROUND
from .compare import diffs, load, mean_se

BATCH = os.path.join(PLAYGROUND, "batch")


def command(v: dict, seed: int, games: int) -> list[str]:
    cmd = [sys.executable, "-m", "pilot.batch", "--brain", "rules", "--seed", str(seed),
           "--games", str(games), "--parallel", "16"]
    if v.get("orders"):
        cmd += ["--orders", json.dumps(v["orders"])]
    if v.get("env"):
        cmd += ["--env", json.dumps(v["env"])]
    return cmd


def newest_run(after: float) -> str | None:
    runs = [f[:-5] for f in os.listdir(BATCH) if f.startswith("2026") and f.endswith(".json")
            and "summary" not in f and os.path.getmtime(os.path.join(BATCH, f)) >= after]
    return max(runs) if runs else None


def row(label: str, base: list[dict], cand: list[dict]) -> dict:
    (dm, ds), (xm, xs) = mean_se(diffs(base, cand, "maxlvl")), mean_se(diffs(base, cand, "xlvl"))
    buckets = collections.Counter(g["bucket"] for g in cand)
    return {"label": label, "depth": dm, "depth_se": ds, "xl": xm, "xl_se": xs,
            "timeouts": sum(1 for g in cand if str(g.get("stall") or "").startswith("time limit")),
            "buckets": dict(buckets.most_common(4))}


def table(rows: list[dict]) -> str:
    out = [f"{'variant':34} {'deepest':>15} {'XL':>13}  buckets"]
    for r in sorted(rows, key=lambda r: -r["depth"]):
        b = ", ".join(f"{k.replace('died in ', '').replace('stall: ', '')} {v}" for k, v in r["buckets"].items())
        out.append(f"{r['label'][:34]:34} {r['depth']:+.2f} +/- {r['depth_se']:.2f} {r['xl']:+.2f} +/- {r['xl_se']:.2f}  {b}"
                   + (f"  TIMEOUTS {r['timeouts']}" if r["timeouts"] else ""))
    return "\n".join(out)


def check() -> None:
    cmd = command({"orders": {"rest_below": 0.65}, "env": {"PILOT_X": "1"}}, 1000, 128)
    assert cmd[cmd.index("--orders") + 1] == '{"rest_below": 0.65}' and "--env" in cmd and "128" in cmd, cmd
    mk = lambda d: [{"name": f"B000000{i:02d}", "maxlvl": x, "xlvl": 5, "bucket": "died in melee/other"} for i, x in enumerate(d)]
    r = row("up", mk([5] * 10), mk([6] * 5 + [5] * 5))
    assert abs(r["depth"] - 0.5) < 1e-9 and r["timeouts"] == 0, r
    assert table([r]).splitlines()[1].startswith("up"), table([r])
    print("ok")


def main() -> None:
    if sys.argv[1:] == ["--check"]:
        check()
        return
    p = argparse.ArgumentParser()
    p.add_argument("variants", nargs="?")
    p.add_argument("--runs", help="label=RUN,label=RUN: tabulate finished runs instead of launching batches")
    p.add_argument("--base", required=True, help="baseline run on the same seed and game count")
    p.add_argument("--seed", type=int, default=1000)
    p.add_argument("--games", type=int, default=128)
    p.add_argument("--name", default=time.strftime("%H%M%S"))
    a = p.parse_args()
    base = load(a.base)
    rows = []
    if a.runs:  # The loop runs each variant in the foreground itself, then tabulates.
        for item in a.runs.split(","):
            label, run = item.rsplit("=", 1)
            r = row(label, base, load(run))
            r["run"] = run
            rows.append(r)
        with open(os.path.join(BATCH, f"sweep-{a.name}.json"), "w") as f:
            json.dump({"base": a.base, "rows": rows}, f, indent=1)
        print(table(rows))
        return
    variants = json.loads(a.variants)
    env = dict(os.environ, PYTHONHASHSEED="0")
    for v in variants:
        label = v.get("label") or json.dumps({**v.get("orders", {}), **v.get("env", {})})
        started = time.time()
        subprocess.run(command(v, a.seed, a.games), env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        run = newest_run(started)
        r = row(label, base, load(run))
        r["run"] = run
        rows.append(r)
        print(f"{label}: {run} deepest {r['depth']:+.2f} +/- {r['depth_se']:.2f}", flush=True)
    with open(os.path.join(BATCH, f"sweep-{a.name}.json"), "w") as f:
        json.dump({"base": a.base, "seed": a.seed, "games": a.games, "rows": rows}, f, indent=1)
    print(table(rows))


if __name__ == "__main__":
    main()
