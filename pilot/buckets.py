"""Why the pilot fails: the failure split the loop's Review reads.

    python3 -m pilot.buckets <run> [<run> ...]          # buckets, killers, worst games to drill
    python3 -m pilot.buckets --deaths <run> [<run> ...] # each melee or Mines death: the last tactic
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


def deaths(games: list[tuple[str, dict]]) -> str:
    """Each death in melee or the Mines with the last recorded tactic before
    it: how long before death it started, the pilot's HP then, what else was
    on the menu. Then the totals the TRY tasks lean on: lost by choice (an
    escape was feasible) against lost unready (XL two or more behind the
    level)."""
    rows, by_tactic, escape, unready, low = [], collections.Counter(), 0, 0, 0
    for run, g in games:
        if not g["bucket"].startswith("died in melee") and g["bucket"] != "died in the Mines":
            continue
        end, outs = int(g.get("turn") or 0), g.get("outcomes") or []
        o = outs[-1] if outs else None
        xl, dlvl = int(g.get("xlvl") or 0), int(g.get("dlvl") or 0)
        behind = dlvl - xl >= 2
        unready += behind
        if o is None:
            rows.append(f"  {g['name']} dlvl {dlvl:>2} XL {xl:>2} {g.get('death', '')[:28]:28} no tactic recorded")
            continue
        frac = o["hp"] / max(o["hpmax"], 1)
        others = [m for m in o["menu"] if m != o["tactic"]]
        by_tactic[o["tactic"]] += 1
        esc = any(m in others for m in ("elbereth", "stairs", "pray"))
        escape += esc and o["tactic"] == "melee"
        low += frac < 0.34 and o["tactic"] == "melee"
        rows.append(f"  {g['name']} dlvl {dlvl:>2} XL {xl:>2} {g.get('death', '')[:28]:28} {o['tactic']:8} "
                    f"{end - o['turn']:>4}t before, HP {int(100 * frac):>3}%, also: {', '.join(others) or 'nothing'}"
                    + ("  XL behind" if behind else ""))
    n = len(rows) or 1
    head = [f"{len(rows)} deaths in melee or the Mines; last tactic: "
            + ", ".join(f"{t} {c}" for t, c in by_tactic.most_common()),
            f"  melee with an escape (Elbereth, stairs or prayer) on the menu: {escape} ({100 * escape // n}%)",
            f"  melee started under a third HP: {low}",
            f"  XL two or more behind the level: {unready} ({100 * unready // n}%)"]
    return "\n".join(head + rows)


def check() -> None:
    games = [("r", {"bucket": "a", "maxlvl": "3", "turn": "9"}),
             ("r", {"bucket": "b", "maxlvl": "1", "turn": "5"}),
             ("r", {"bucket": "a", "maxlvl": "1", "turn": "7"})]
    s = split(games)
    assert list(s) == ["a", "b"], s                   # biggest bucket first
    assert s["a"][0][1]["maxlvl"] == "1", s["a"]      # shallowest game first
    g = {"name": "X", "bucket": "died in the Mines", "turn": "50", "xlvl": "2", "dlvl": "5", "death": "killed by an ant",
         "outcomes": [{"tactic": "melee", "turn": 45, "hp": 5, "hpmax": 20, "menu": ["melee", "elbereth"]}]}
    t = deaths([("r", g)])
    assert "escape (Elbereth, stairs or prayer) on the menu: 1" in t and "XL behind" in t, t
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
    elif sys.argv[1:2] == ["--deaths"]:
        print(deaths([(r, g) for r in sys.argv[2:] for g in load(r)]))
    elif len(sys.argv) > 1:
        print(report(sys.argv[1:]))
    else:
        print(__doc__)
