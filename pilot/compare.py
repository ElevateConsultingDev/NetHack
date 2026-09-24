"""Compare two batch runs game by game (same --seed: same dungeons).

    python3 -m pilot.compare <run_a> <run_b>

SAME means every key matched (the change never touched that game).
"""

from __future__ import annotations

import collections
import json
import os
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
