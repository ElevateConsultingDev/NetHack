"""Why the pilot fails: the failure split the loop's Review reads.

    python3 -m pilot.buckets <run> [<run> ...]          # buckets, killers, worst games to drill
    python3 -m pilot.buckets --check                    # self-check

For each bucket (died in the Mines, stall: no way on, ...) it prints the
count across the runs, the killers inside it, and the games to look at
first (shallowest, since a shallow loss cost the most levels), each with
its replay command and page.
"""

from __future__ import annotations

import collections
import os
import sys

from .batch import PLAYGROUND
from .compare import load

DRILL = 3   # games shown per bucket


def split(games: list[tuple[str, dict]]) -> dict[str, list[tuple[str, dict]]]:
    """Games grouped by bucket, shallowest first."""
    by = collections.defaultdict(list)
    for run, g in games:
        by[g["bucket"]].append((run, g))
    for v in by.values():
        v.sort(key=lambda p: (int(p[1].get("maxlvl") or 0), int(p[1].get("turn") or 0)))
    return dict(sorted(by.items(), key=lambda kv: -len(kv[1])))


def report(runs: list[str]) -> str:
    games = [(r, g) for r in runs for g in load(r)]
    n = len(games) or 1
    avg = lambda k: sum(float(g.get(k) or 0) for _, g in games) / n
    out = [f"{len(games)} games in {', '.join(runs)}: deepest {avg('maxlvl'):.2f}  XL {avg('xlvl'):.2f}"]
    for bucket, gs in split(games).items():
        out.append(f"\n{bucket}: {len(gs)} ({100 * len(gs) // n}%)")
        causes = collections.Counter((g.get("death") or g.get("stall") or "?")[:40] for _, g in gs)
        out.append("  " + "; ".join(f"{c} x{k}" for c, k in causes.most_common(5)))
        for run, g in gs[:DRILL]:
            out.append(f"  dlvl {g['maxlvl']:>2} XL {g['xlvl']:>2} T{g['turn']:>6}  "
                       f"python3 -m pilot.batch --replay {run}/{g['name']}  "
                       f"{os.path.join(PLAYGROUND, 'batch', 'replay-' + g['name'] + '.html')}")
    return "\n".join(out)


def check() -> None:
    games = [("r", {"bucket": "a", "maxlvl": "3", "turn": "9"}),
             ("r", {"bucket": "b", "maxlvl": "1", "turn": "5"}),
             ("r", {"bucket": "a", "maxlvl": "1", "turn": "7"})]
    s = split(games)
    assert list(s) == ["a", "b"], s                   # biggest bucket first
    assert s["a"][0][1]["maxlvl"] == "1", s["a"]      # shallowest game first
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif len(sys.argv) > 1:
        print(report(sys.argv[1:]))
    else:
        print(__doc__)
