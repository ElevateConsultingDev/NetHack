"""Tactics with predictions and measured outcomes (docs/pilot-tactics-design.md, phase 1).

Shadow mode: the rules pilot plays exactly as before. Each command prompt, `Tracker.observe`
reads which fight-or-escape tactic the engine just chose (from its note), attaches that
tactic's prediction, and measures it against the following snapshots. Outcomes go into the
game's record (`outcomes`), where `pilot.ledger` counts them.

    tactic     prediction                                       budget
    melee      the target dies                                  10 turns
    throw      the target dies                                   4 turns
    elbereth   no HP lost once it is written                     6 turns (the first is the cost)
    stairs     off this level                                   14 turns
    corridor   at most one hostile adjacent                      8 turns
    pray       the trouble is gone (HP back over half)           4 turns
    back_off   nothing hostile adjacent                          4 turns

Statuses: met, not_met, unknown (the evidence went away: the target left view),
ended_early (another tactic replaced it before its budget, with nothing decisive).
`menu` records what else was feasible at the start, and `omitted` why the rest was not: the
input for forced replay (phase 3).

    python3 -m pilot.tactics    # self-check
"""

from __future__ import annotations

import re

from .spoilers import spoiler

BUDGET = {"melee": 10, "throw": 4, "elbereth": 6, "stairs": 14, "corridor": 8, "pray": 4, "back_off": 4}
NOTES = [  # (tactic, pattern on the engine's note); first match wins
    ("pray", re.compile(r"standing order: pray")),
    ("stairs", re.compile(r"flee up the stairs|retreat to the stairs|flee by the stairs")),
    ("corridor", re.compile(r"retreat into a corridor|back into a corridor")),
    ("throw", re.compile(r"throw \w at the (?P<target>[\w' -]+)")),
    ("elbereth", re.compile(r"engrave Elbereth|rest on Elbereth")),
    ("back_off", re.compile(r"back off from the (?P<target>[\w' -]+?)(?: before| $|$)")),
    ("melee", re.compile(r"fight (?:it with the weapon|the (?P<target>[\w' -]+))|cornered by the (?P<t2>[\w' -]+): fight|hit back at")),
]
KILLED = re.compile(r"You (?:kill|destroy) (?:the |poor )?(?P<name>[\w' -]+?)!")


def classify(note: str) -> tuple[str, str] | None:
    """(tactic, target name or '') for the engine's note, or None when it is not a fight-or-escape tactic."""
    for tactic, pat in NOTES:
        m = pat.search(note or "")
        if m:
            g = m.groupdict()
            return tactic, (g.get("target") or g.get("t2") or "").strip()
    return None


def menu(c: dict, feasible: dict) -> tuple[list, list]:
    """What could have been chosen, and what was withheld and why. `feasible` maps a tactic to
    True or to the reason it is not on offer."""
    offered = [t for t, ok in feasible.items() if ok is True]
    omitted = [{"id": t, "reason": ok} for t, ok in feasible.items() if ok is not True]
    return offered, omitted


class Tracker:
    def __init__(self) -> None:
        self.outcomes: list = []
        self.open: dict | None = None

    def observe(self, turn: int, dlvl: int, c: dict, note: str, messages: list, feasible: dict | None = None) -> None:
        """One command prompt: measure the open tactic, then start or continue from this turn's note."""
        got = classify(note)
        o = self.open
        if o:
            status = self._measure(o, turn, dlvl, c, messages)
            same = got and got[0] == o["tactic"] and (not got[1] or not o["target"] or got[1] == o["target"])
            if status:
                self._close(o, status, turn, c)
            elif not same and (got or turn - o["turn"] >= 1):
                # Replaced by another tactic, or the engine went back to its default activity.
                self._close(o, "ended_early", turn, c)
        if got and not self.open:
            tactic, target = got
            adjacent = c.get("adjacent_hostiles") or []
            target = target or (adjacent[0]["name"] if adjacent else "")
            offered, omitted = menu(c, feasible or {})
            sp = spoiler(target)
            self.open = {"tactic": tactic, "target": target, "turn": turn, "dlvl": dlvl, "hp": c["hp"], "hpmax": c["hpmax"],
                         "xl": c.get("xlvl"), "adjacent": len(adjacent), "in_view": len(c.get("mobile_hostiles") or []),
                         "symbol": sp.get("symbol", "?"), "fast": sp.get("speed", 12) > 12,
                         "low": c["hp"], "menu": offered, "omitted": omitted}
        elif self.open:
            self.open["low"] = min(self.open["low"], c["hp"])

    def _measure(self, o: dict, turn: int, dlvl: int, c: dict, messages: list) -> str | None:
        t, age = o["tactic"], turn - o["turn"]
        text = " ".join(messages)
        adjacent = c.get("adjacent_hostiles") or []
        names = {h["name"] for h in (c.get("visible_hostiles") or [])}
        if t in ("melee", "throw"):
            if any(m.group("name") == o["target"] or not o["target"] for m in KILLED.finditer(text)):
                return "met"
            if o["target"] and o["target"] not in names and age >= 1:
                return "unknown"  # It left view: gone is not dead.
        elif t == "elbereth":
            if age >= 1:
                o.setdefault("after_writing", c["hp"]) if age == 1 else None
                if c["hp"] < o.get("after_writing", c["hp"]):
                    return "not_met"
                o["after_writing"] = max(o.get("after_writing", c["hp"]), c["hp"])
        elif t == "stairs" and dlvl != o["dlvl"]:
            return "met"
        elif t == "corridor" and age >= 1 and len(adjacent) <= 1 and c.get("in_chokepoint"):
            return "met"
        elif t == "pray" and age >= 1 and c["hp"] * 2 >= c["hpmax"]:
            return "met"
        elif t == "back_off" and age >= 1 and not adjacent:
            return "met"
        if age >= BUDGET[t]:
            return "met" if t == "elbereth" else "not_met"
        return None

    def _close(self, o: dict, status: str, turn: int, c: dict) -> None:
        o.update(status=status, turns=turn - o["turn"], hp_end=c["hp"])
        o.pop("after_writing", None)
        self.outcomes.append(o)
        self.open = None

    def finish(self, died: bool, turn: int, hp: int = 0) -> list:
        """Game over: a tactic still open when the pilot died did not come true."""
        if self.open:
            self._close(self.open, "not_met" if died else "ended_early", turn, {"hp": 0 if died else hp})
        return self.outcomes


if __name__ == "__main__":
    assert classify("standing order: fight the soldier ant") == ("melee", "soldier ant")
    assert classify("standing order: throw b at the floating eye") == ("throw", "floating eye")
    assert classify("rest on Elbereth (HP 12/40)") == ("elbereth", "")
    assert classify("standing order: flee up the stairs (hurt, outnumbered)") == ("stairs", "")
    assert classify("standing order: back off from the cockatrice") == ("back_off", "cockatrice")
    assert classify("explore: explore toward (3, 4)") is None
    ant = [{"name": "soldier ant"}]
    c = lambda hp, adj=ant: {"hp": hp, "hpmax": 60, "xlvl": 6, "adjacent_hostiles": adj, "visible_hostiles": adj, "mobile_hostiles": adj}
    t = Tracker()
    t.observe(100, 7, c(50), "standing order: fight the soldier ant", [], {"melee": True, "pray": "prayer gate closed"})
    t.observe(101, 7, c(41), "standing order: fight the soldier ant", ["You miss the soldier ant."])
    t.observe(102, 7, c(35, []), "explore: explore toward (1, 1)", ["You kill the soldier ant!"])
    assert [(o["tactic"], o["status"], o["turns"], o["low"]) for o in t.outcomes] == [("melee", "met", 2, 41)], t.outcomes
    assert t.outcomes[0]["menu"] == ["melee"] and t.outcomes[0]["omitted"][0]["id"] == "pray" and t.outcomes[0]["fast"]
    t.observe(200, 7, c(20), "engrave Elbereth", [])
    t.observe(201, 7, c(14), "rest on Elbereth (HP 14/60)", [])      # the round it costs to write
    t.observe(206, 7, c(16), "rest on Elbereth (HP 16/60)", [])
    t.observe(207, 7, c(18), "rest on Elbereth (HP 18/60)", [])
    assert t.outcomes[-1]["tactic"] == "elbereth" and t.outcomes[-1]["status"] == "met", t.outcomes[-1]
    t.observe(300, 7, c(20), "engrave Elbereth", [])
    t.observe(301, 7, c(14), "rest on Elbereth (HP 14/60)", [])
    t.observe(302, 7, c(9), "rest on Elbereth (HP 9/60)", [])        # hit while standing on it
    assert t.outcomes[-1]["status"] == "not_met"
    t.observe(400, 7, c(30), "standing order: fight the soldier ant", [])
    assert t.finish(True, 401)[-1]["status"] == "not_met"
    print("tactics ok")
