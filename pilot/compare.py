"""Compare two batch runs game by game (same --seed: same dungeons).

    python3 -m pilot.compare <run_a> <run_b>

SAME means every key matched (the change never touched that game).
"""

from __future__ import annotations

import collections
import json
import os
import statistics
import sys

from .batch import PLAYGROUND


def load(run: str) -> list[dict]:
    with open(os.path.join(PLAYGROUND, "batch", f"{run}.json")) as f:
        return json.load(f)["games"]


def summary(games: list[dict]) -> str:
    n = len(games) or 1
    avg = lambda k: sum(float(g.get(k) or 0) for g in games) / n
    buckets = collections.Counter(g["bucket"] for g in games)
    return (f"deepest {avg('maxlvl'):.2f}  XL {avg('xlvl'):.2f}  turns {avg('turn'):.0f}  "
            + ", ".join(f"{k} {v}" for k, v in buckets.most_common()))


def main() -> None:
    a, b = load(sys.argv[1]), load(sys.argv[2])
    print("before", summary(a))
    print("after ", summary(b))
    after = {g["name"][-2:]: g for g in b}
    # Game by game on the same seeds: the mean difference and its standard
    # error say whether a change is real or noise (|diff| < 2 SE: noise).
    pairs = [(float(g.get("maxlvl") or 0), float(after[g["name"][-2:]].get("maxlvl") or 0),
              float(g.get("xlvl") or 0), float(after[g["name"][-2:]].get("xlvl") or 0))
             for g in a if g["name"][-2:] in after]
    for label, i in (("deepest", 0), ("XL", 2)):
        d = [p[i + 1] - p[i] for p in pairs]
        if len(d) > 1:
            mean, se = statistics.mean(d), statistics.stdev(d) / len(d) ** 0.5
            verdict = "real" if abs(mean) >= 2 * se and se > 0 else "noise"
            print(f"{label} change {mean:+.2f} +/- {se:.2f} (n={len(d)}, better {sum(x > 0 for x in d)}, "
                  f"worse {sum(x < 0 for x in d)}): {verdict}")
    for g in a:
        h = after.get(g["name"][-2:])
        if h is None:
            continue
        same = g.get("keys") == h.get("keys")
        print(f"{g['name'][-2:]} {'SAME' if same else 'diff'} {g['bucket'][:22]:22} max{g['maxlvl']} T{g['turn']:>5}"
              f" -> {h['bucket'][:22]:22} max{h['maxlvl']} T{h['turn']:>5}"
              + ("" if same else "  " + (h.get("death") or h.get("stall") or "")[:40]))


if __name__ == "__main__":
    main()
