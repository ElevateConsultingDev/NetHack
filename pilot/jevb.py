"""JEV judge mode: the rules pilot plays; in a fight that is going badly, Jev answers narrow
yes/no questions and code picks the move.

`python3 -m pilot.batch --brain jevb`. TypeSafe's guidance for System One models: keep control
flow and arithmetic in code, hand the model facts in words (it is no calculator), and ask
several narrow judgments in one request instead of one broad "what should I do?". So the
engine works out the numbers (rounds the pilot can survive at the current rate, rounds to kill
the enemy, steps to the stairs), turns them into words with the spoiler table's facts, and asks
three Nouls. `decide` below is the whole policy: thresholds to read and tune.

    python3 -m pilot.jevb          # offline check of the state builder and the policy
    python3 -m pilot.jevb --live   # one real call on a sample fight (needs the Keychain key)
"""

from __future__ import annotations

import sys

from .engine import DONT_MELEE, View, bfs, checks, r_elbereth, _count, _step
from .jev import JevEngine
from .spoilers import PILOT_SPEED, spoiler

QUESTIONS = {
    "lose": {
        "type": "noul",
        "instructions": "I will die in this fight if I keep attacking the enemies in `enemies_next_to_me` in melee.",
        "criteria": {"true": "At the current rate I run out of health before they are dead.",
                     "false": "I kill them first, or the fight is close enough to finish safely."},
    },
    "elbereth": {
        "type": "noul",
        "instructions": "Engraving Elbereth now, as described in `escapes.elbereth`, will stop the enemies in "
                        "`enemies_next_to_me` from hurting me.",
        "criteria": {"true": "Every enemy next to me respects Elbereth and I survive the one round it costs to write.",
                     "false": "An enemy ignores Elbereth, it has already failed here, or I die while writing it."},
    },
    "stairs": {
        "type": "noul",
        "instructions": "I will reach the stairs up alive, given `escapes.stairs_up` and `me.rounds_i_can_survive_at_this_rate`.",
        "criteria": {"true": "I am on the stairs, or close enough to get there before my health runs out.",
                     "false": "There are no stairs up in reach, or the enemies kill me on the way."},
    },
}

LOSE_AT = 0.6     # act when Jev thinks the fight is lost at least this strongly
ESCAPE_AT = 0.5   # and take an escape Jev rates at least this likely to work


def decide(answers: dict, can_elbereth: bool, can_stairs: bool) -> str:
    """The policy: 'stairs', 'elbereth', or 'rules' (leave it to the rules pilot)."""
    if answers["lose"]["noul"] < LOSE_AT:
        return "rules"
    options = [(answers[k]["noul"], k) for k, ok in (("stairs", can_stairs), ("elbereth", can_elbereth)) if ok]
    best = max(options, default=(0, "rules"))
    return best[1] if best[0] >= ESCAPE_AT else "rules"


def rounds(n: float) -> str:
    return "one" if n < 1.5 else "two" if n < 2.5 else "three or four" if n < 4.5 else "five to eight" if n < 8.5 else "many"


def health(hp: int, hpmax: int) -> str:
    f = hp / max(hpmax, 1)
    return ("most of it left" if f > 0.66 else "a little over half left" if f > 0.5 else "less than half left"
            if f > 0.33 else "under a third left" if f > 0.15 else "almost dead")


def fight_state(c: dict, loss_per_round: float, steps_up: int | None, on_elbereth_failed: bool, messages: list) -> dict:
    """The fight in words. All arithmetic happens here."""
    foes = [h for h in c["adjacent_hostiles"] if h["name"] not in DONT_MELEE]
    survive = c["hp"] / max(loss_per_round, 0.5)
    enemies, kill_rounds = [], 0.0
    for h in foes:
        sp = spoiler(h["name"])
        hit = min(0.95, max(0.25, (2 + (c["xlvl"] or 1) + sp.get("ac", 6)) / 20))  # find_roll_to_hit, roughly
        need = max(2, sp.get("level", 1) * 4.5) / (7 * hit)  # d8 hit dice against a long sword's ~7 a hit
        kill_rounds += need
        enemies.append({"name": h["name"], "faster_than_me": sp.get("speed", 12) > PILOT_SPEED,
                        "respects_elbereth": sp.get("elbereth", True),
                        "dangers": (sp.get("hazards") or []) + (sp.get("passive") or []),
                        "rounds_to_kill_it": rounds(need)})
    others = len(c["mobile_hostiles"]) - len(foes)
    if steps_up is None:
        stairs = "none known on this level"
    elif steps_up == 0:
        stairs = "I am standing on them: one move and I am away from every enemy not next to me"
    else:
        fast = any(e["faster_than_me"] for e in enemies)
        stairs = (f"{rounds(steps_up)} steps away; the enemies follow and keep attacking on the way"
                  + (", and they are faster than me" if fast else ""))
    if on_elbereth_failed:
        elbereth = "already failed: I was hit while standing on it"
    elif not all(e["respects_elbereth"] for e in enemies):
        elbereth = "useless: an enemy next to me ignores it"
    else:
        elbereth = "possible: writing it costs one round of being attacked, then enemies that respect it stop attacking"
    return {
        "me": {"health": health(c["hp"], c["hpmax"]), "rounds_i_can_survive_at_this_rate": rounds(survive),
               "armor": "poor" if (c.get("ac") or 10) >= 6 else "fair" if c["ac"] >= 3 else "good"},
        "enemies_next_to_me": enemies,
        "rounds_to_kill_all_of_them": rounds(kill_rounds),
        "other_enemies_in_view": "none" if others <= 0 else "one" if others == 1 else "several",
        "escapes": {"prayer": "not available", "stairs_up": stairs, "elbereth": elbereth},
        "recent_messages": messages[-6:],
    }


class JevJudge(JevEngine):
    def __init__(self) -> None:
        super().__init__()
        self.hp_log: list = []  # (turn, hp) at the start of the last few turns

    def _decide(self, v: View):
        if v.kind != "command" or v.engulfed or not v.pos:
            return super(JevEngine, self)._decide(v)
        m = self.memory
        c = checks(v, m)
        c["ac"] = v.status.get("ac")
        turn = c["turn"]
        if not self.hp_log or self.hp_log[-1][0] != turn:
            self.hp_log = (self.hp_log + [(turn, c["hp"])])[-3:]
        then_turn, then_hp = self.hp_log[0]
        loss = (then_hp - c["hp"]) / max(turn - then_turn, 1)
        foes = [h for h in c["adjacent_hostiles"] if h["name"] not in DONT_MELEE]

        elb = self.jev_args.get("elbereth")
        if elb:  # Resting on an Elbereth Jev chose: stay until healed, gone, or it fails.
            failed = self._hit_on_elbereth(v, c)
            keys, note = (None, "hit on it") if failed else r_elbereth(v, m, elb)
            self.prev_hp = (turn, c["hp"])
            if keys:
                self.note = "jev judge: " + note
                return self._stuck_guard(v, keys, note)
            self.jev_args.pop("elbereth")
            self.elbereth_failed_at = v.pos if failed else None

        # Ask only in a fight that is costing something, and only when prayer is not the answer.
        hurt = c["hp"] * 3 < c["hpmax"] * 2 or loss * 4 >= c["hp"]
        if not (foes and loss > 0 and hurt) or (c["major_trouble"] and c["prayer_safe"]):
            self.prev_hp = (turn, c["hp"])
            return super(JevEngine, self)._decide(v)

        up = [(x, y) for (d, x, y), n in m.features.items() if d == v.dlvl and n == "staircase up" and v.dlvl > 1]
        path = [] if v.pos in up else bfs(v, lambda x, y: (x, y) in up) if up else None
        steps = None if path is None else len(path)
        failed_here = getattr(self, "elbereth_failed_at", None) == v.pos
        state = fight_state(c, loss, steps, failed_here, [x for x in v.s.get("messages", []) if x])
        answers = self.ask(state, QUESTIONS)
        self.prev_hp = (turn, c["hp"])
        if answers is None:
            _count(m, "jev judge: api failure, rules decided")
            return super(JevEngine, self)._decide(v)
        can_elbereth = state["escapes"]["elbereth"].startswith("possible")
        action = decide(answers, can_elbereth, steps is not None)
        probs = {k: round(a["noul"], 3) for k, a in answers.items()}
        self.last_ask = (turn, state, {"choice": action, "probabilities": probs})  # for the replay page
        _count(m, f"jev judge: {action}")
        if action == "stairs":
            keys, note = ("<", "flee up the stairs") if steps == 0 else _step(v, m, path, "retreat to the stairs up")
        elif action == "elbereth":
            keys, note = r_elbereth(v, m, self.jev_args.setdefault("elbereth", {}))
        else:
            keys = None
        if keys:
            self.note = f"jev judge {action} (lose {probs['lose']:.2f}, {action} {probs[action]:.2f}): {note}"
            return self._stuck_guard(v, keys, note)
        return super(JevEngine, self)._decide(v)


SAMPLE = {"hp": 41, "hpmax": 62, "xlvl": 6, "ac": 2, "mobile_hostiles": [{}],
          "adjacent_hostiles": [{"name": "soldier ant"}]}

if __name__ == "__main__":
    st = fight_state(SAMPLE, 10.5, 9, False, ["The soldier ant bites!", "The soldier ant stings!", "You miss the soldier ant."])
    assert st["me"]["rounds_i_can_survive_at_this_rate"] == "three or four" and st["enemies_next_to_me"][0]["faster_than_me"]
    assert st["escapes"]["elbereth"].startswith("possible") and "faster" in st["escapes"]["stairs_up"]
    human = fight_state({**SAMPLE, "adjacent_hostiles": [{"name": "watchman"}]}, 5, None, False, [])
    assert human["escapes"]["elbereth"].startswith("useless") and human["escapes"]["stairs_up"].startswith("none")
    a = lambda lose, elb, up: {"lose": {"noul": lose}, "elbereth": {"noul": elb}, "stairs": {"noul": up}}
    assert decide(a(0.3, 0.9, 0.9), True, True) == "rules"       # not losing: the rules fight on
    assert decide(a(0.8, 0.7, 0.2), True, True) == "elbereth"
    assert decide(a(0.8, 0.7, 0.9), True, True) == "stairs"
    assert decide(a(0.8, 0.9, 0.9), False, False) == "rules"     # no escape exists
    assert decide(a(0.8, 0.3, 0.4), True, True) == "rules"       # no escape is likely to work
    print("jev judge ok")
    if "--live" in sys.argv:
        import json, time
        e = JevJudge()
        t = time.time()
        print(json.dumps(st, indent=1))
        ans = e.ask(st, QUESTIONS)
        print({k: round(x["noul"], 3) for k, x in ans.items()}, "->", decide(ans, True, True), f"({time.time() - t:.2f}s)")
