"""Danger table: how often a melee against a monster, at a given level gap, ends in death.

    python3 -m pilot.danger [runs...]      # default: every plain rules run of seeds 1000 and 5000
    python3 -m pilot.danger --check

Reads the tactic outcomes (pilot.ledger.rows): each melee start, the monster, the pilot's XL,
and whether the pilot was dead within 20 turns. Groups by (monster, gap band), where the gap is
the monster's difficulty minus the pilot's XL: "<=0", "1-2", "3+". Writes pilot/danger.json with
tries, deaths, the rate and a Wilson lower bound (95%), so a rarely seen monster is not judged on
two unlucky fights. Held-out seeds (6000 and up) are never read: the table must not learn them.
"""

from __future__ import annotations

import collections
import glob
import json
import math
import os
import sys

from .ledger import rows
from .spoilers import spoiler

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "danger.json")


def band(gap: int) -> str:
    return "<=0" if gap <= 0 else "1-2" if gap <= 2 else "3+"


def wilson_low(k: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    p = k / n
    centre = p + z * z / (2 * n)
    spread = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return max(0.0, (centre - spread) / (1 + z * z / n))


def fights(outcomes: list[dict]) -> list[dict]:
    """One row per fight: a losing fight is re-decided every turn, so the tracker records many
    melee starts for it, all marked dead. Melee outcomes against the same monster in the same
    game less than 20 turns apart are one fight; it counts as a death if any of them does, at
    the gap of its first outcome."""
    out, last = [], {}
    for o in sorted((o for o in outcomes if o.get("tactic") == "melee" and o.get("target")),
                    key=lambda o: (o.get("game", ""), o["target"], o["turn"])):
        k = (o.get("game", ""), o["target"])
        f = last.get(k)
        if f and o["turn"] - f["end"] < 20:
            f["end"], f["dead20"] = o["turn"], f["dead20"] or bool(o.get("dead20"))
        else:
            f = {"target": o["target"], "xl": o.get("xl") or 1, "end": o["turn"], "dead20": bool(o.get("dead20"))}
            last[k] = f
            out.append(f)
    return out


def table(outcomes: list[dict]) -> dict:
    count = collections.defaultdict(lambda: [0, 0])
    for o in fights(outcomes):
        diff = spoiler(o["target"]).get("difficulty")
        if diff is None:
            continue
        c = count[f"{o['target']}|{band(diff - o['xl'])}"]
        c[0] += 1
        c[1] += o["dead20"]
    return {k: {"tries": n, "deaths": d, "rate": round(d / n, 3), "low": round(wilson_low(d, n), 3)}
            for k, (n, d) in sorted(count.items())}


def default_runs() -> list[str]:
    out = []
    for f in sorted(glob.glob(os.path.join(HERE, "..", "playground", "batch", "2026*.json"))):
        if "summary" in f:
            continue
        try:
            d = json.load(open(f))
        except (OSError, ValueError):
            continue
        if d.get("brain") == "rules" and d.get("seed") in (1000, 5000) and not d.get("orders") and not d.get("env") \
                and d.get("games") and "outcomes" in d["games"][0]:
            out.append(os.path.basename(f)[:-5])
    return out


def check() -> None:
    assert band(0) == "<=0" and band(2) == "1-2" and band(5) == "3+"
    assert wilson_low(0, 10) == 0.0 and 0.0 < wilson_low(5, 10) < 0.5 < wilson_low(9, 10)
    t = table([{"tactic": "melee", "target": "soldier ant", "xl": 3, "dead20": False, "game": "g1", "turn": 100},
               {"tactic": "melee", "target": "soldier ant", "xl": 3, "dead20": True, "game": "g2", "turn": 50},
               {"tactic": "melee", "target": "soldier ant", "xl": 3, "dead20": True, "game": "g2", "turn": 55},
               {"tactic": "throw", "target": "soldier ant", "xl": 3, "dead20": True, "game": "g3", "turn": 9}])
    assert t["soldier ant|3+"]["tries"] == 2 and t["soldier ant|3+"]["deaths"] == 1, t  # g2 is one fight
    print("ok")


def main() -> None:
    if sys.argv[1:] == ["--check"]:
        check()
        return
    runs = sys.argv[1:] or default_runs()
    t = table(rows(runs))
    with open(OUT, "w") as f:
        json.dump({"runs": len(runs), "table": t}, f, indent=1, sort_keys=True)
    worst = sorted(t.items(), key=lambda kv: -kv[1]["low"])[:20]
    print(f"{len(runs)} runs, {sum(v['tries'] for v in t.values())} fights, {len(t)} (monster, gap) rows -> {OUT}")
    for k, v in worst:
        print(f"  {k:32} tries {v['tries']:5}  deaths {v['deaths']:4}  rate {v['rate']:.2f}  low {v['low']:.2f}")


if __name__ == "__main__":
    main()
