"""JEV mode: TypeSafe's Jev (a System One model) picks the pilot's action every turn.

An alternative to the rule engine's standing orders and default activity,
not a replacement: `python3 -m pilot.batch --brain jev`. Each command
prompt, the engine builds a compact JSON state of what the rules look at
(health, hunger, prayer gate, threats, what the level offers) and asks
Jev one Choice question whose options are the engine's actions, each
described with what the autopsies taught us about when it is right. The
engine then carries the action out with its existing routines (path
finding, prompts, throws, prayers). Hard safety rules stay in code: no
unsafe prayer, no melee on the never-melee list, no resting under
attack, no shop looting, no kicking doors near the watch.

The API key is the Keychain entry typesafe/jev (account elevate).
"""

from __future__ import annotations

import json
import subprocess
import time

import httpx

from .brain import RuleBrain
from .engine import (DONT_MELEE, KEY_FOR, ORTHO, SESSILE, Engine, View, bfs, checks, in_line, r_elbereth, r_explore,
                     r_go_down, r_loot, r_pray, r_probe_dark, r_search_walls, r_step_away, r_throw, throwable,
                     _count, _step)

URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-latest"
TIMEOUT_S = 20

ACTIONS = {
    "pray": "Pray to the god. Right only when `prayer.safe` is true and `prayer.trouble` is not empty "
            "(HP critical: 5 or less, or under a seventh of maximum; Weak from hunger with no food; stoning, "
            "sliming, strangling, sickness, lycanthropy). An unsafe prayer angers the god for the rest of the game.",
    "fight": "Melee the adjacent hostile with the wielded weapon. Right for an adjacent hostile whose difficulty is "
             "at most `threats.difficulty_limit`, and for any adjacent hostile when backing off is impossible. "
             "Never for one marked never_melee (a floating eye paralyses, a cockatrice stones, molds and jellies burn).",
    "throw": "Throw a dagger at `options.can_throw_at`. Right for a floating eye, acid blob, gas spore or yellow light "
             "in line, and for a stationary monster sitting on the stairs down or in a doorway.",
    "elbereth": "Engrave Elbereth in the dust and rest on it. Right when badly hurt (under about a third of maximum HP) "
                "with a hostile adjacent, or when something unseen is hitting the pilot, and prayer is not safe. "
                "Useless against humans (@), minotaurs and shopkeepers; attacking from the square erases it. If "
                "`threats.hit_while_on_elbereth` is true the engraving has failed: do not rest on it again, fight or pray.",
    "back_off": "Step one square away from the nearest hostile. Right next to a cockatrice, next to a gas spore about "
                "to explode, or to pull a single enemy into a corridor before fighting.",
    "eat": "Eat safe food from the pack, or the fresh corpse of a safe species the pilot just killed. Right when Hungry "
           "or Weak and `options.safe_food_in_pack` is above zero, or when `options.fresh_safe_corpse_nearby` and the "
           "pilot is not Satiated. Never corpses of unknown age, never unknown eggs.",
    "rest": "Search in place for twenty turns to recover HP. Right when HP is under half, nothing hostile that can move "
            "is in view, and nothing unseen is hitting the pilot. Stationary molds in view do not matter. Never when "
            "Weak or Fainting from hunger: resting does not feed you.",
    "wear": "Put on `options.armor_to_wear`. Right when armor for an empty slot is in the pack and no hostile is in view.",
    "loot": "Walk to a visible object and pick it up: gold, scrolls, potions, wands, rings, amulets, books, tools, food. "
            "Never items in a shop while the shopkeeper is around.",
    "explore": "Walk toward unexplored map, opening doors (kicking locked ones only where the Minetown watch has not "
               "been seen). The default while `options.level_explored` is false and nothing is urgent. Never with a "
               "hostile adjacent and HP low: walking away from a fight at 5 HP is how a pilot dies.",
    "probe": "Feel around dark areas by stepping into blank squares next to where the pilot has stood. Dark rooms and "
             "corridors stay blank until walked, so this is the first thing to do whenever `options.level_explored` is true, "
             "the stairs down are not known, and `options.probe_spots_remain` is true. Comes before search.",
    "search": "Search walls and dead ends for hidden doors and corridors. Right only when the level is fully explored, "
              "`options.probe_spots_remain` is false, the stairs down are not known, and `options.unsearched_spots_remain` "
              "is true. Never while the stairs down are known.",
    "go_down": "Walk to the known stairs down and descend. Right when `options.stairs_down_known` and the level is "
               "explored, and always when Weak or Fainting with no food and the stairs are known: a fresh level has "
               "fresh kills to eat. Each level deeper brings monsters about one level harder; experience level plus "
               "two is comfortable.",
    "go_up": "Walk to the stairs up and climb. Right only in the Gnomish Mines (`options.in_gnomish_mines`) below "
             "experience level 8 for anyone but a dwarf or gnome, or to flee a fight the pilot is losing. Anywhere else it "
             "undoes progress: the goal is depth.",
}

QUESTIONS = {
    "action": {
        "type": "choice",
        "instructions": "Choose the pilot's next action in NetHack from `pilot`, `prayer`, `threats` and `options`. "
                        "The goal is to get as deep into the dungeon as possible without dying: survive first, "
                        "keep fed, pick up what helps, clear the level, then descend.",
        "criteria": ACTIONS,
    },
}


def _api_key() -> str:
    return subprocess.run(["security", "find-generic-password", "-a", "elevate", "-s", "typesafe/jev", "-w"],
                          capture_output=True, text=True, check=True).stdout.strip()


class JevFallback(RuleBrain):
    """Answers the rare escalation Jev mode still raises (prompts); names the run."""
    name = "jev"


class JevEngine(Engine):
    def __init__(self) -> None:
        super().__init__()
        self.key = _api_key()
        self.client = httpx.Client(timeout=TIMEOUT_S)
        self.jev_args: dict[str, dict] = {}
        self.calls, self.seconds, self.failures = 0, 0.0, 0
        self.last_ask = None
        self.prev_hp: tuple = (None, None)  # (turn, hp) of the previous command prompt
        self.loot_quiet_until = 0           # turn until which loot is reported absent (a loot just failed)

    # ---------- state ----------
    def _state(self, v: View, c: dict) -> dict:
        st, m = v.status, self.memory
        inv = v.s.get("inventory", [])
        hostiles = c.get("visible_hostiles") or []
        adjacent = c.get("adjacent_hostiles") or []
        limit = self.orders["fight_up_to"] if self.orders["fight_up_to"] is not None else (c["xlvl"] or 1) + 2
        target = None
        if throwable(v):
            for mon in hostiles:
                if mon["distance"] <= 8 and in_line(v.pos, (mon["x"], mon["y"])):
                    target = mon["name"]
                    break
        corpse = self._corpse_to_eat(v, c) if not hostiles else None
        armor = None
        worn = {i["text"] for i in inv if i.get("worn")}
        for i in inv:
            if i["class"] == "[" and not i.get("worn") and i["text"] not in m.tried_wear \
                    and "cursed" not in i["text"].replace("uncursed", ""):
                armor = i["text"]
                break
        probe_spots = any(v.unknown(x + dx, y + dy) and (v.dlvl, x + dx, y + dy) not in m.probed
                          for (d, x, y) in m.visited if d == v.dlvl for dx, dy in ORTHO)
        loot_in_view = c["turn"] >= self.loot_quiet_until and any(
            cell["kind"] == "object" and cell["name"] not in ("boulder", "corpse")
            and (v.dlvl, x, y) not in m.shop_items for (x, y), cell in v.cells.items())
        return {
            "pilot": {"hp": c["hp"], "hp_max": c["hpmax"], "wounded": c["wounded"] or "fine", "experience_level": c["xlvl"],
                      "armor_class": st.get("ac"), "dungeon_level": v.dlvl, "dungeon": st.get("dungeon"),
                      "turn": c["turn"], "hunger": c["hunger"] or "not hungry", "conditions": st.get("conditions", []),
                      "encumbrance": st.get("encumbrance") or "none", "engulfed": bool(v.engulfed),
                      "worn": sorted(worn)},
            "prayer": {"safe": bool(c["prayer_safe"]), "opens_in_turns": c["prayer_opens_in"],
                       "trouble": c["major_trouble"]},
            "threats": {"adjacent": [{"name": h["name"], "difficulty": h["difficulty"], "never_melee": h["name"] in DONT_MELEE}
                                     for h in adjacent],
                        "in_view": [{"name": h["name"], "distance": h["distance"], "difficulty": h["difficulty"],
                                     "stationary": h["name"] in SESSILE} for h in hostiles[:8]],
                        "attacked_by_something_unseen": bool(c["under_attack"]),
                        "hit_while_on_elbereth": self._hit_on_elbereth(v, c),
                        "hp_dropped_this_turn": self._hit(c),
                        "difficulty_limit": limit,
                        "shopkeeper_in_view": any(cell["kind"] == "monster" and cell["name"] == "shopkeeper" for cell in v.cells.values()),
                        "watch_seen_on_level": v.dlvl in m.watch},
            "options": {"safe_food_in_pack": len(c["safe_food"]), "fresh_safe_corpse_nearby": corpse is not None,
                        "can_throw_at": target, "armor_to_wear": armor, "stairs_down_known": c["stairs_down"] is not None,
                        "on_stairs_down": bool(c["on_stairs_down"]), "level_explored": bool(c["level_explored"]),
                        "unsearched_spots_remain": v.dlvl not in m.searched_out, "probe_spots_remain": probe_spots,
                        "in_gnomish_mines": st.get("dungeon") == "The Gnomish Mines",
                        "loot_in_view": loot_in_view, "gold_in_view": bool(c["gold_visible"]),
                        "stairs_up_known": any(d == v.dlvl and n == "staircase up" for (d, x, y), n in m.features.items())},
        }

    def _hit(self, c: dict) -> bool:
        t, hp = self.prev_hp
        return t is not None and c["turn"] - t <= 2 and hp is not None and c["hp"] < hp

    def _hit_on_elbereth(self, v: View, c: dict) -> bool:
        a = self.jev_args.get("elbereth") or {}
        return bool(a.get("sent")) and v.pos == tuple(a.get("at") or ()) and (self._hit(c) or c["under_attack"])

    # ---------- the call ----------
    def ask(self, state: dict, questions: dict | None = None) -> dict | None:
        """Jev's probabilities over the actions (or, given `questions`, every answer), or None
        when the API is unavailable."""
        body = {"model": MODEL, "state": state, "questions": questions or QUESTIONS}
        started = time.time()
        for attempt in range(4):
            try:
                r = self.client.post(URL, headers={"Authorization": f"Bearer {self.key}"}, json=body)
            except httpx.HTTPError:
                time.sleep(2 ** attempt)
                continue
            if r.status_code in (429, 529) or r.status_code >= 500:
                time.sleep(float(r.headers.get("retry-after", 2 ** attempt)))
                continue
            if r.status_code >= 400:
                break
            self.calls += 1
            self.seconds += time.time() - started
            return r.json()["answers"] if questions else r.json()["answers"]["action"]
        self.failures += 1
        self.seconds += time.time() - started
        return None

    # ---------- carrying the choice out ----------
    def _do(self, action: str, v: View, c: dict):
        m, args = self.memory, self.jev_args
        cornered = c["adjacent_hostiles"] and c["hp"] * 3 < c["hpmax"]
        if cornered and action in ("explore", "loot", "probe", "search", "wear", "rest"):
            return None, "a hostile is adjacent and HP is low: not the moment to wander"
        if action == "pray":
            return r_pray(v, m, {}) if c["prayer_safe"] else (None, "prayer gate closed")
        if action == "fight":
            for mon in c["adjacent_hostiles"]:
                if mon["name"] not in DONT_MELEE:
                    m.pending_fight = (mon["x"], mon["y"])
                    return "F" + KEY_FOR[(mon["x"] - v.pos[0], mon["y"] - v.pos[1])], f"fight the {mon['name']}"
            return None, "nothing safe to melee"
        if action == "throw":
            for mon in c["visible_hostiles"]:
                if throwable(v) and mon["distance"] <= 8 and in_line(v.pos, (mon["x"], mon["y"])):
                    return r_throw(v, m, {"target": mon["name"]})
            return None, "nothing to throw at"
        if action == "elbereth":
            if self._hit_on_elbereth(v, c):  # Jev chose Elbereth at 0.6-0.8 for eight turns while a coyote bit through it.
                args.pop("elbereth", None)
                return None, "Elbereth is not working: still being hit on it"
            keys, note = r_elbereth(v, m, args.setdefault("elbereth", {}))
            if keys is None:
                args.pop("elbereth", None)
            return keys, note
        if action == "back_off":
            return r_step_away(v, m, {"max_steps": 1})
        if action == "eat":
            if c["safe_food"] and c["hunger"] in ("Hungry", "Weak", "Fainting"):
                m.pending_food = c["safe_food"][0]["letter"]
                return "e", f"eat ({c['hunger']})"
            corpse = self._corpse_to_eat(v, c)
            return corpse if corpse else (None, "nothing safe to eat")
        if action == "rest":
            if c["mobile_hostiles"] or c["under_attack"] or c["hunger"] in ("Weak", "Fainting", "Fainted"):
                return None, "not safe to rest, or starving"
            return "20s", f"rest (HP {c['hp']}/{c['hpmax']})"
        if action == "wear":
            got = self._wear_armor(v, c)
            return got if got else (None, "nothing to wear")
        if action == "loot":
            if c["turn"] < self.loot_quiet_until:
                return None, "loot just failed; quiet for a while"
            keys, note = r_loot(v, m, args.setdefault("loot", {"classes": self.orders["loot"]}))
            if keys is None:
                args.pop("loot", None)
                self.loot_quiet_until = c["turn"] + 20  # 400 top picks of loot with nothing reachable in 4 games
            return keys, note
        if action == "explore":
            return r_explore(v, m, {})
        if action == "probe":
            return r_probe_dark(v, m, {})
        if action == "search":
            if v.dlvl in m.searched_out or c["stairs_down"] is not None or not c["level_explored"]:
                return None, "searched out, stairs known, or not yet explored"
            keys, note = r_search_walls(v, m, {})
            if keys is None and note.startswith("failed: searched every spot"):
                m.searched_out.add(v.dlvl)
            return keys, note
        if action == "go_down":
            return r_go_down(v, m, {"start_dlvl": v.dlvl})
        if action == "go_up":
            mines = v.status.get("dungeon") == "The Gnomish Mines" and v.status.get("race") not in ("dwarf", "gnome") \
                and (c["xlvl"] or 0) < 8
            losing = c["adjacent_hostiles"] and c["hp"] * 3 < c["hpmax"]
            if not (mines or losing):  # Climbing anywhere else undoes progress (386 such picks in 30 games).
                return None, "no reason to go up"
            if v.feature(*v.pos) == "staircase up":
                return "<", "climb the stairs up"
            path = bfs(v, lambda x, y: v.feature(x, y) == "staircase up")
            return _step(v, m, path, "head for the stairs up") if path else (None, "no stairs up known")
        return None, f"unknown action {action}"

    def _decide(self, v: View):
        if v.kind != "command":
            return super()._decide(v)
        c = checks(v, self.memory)
        self.last_checks = c
        if v.engulfed:  # Mechanics, not a choice: any direction hits whatever swallowed us.
            self.note = "jev mode: engulfed, fight out"
            return "Fk", []
        if c["major_trouble"] and c["prayer_safe"]:
            # The rules pilot's first standing order. Jev fought a human zombie at 1 HP with prayer available (round two).
            _count(self.memory, "jev: prayed by rule")
            self.prev_hp = (c["turn"], c["hp"])
            self.note = "jev mode, rule: pray (" + ", ".join(c["major_trouble"]) + ")"
            return r_pray(v, self.memory, {})[0], []
        hit = self._hit(c)  # An HP drop since last turn counts as being under attack: blind, one quiet message turn let rest through.
        if hit:
            c["under_attack"] = True
        starving = c["hunger"] in ("Weak", "Fainting", "Fainted") and not c["safe_food"] and c["stairs_down"] is not None
        if starving and not c["adjacent_hostiles"] and not self._corpse_to_eat(v, c):
            # The engine's own rule: a fresh level has fresh kills. Jev's probabilities went flat here and the fallback rested.
            keys, note = r_go_down(v, m := self.memory, {"start_dlvl": v.dlvl})
            if keys:
                _count(m, "jev: starving, went down by rule")
                self.note = "jev mode, rule: starving with a known way down: " + note
                self.prev_hp = (c["turn"], c["hp"])
                return self._stuck_guard(v, keys, note)
        state = self._state(v, c)
        answer = self.ask(state)
        self.last_ask = (c["turn"], state, answer)  # for the replay page's brain log
        self.prev_hp = (c["turn"], c["hp"])
        if answer is None:
            _count(self.memory, "jev: api failure, rules decided")
            return super()._decide(v)
        order = [(a, p) for a, p in sorted(answer["probabilities"].items(), key=lambda kv: -kv[1]) if p >= 0.05]
        if not order:  # Flat: Jev does not know. The rules decide this turn rather than the fallback order.
            _count(self.memory, "jev: unsure, rules decided")
            return super()._decide(v)
        for action, p in order:
            keys, note = self._do(action, v, c)
            if keys:
                _count(self.memory, f"jev: {action}")
                if action != order[0][0]:
                    _count(self.memory, f"jev: {order[0][0]} not possible, did {action}")
                self.note = f"jev {action} ({p:.2f}): {note}"
                return self._stuck_guard(v, keys, note)
        _count(self.memory, "jev: nothing possible, rules decided")
        return super()._decide(v)


if __name__ == "__main__":  # Smoke test: one call on a sample state, with timing.
    e = JevEngine.__new__(JevEngine)
    e.key, e.client, e.calls, e.seconds, e.failures = _api_key(), httpx.Client(timeout=TIMEOUT_S), 0, 0.0, 0
    sample = {"pilot": {"hp": 12, "hp_max": 40, "wounded": "badly hurt", "experience_level": 4, "armor_class": 6,
                        "dungeon_level": 4, "dungeon": "The Dungeons of Doom", "turn": 1500, "hunger": "not hungry",
                        "conditions": [], "encumbrance": "none", "engulfed": False, "worn": ["small shield"]},
              "prayer": {"safe": True, "opens_in_turns": 0, "trouble": []},
              "threats": {"adjacent": [{"name": "soldier ant", "difficulty": 6, "never_melee": False}],
                          "in_view": [{"name": "soldier ant", "distance": 1, "difficulty": 6, "stationary": False}],
                          "attacked_by_something_unseen": False, "difficulty_limit": 6, "shopkeeper_in_view": False,
                          "watch_seen_on_level": False},
              "options": {"safe_food_in_pack": 1, "fresh_safe_corpse_nearby": False, "can_throw_at": None, "armor_to_wear": None,
                          "stairs_down_known": True, "on_stairs_down": False, "level_explored": False,
                          "unsearched_spots_remain": True, "in_gnomish_mines": False, "loot_in_view": False,
                          "gold_in_view": False, "stairs_up_known": True}}
    t0 = time.time()
    a = e.ask(sample)
    print(f"{time.time() - t0:.2f}s", a and a["choice"], a and {k: round(p, 2) for k, p in sorted(a["probabilities"].items(), key=lambda kv: -kv[1])[:5]})
