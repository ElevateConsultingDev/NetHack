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
