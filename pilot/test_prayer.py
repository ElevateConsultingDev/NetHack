"""Prayer gate self-check: python3 -m pilot.test_prayer"""
from pilot.engine import Engine, View, checks


def snap(msgs, turn, hp=40, hunger=""):
    return {"messages": msgs, "status": {"turn": turn, "hp": hp, "hpmax": 50, "hunger": hunger},
            "context": {"kind": "command"}}


def safe(e, turn):
    return checks(View(snap([], turn), e.memory), e.memory)["prayer_safe"]


e = Engine()
m = e.memory
assert not safe(e, 299) and safe(e, 300)
assert checks(View(snap([], 300, hunger="Weak"), m), m)["major_trouble"] == ["Weak"]
assert checks(View(snap([], 300, hp=7), m), m)["major_trouble"] == ["critical HP"]
# Success; the gift voice after it must not count as a failure.
m.stats["prayers"], m.last_pray_turn = 1, 400
e._read_messages(View(snap(["You feel that Tyr is well-pleased.", 'The voice of Tyr booms: "Thou hast pleased me"'], 403), m))
assert m.stats["prayers ok"] == 1 and not m.prayer_broken
assert not safe(e, 1399) and safe(e, 1400)
assert checks(View(snap([], 1250), m), m)["prayer_opens_in"] == 150
# Failure closes the gate for good.
m.stats["prayers"], m.last_pray_turn = 2, 1400
e._read_messages(View(snap(["You feel that Tyr is displeased."], 1403), m))
assert m.prayer_broken and not safe(e, 9000)
# Luck penalty closes it until Luck decays.
e = Engine()
e._read_messages(View(snap(["You murderer!"], 500), e.memory))
assert not safe(e, 1600) and safe(e, 1700)
print("ok")

# Tins (plan item 2): judged by what they smell like.
from pilot.engine import tin_ok


class _V:
    status = {"race": "dwarf", "conditions": []}


assert tin_ok("newts", _V) and tin_ok("spinach", _V)
assert not tin_ok("dwarves", _V) and not tin_ok("cockatrices", _V)
print("tins ok")

from pilot.engine import is_safe_food

assert is_safe_food("2 tins") and is_safe_food("an uncursed food ration") and is_safe_food("a tin")
assert not is_safe_food("a floating eye corpse") and not is_safe_food("an egg")
print("food words ok")
assert is_safe_food("2 lumps of royal jelly") and is_safe_food("3 cloves of garlic") \
    and is_safe_food("2 huge chunks of meat") and is_safe_food("4 eucalyptus leaves")

# A brain prayer while the gate is closed is refused and says so (review finding).
from pilot.engine import Engine as _E
_e = _E()
_e.last_checks = {"prayer_safe": False}
assert _e.order("pray") is False and _e.routine is None
_e.last_checks = {"prayer_safe": True}
assert _e.order("pray") is True and _e.routine == "pray"
print("review fixes ok")

# Engulfed: NetHack draws the engulfer around you as a 3x3 box.
from pilot.engine import View as _View

_row = " " * 10
_box = {"context": {"kind": "command"}, "player": {"x": 5, "y": 2},
        "map": [_row, "   /-\\    ", "   |@|    ", "   \\-/    ", _row]}
_room = {"context": {"kind": "command"}, "player": {"x": 5, "y": 2},
         "map": [_row, "   ---    ", "   |@|    ", "   ---    ", _row]}
assert _View(_box).engulfed and not _View(_room).engulfed
print("engulf ok")

from pilot.engine import armor_slot
assert armor_slot("a hard hat") == "helmet" and armor_slot("an uncursed +0 crude chain mail") == "body"
assert armor_slot("a pair of hard shoes") == "boots" and armor_slot("a plumed helmet") is None
assert armor_slot("a pair of padded gloves") is None and armor_slot("a +3 small shield (being worn)") is None
print("armor ok")

# Corpses (plan item 11): the game's own monster flags decide.
from pilot.engine import species_ok

assert species_ok("jackal", "human")[0] and species_ok("dwarf", "human")[0]
assert species_ok("giant beetle", "human") == (False, "poisonous") and not species_ok("acid blob", "human")[0]
assert species_ok("dwarf", "dwarf") == (False, "cannibalism") and not species_ok("watchman", "human")[0]
assert not species_ok("cockatrice", "human")[0] and not species_ok("kobold zombie", "human")[0]
print("corpses ok")

# Smoke: the engine steps a small real-looking snapshot without crashing.
_snap = {"context": {"kind": "command"}, "player": {"x": 3, "y": 2}, "messages": [],
         "status": {"turn": 10, "hp": 16, "hpmax": 16, "hunger": "", "dlvl": 1, "xlvl": 1, "conditions": [],
                    "race": "human", "alignment": "lawful", "dungeon": "The Dungeons of Doom"},
         "map": ["", " -----", " |...|", " |.@.|", " |...", " -----"], "cells": [], "inventory": []}
_keys, _esc = Engine().step(_snap)
assert _keys or _esc
print("step ok")

# Hard rule: the brain may not order a melee on a floating eye (unless Blind).
_e = _E()
_e.last_checks = {"prayer_safe": True, "conditions": []}
assert _e.order("fight", {"target": "floating eye"}) is False and _e.routine is None
_e.last_checks = {"prayer_safe": True, "conditions": ["Blind"]}
assert _e.order("fight", {"target": "floating eye"}) is True
print("fight guard ok")

# Branch recall: the engine picks the leaves that match the moment.
import os as _os, tempfile as _tf
from pilot.brain import recall as _recall
_root = _tf.mkdtemp()
for _leaf, _txt in (("monsters/floating-eye", "floating eye in view: throw, never melee"),
                    ("hunger/weak", "Weak: eat a floor corpse"), ("depth/dlvl-3-5", "dlvl 3-5: clear the level"),
                    ("general", "keep the pet"), ("monsters/jackal", "jackal: fight")):
    _os.makedirs(_os.path.dirname(_os.path.join(_root, _leaf + ".md")) or _root, exist_ok=True)
    open(_os.path.join(_root, _leaf + ".md"), "w").write(_txt)
_c = {"visible_hostiles": [{"name": "floating eye", "distance": 2}], "hunger": "Weak"}
_s = {"status": {"dlvl": 4, "dungeon": "The Dungeons of Doom"}}
_m = _recall(_c, ["Weak and no known-safe food"], _s, root=_root)
assert "[monsters/floating-eye]" in _m and "[hunger/weak]" in _m and "[depth/dlvl-3-5]" in _m and "[general]" in _m
assert "jackal" not in _m, _m
print("recall ok")

# Dark room floor: seen once, it stays known even when drawn blank again.
from pilot.engine import View as _View, Memory as _Memory, _frontier
_mem = _Memory()
_dark = dict(_snap, map=["", " ---- ", " |.@| ", " ---- "], player={"x": 4, "y": 2})
_e2 = Engine(); _e2.memory = _mem
_e2.step(_dark)                                # sees the floor at (3, 2)
_dark["map"][2] = " | @| "                     # drawn blank once we look away
_v = _View(_dark, _mem)
assert not _v.unknown(3, 2) and _v.walkable(3, 2)
assert _v.unknown(0, 2)                        # never-seen blank is still unknown
assert not _frontier(_v, _mem)(4, 2)           # nothing unknown next to us: not a frontier
print("dark floor ok")

# Unseen attacker: never rest through "It bites!"; fight yields to an ordered retreat.
_hurt = dict(_snap, messages=["It bites!"], status=dict(_snap["status"], hp=6, hpmax=16))
_k, _esc = Engine().step(_hurt)
assert _k != "20s" and (_esc or _k), (_k, _esc)          # escalates (or hits back), never rests
_bee = dict(_snap, cells=[{"x": 4, "y": 2, "kind": "monster", "name": "killer bee", "difficulty": 5}],
            status=dict(_snap["status"], hp=6, hpmax=16, xlvl=6))
_k4, _ = Engine().step(_bee)
assert (_k4 or "").startswith("F"), _k4                 # adjacent hostiles are still fought
print("unseen attack ok")

# Minetown: a locked door is never kicked once the watch has been seen on the level.
from pilot.engine import r_explore as _r_explore
_town = dict(_snap, map=["", " -----", " |...|", " |.@+|", " |...|", " -----"], messages=["This door is locked."],
             cells=[{"x": 4, "y": 3, "kind": "feature", "name": "closed door"},
                    {"x": 2, "y": 2, "kind": "monster", "name": "watchman", "difficulty": 6, "peaceful": True}])
_e5 = Engine(); _e5.step(_town)
assert 1 in _e5.memory.watch
_k5, _n5 = _r_explore(_View(_town, _e5.memory), _e5.memory, {})
assert not (_k5 or "").startswith("\x04"), (_k5, _n5)
print("watch ok")

# Retreat upstairs: hurt, two hostiles in view, no prayer, stairs up known and close.
_e6 = Engine(); _e6.memory.last_pray_turn = 5  # prayer gate shut
_e6.memory.features[(1, 2, 2)] = "staircase up"
_flee = dict(_snap, map=["", " -----", " |<..|", " |.@.|", " |...|", " -----"],
             cells=[{"x": 2, "y": 2, "kind": "feature", "name": "staircase up"},
                    {"x": 4, "y": 3, "kind": "monster", "name": "jackal", "difficulty": 1},
                    {"x": 4, "y": 4, "kind": "monster", "name": "jackal", "difficulty": 1}],
             status=dict(_snap["status"], hp=6, hpmax=16, turn=50))
_k6, _ = _e6.step(_flee)
assert _k6 in ("h", "y"), _k6   # a step toward the stairs up, not a fight
print("flee upstairs ok")

# A worn "Closed for inventory" engraving still shuts the shop door.
from pilot.engine import closed_for_inventory
assert closed_for_inventory('Something is written here in the dust. You read: "C?o??c fo  inventory".')
assert closed_for_inventory('You read: "Closed for inventory".')
assert not closed_for_inventory('You read: "Elbereth".') and not closed_for_inventory('You read: "ad aerarium".')
print("closed shop ok")

# Spoiler table from src/monst.c: speed, Elbereth, hazards.
from pilot.spoilers import spoiler, SPOILERS
assert spoiler("soldier ant")["speed"] == 18 and not spoiler("soldier ant")["outrun"]
assert spoiler("hill orc")["outrun"] and spoiler("floating eye")["passive"] == ["paralysis"]
assert not spoiler("watchman")["elbereth"] and not spoiler("minotaur")["elbereth"] and spoiler("killer bee")["elbereth"]
assert "stoning" in spoiler("cockatrice")["hazards"] and len(SPOILERS) > 350
print("spoilers ok")
