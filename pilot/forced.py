"""Forced replay: was there a surviving move? (docs/pilot-tactics-design.md, phase 3)

    python3 -m pilot.forced <run> [<run> ...] [--games 10] [--parallel 8] [--horizon 80]
    python3 -m pilot.forced --one <run>/<name> <tactic> <turn>     # one forced replay, printed
    python3 -m pilot.forced --check

Each melee or Mines death is replayed from the turn its last fight turned
bad (the first recorded tactic in the final 60 turns made under half HP),
once as recorded and once per alternative tactic forced at that turn:
Elbereth, the stairs up, a corridor square, prayer. The forced routine runs
with the standing orders held off; afterwards the normal engine plays on.
Alive `horizon` turns later counts as survived. Deterministic: the same
seed and the rules brain, so every difference is the forced move.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys

from .batch import PLAYGROUND, Game, prepare_playground
from .brain import RuleBrain
from .buckets import split
from .compare import load
from .engine import Engine, View, _chokepoint, bfs

TACTICS = ("elbereth", "stairs", "corridor", "pray")


class ForcedEngine(Engine):
    """The engine, with one decision forced at a turn: the first command
    prompt at or after `at` starts `tactic`; while it runs the standing
    orders stay out of the way."""

    def __init__(self, tactic: str | None, at: int) -> None:
        super().__init__()
        self.tactic, self.at = tactic, at
        self.forcing = False
        self.fired = tactic is None
        self.infeasible = ""

    def _decide(self, v: View):
        if v.kind == "command" and v.pos and (v.status.get("turn") or 0) >= self.at:
            if not self.fired:
                self.fired = True
                self.forcing = True
                self._force(v)
            if self.forcing and self.routine is None:
                self.forcing = False
        if self.forcing and self.tactic == "stairs" and v.kind == "command" and v.pos in self._up(v):
            self._end_routine()
            self.forcing = False
            self.note = "forced: up the stairs"
            return "<", []
        return super()._decide(v)

    def _standing(self, v: View, c: dict):
        return None if self.forcing else super()._standing(v, c)

    def _up(self, v: View) -> list:
        return [(x, y) for (d, x, y), n in self.memory.features.items() if d == v.dlvl and n == "staircase up"]

    def _force(self, v: View) -> None:
        if self.tactic == "elbereth":
            self.order("elbereth")
        elif self.tactic == "pray":
            if not self.order("pray"):
                self.infeasible = "prayer gate closed"
                self.forcing = False
        elif self.tactic == "stairs":
            up = self._up(v)
            path = bfs(v, lambda x, y: (x, y) in up) if up and v.pos not in up else None
            if up and v.pos in up:
                return
            if not path:
                self.infeasible = "no stairs up known or no path"
                self.forcing = False
                return
            self.order("go_to", {"x": path[-1][0], "y": path[-1][1]})
        elif self.tactic == "corridor":
            path = None if _chokepoint(v, *v.pos) else bfs(v, lambda x, y: _chokepoint(v, x, y))
            if path is None and not _chokepoint(v, *v.pos):
                self.infeasible = "no corridor square reachable"
                self.forcing = False
                return
            if path:
                self.order("go_to", {"x": path[-1][0], "y": path[-1][1]})


def bad_turn(g: dict) -> int | None:
    """The turn the final fight turned bad: the first recorded tactic within
    60 turns of the end made under half HP; else the last tactic's turn."""
    end, outs = int(g.get("turn") or 0), g.get("outcomes") or []
    late = [o for o in outs if end - o["turn"] <= 60]
    for o in late:
        if o["hp"] * 2 < o["hpmax"]:
            return o["turn"]
    return late[0]["turn"] if late else (outs[-1]["turn"] if outs else None)


def one(run: str, name: str, tactic: str | None, at: int, horizon: int = 80) -> dict:
    rec = next(g for g in load(run) if g["name"] == name)
    prepare_playground()
    engine = ForcedEngine(tactic, at)
    g = Game(f"F{(tactic or 'as')[0]}{name[2:]}", rec.get("role", "Valkyrie"), RuleBrain(), at + horizon, 900,
             save_on_stall=False, out_dir=os.path.join(PLAYGROUND, "replays"), seed=rec["seed"], engine=engine)
    r = g.play()
    turn = int(r.get("turn") or 0)
    survived = bool(r.get("stall", "").startswith("turn limit")) or turn > at + horizon
    return {"game": name, "tactic": tactic or "as recorded", "at": at, "turn": turn, "survived": survived,
            "infeasible": engine.infeasible, "end": r.get("stall") or r.get("death") or "", "hp": r.get("hp")}


def _job(a):
    return one(*a)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("runs", nargs="*")
    p.add_argument("--games", type=int, default=10)
    p.add_argument("--parallel", type=int, default=8)
    p.add_argument("--horizon", type=int, default=80)
    p.add_argument("--one", nargs=3, metavar=("RUN/NAME", "TACTIC", "TURN"))
    p.add_argument("--check", action="store_true")
    a = p.parse_args()
    if a.check:
        g = {"turn": "100", "outcomes": [{"turn": 30, "hp": 9, "hpmax": 10}, {"turn": 50, "hp": 9, "hpmax": 10},
                                         {"turn": 70, "hp": 4, "hpmax": 10}, {"turn": 99, "hp": 1, "hpmax": 10}]}
        assert bad_turn(g) == 70, bad_turn(g)
        e = ForcedEngine("pray", 5)
        assert not e.fired and not e.forcing
        print("ok")
        return
    if a.one:
        which, tactic, turn = a.one
        run, name = which.split("/")
        print(json.dumps(one(run, name, None if tactic == "as" else tactic, int(turn), a.horizon)))
        return
    games = [(r, g) for r in a.runs for g in load(r)]
    picked = []
    for bucket, gs in split(games).items():
        if bucket.startswith("died in melee") or bucket == "died in the Mines":
            picked += gs
    picked.sort(key=lambda p: int(p[1].get("maxlvl") or 0))
    picked = [(r, g, bad_turn(g)) for r, g in picked if bad_turn(g)][:a.games]
    jobs = [(r, g["name"], t, at, a.horizon) for r, g, at in picked for t in (None,) + TACTICS]
    with concurrent.futures.ProcessPoolExecutor(a.parallel) as ex:
        results = list(ex.map(_job, jobs))
    by = {}
    for x in results:
        by.setdefault(x["game"], {})[x["tactic"]] = x
    saved = 0
    print(f"{'game':10} {'at':>5} {'as recorded':12} " + " ".join(f"{t:10}" for t in TACTICS))
    for r, g, at in picked:
        row = by[g["name"]]
        cell = lambda x: ("n/a" if x["infeasible"] else "alive" if x["survived"] else f"dead T{x['turn']}")
        alts = [row[t] for t in TACTICS]
        saved += any(x["survived"] and not x["infeasible"] for x in alts) and not row["as recorded"]["survived"]
        print(f"{g['name']:10} {at:>5} {cell(row['as recorded']):12} " + " ".join(f"{cell(x):10}" for x in alts)
              + f"  dlvl {g['maxlvl']} XL {g['xlvl']} {g.get('death', '')}")
    print(f"\n{saved} of {len(picked)} deaths had a surviving forced move within {a.horizon} turns")
    for t in TACTICS:
        n = sum(1 for x in results if x["tactic"] == t and not x["infeasible"])
        s = sum(1 for x in results if x["tactic"] == t and x["survived"] and not x["infeasible"])
        print(f"  {t}: survived {s} of {n} feasible")


if __name__ == "__main__":
    main()
