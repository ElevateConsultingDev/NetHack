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
