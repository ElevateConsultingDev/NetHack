"""Danger guard and warnings for helper.py: plain rules over an aipipe state.

check(state, key) says why a key about to go to the game is dangerous (or None);
warnings(state) lists what deserves a heads-up right now; item_actions(cls, text)
lists what can be done with an inventory item. No model calls.
"""
import re

DIRS = {b"h": (-1, 0), b"j": (0, 1), b"k": (0, -1), b"l": (1, 0),
        b"y": (-1, -1), b"u": (1, -1), b"b": (-1, 1), b"n": (1, 1),
        b"\x1b[A": (0, -1), b"\x1b[B": (0, 1), b"\x1b[C": (1, 0), b"\x1b[D": (-1, 0),
        b"\x1bOA": (0, -1), b"\x1bOB": (0, 1), b"\x1bOC": (1, 0), b"\x1bOD": (-1, 0)}
DEADLY_FOOD = re.compile(r"(cockatrice|chickatrice|Medusa) corpse|green slime corpse")
CURSED = re.compile(r"\bcursed\b")  # not "uncursed"
KNOWN_BUC = re.compile(r"\b(uncursed|blessed|cursed)\b")
STONERS = ("cockatrice", "chickatrice")
DANGEROUS = {
    "floating eye": "don't hit it in melee: it paralyzes you.",
    "cockatrice": "don't touch it bare-handed and never eat it.",
    "chickatrice": "don't touch it bare-handed and never eat it.",
    "soldier ant": "fast and deadly early on; fight in a corridor or leave.",
    "leprechaun": "steals gold.",
    "mind flayer": "eats your brain; get away.",
    "master mind flayer": "eats your brain; get away.",
    "werewolf": "its bite gives lycanthropy.",
    "wererat": "its bite gives lycanthropy.",
    "werejackal": "its bite gives lycanthropy.",
    "gelatinous cube": "engulfs and paralyzes.",
}
CONDITIONS = {
    "Stone": "You are turning to stone! Eat a lizard or acidic corpse, or pray.",
    "Slime": "You are turning into slime! Pray, or burn it off with fire.",
    "Strngl": "You are being strangled! Take off the amulet, or pray.",
    "Sick": "You have a deadly illness! Pray, or apply a unicorn horn.",
}


def _inventory(state):
    """letter -> text, truly identified when the reveal cheat is on."""
    inv = (state.get("reveal") or {}).get("inventory") or state.get("inventory") or []
    return {i["letter"]: i["text"] for i in inv}


def _major_trouble(st):
    hp, hpmax = st.get("hp", 1), st.get("hpmax", 1)
    return (hp < 6 or hp * 7 < hpmax or st.get("hunger") in ("Weak", "Fainting")
            or any(c in CONDITIONS for c in st.get("conditions", [])))


def prayer_unsafe(state):
    """Why praying now would go badly, or None. Needs the reveal cheat's prayer numbers."""
    p = (state.get("reveal") or {}).get("prayer")
    if not p:
        return None
    if p["anger"]:
        return "your god is angry with you."
    if p["luck"] < 0:
        return "your luck is negative."
    limit = 200 if _major_trouble(state.get("status", {})) else 0
    if p["timeout"] > limit:
        return f"your prayer timeout is {p['timeout']} (needs {limit} or less right now)."
    return None


ITEM_PROMPTS = {"e": "What do you want to eat?", "P": "What do you want to put on?",
                "W": "What do you want to wear?"}  # so check() can vet an action before it's sent
WORN = re.compile(r"\((being worn|on left|on right|in use)")


def item_actions(cls, text):
    """(command key, label) for an inventory item of class `cls` (its map symbol)."""
    worn = WORN.search(text)
    acts = []
    if cls == ")":
        if "weapon in hand" not in text:
            acts += [("w", "Wield"), ("Q", "Quiver")]
        acts.append(("t", "Throw"))
    elif cls == "[":
        acts.append(("T", "Take off") if worn else ("W", "Wear"))
    elif cls in '="' or (cls == "(" and re.search(r"blindfold|towel|lenses", text)):
        acts.append(("R", "Remove") if worn else ("P", "Put on"))
    elif cls == "(":
        acts.append(("a", "Apply"))
    elif cls == "!":
        acts += [("q", "Quaff"), ("t", "Throw")]
    elif cls in "?+":
        acts.append(("r", "Read"))
    elif cls == "/":
        acts += [("z", "Zap"), ("E", "Engrave with")]
    elif cls == "%":
        acts.append(("e", "Eat"))
    elif cls in "*`0_":
        acts.append(("t", "Throw"))
    return acts + [("d", "Drop"), ("?", "Ask the helper")]


def asked_letters(state):
    """(question, letters) when the game is asking for an item, like
    "What do you want to drink? [h or ?*]"; letters expands ranges like a-d."""
    ctx = state.get("context") or {}
    m = re.match(r"(.*?\?) \[([^\]]*?)(?: or \?\*)?\]", ctx.get("prompt") or "")
    if ctx.get("kind") != "yn" or not m or "?*" not in ctx.get("prompt", ""):
        return None
    spec, letters, i = m.group(2), set(), 0
    while i < len(spec):
        if i + 2 < len(spec) and spec[i + 1] == "-" and spec[i].isalpha():
            letters.update(chr(c) for c in range(ord(spec[i]), ord(spec[i + 2]) + 1))
            i += 3
        else:
            if spec[i] != " ":
                letters.add(spec[i])
            i += 1
    return m.group(1), letters


ARROWS = {b"\x1b[" + c: c for c in (b"A", b"B", b"C", b"D")}
ARROWS.update({b"\x1bO" + c: c for c in (b"A", b"B", b"C", b"D")})
DIGGERS = re.compile(r"pick-axe|mattock|broad pick|bullwhip")  # apply asks a direction


def apply_wielded(state, key):
    """At "What do you want to use or apply?", an arrow means the wielded pick-axe
    (or mattock, bullwhip) that way: its letter, to send before the arrow."""
    q = asked_letters(state)
    if key not in ARROWS or not q or q[0] != "What do you want to use or apply?":
        return None
    return next((k for k, t in _inventory(state).items()
                 if "weapon in hand" in t and DIGGERS.search(t) and k in q[1]), None)


def check(state, key):
    """Why `key` (bytes from the keyboard) is dangerous in this state, or None."""
    ctx = state.get("context") or {}
    prompt = ctx.get("prompt") or ""
    st = state.get("status") or {}
    inv = _inventory(state)
    letter = key.decode("latin-1") if len(key) == 1 else ""

    if prompt.startswith("What do you want to eat?") and letter in inv:
        if DEADLY_FOOD.search(inv[letter]):
            return f"eating {inv[letter]} kills you."
        if st.get("hunger") == "Satiated":
            return "you are Satiated: eating more can choke you to death."
    m = re.match(r"There (?:is|are) (.*) here; eat (?:it|one)\?", prompt)
    if m and key == b"y":
        if DEADLY_FOOD.search(m.group(1)):
            return f"eating {m.group(1)} kills you."
        if st.get("hunger") == "Satiated":
            return "you are Satiated: eating more can choke you to death."
    if prompt.startswith("Are you sure you want to pray?") and key == b"y":
        why = prayer_unsafe(state)
        if why:
            return "praying now is not safe: " + why
    if prompt.startswith(("What do you want to put on?", "What do you want to wear?")) and letter in inv:
        text = inv[letter]
        if CURSED.search(text):
            return f"{text} is cursed: you won't be able to take it off."
        if not KNOWN_BUC.search(text):
            return f"{text} might be cursed (unknown); you might not get it off."
    if ctx.get("kind") == "command" and key == b"O":  # a stray O while mashing through --More--
        return "O opens the options menu."
    if ctx.get("kind") == "command" and key in DIRS:
        you = state.get("player") or {}
        dx, dy = DIRS[key]
        tx, ty = you.get("x", 0) + dx, you.get("y", 0) + dy
        for c in state.get("cells", []):
            if c["x"] == tx and c["y"] == ty and c["kind"] == "monster" and not c.get("peaceful"):
                if c["name"] == "floating eye" and "Blind" not in st.get("conditions", []):
                    return "hitting a floating eye paralyzes you, often to death."
                if c["name"] in STONERS and not any("weapon in hand" in t for t in inv.values()):
                    return f"fighting a {c['name']} bare-handed turns you to stone."
    return None


def warnings(state):
    """The set of heads-ups that apply right now."""
    out = set()
    st = state.get("status") or {}
    if st.get("hpmax") and 0 < st["hp"] and st["hp"] * 3 < st["hpmax"]:  # -1 while restoring
        out.add(f"HP is low ({st['hp']}/{st['hpmax']}).")
    if st.get("hunger") in ("Weak", "Fainting"):
        out.add(f"You are {st['hunger']}: eat something now.")
    for c in st.get("conditions", []):
        if c in CONDITIONS:
            out.add(CONDITIONS[c])
    you = state.get("player") or {}
    for c in state.get("cells", []):
        if c["kind"] == "monster" and not c.get("peaceful") and c["name"] in DANGEROUS:
            if max(abs(c["x"] - you.get("x", 0)), abs(c["y"] - you.get("y", 0))) <= 7:
                out.add(f"{c['name'].capitalize()} nearby: {DANGEROUS[c['name']]}")
    return out


if __name__ == "__main__":
    base = {"context": {"kind": "command"}, "player": {"x": 10, "y": 5},
            "status": {"hp": 4, "hpmax": 20, "hunger": "Weak", "conditions": ["Stone"]},
            "inventory": [{"letter": "f", "text": "a cockatrice corpse"},
                          {"letter": "r", "text": "a ring of teleportation"}],
            "cells": [{"x": 11, "y": 5, "kind": "monster", "name": "floating eye", "peaceful": 0}]}
    assert "floating eye" in check(base, b"l")
    assert check(base, b"h") is None
    assert "kills you" in check(dict(base, context={"kind": "yn", "prompt": "What do you want to eat? [f or ?*]"}), b"f")
    assert "might be cursed" in check(dict(base, context={"kind": "yn", "prompt": "What do you want to put on? [r or ?*]"}), b"r")
    pray = dict(base, context={"kind": "yn", "prompt": "Are you sure you want to pray? [yn] (n)"},
                reveal={"prayer": {"timeout": 300, "luck": 0, "anger": 0}})
    assert "300" in check(pray, b"y")
    pray["reveal"]["prayer"]["timeout"] = 150  # major trouble: 200 or less is fine
    assert check(pray, b"y") is None
    w = warnings(base)
    assert any("HP is low" in x for x in w) and any("stone" in x for x in w)
    assert any("Floating eye nearby" in x for x in w)
    assert [k for k, _ in item_actions("=", "a ring of teleportation")][:1] == ["P"]
    assert [k for k, _ in item_actions("[", "a +0 small shield (being worn)")][:1] == ["T"]
    assert ("w", "Wield") not in item_actions(")", "a +1 long sword (weapon in hand)")
    put_on = dict(base, context={"kind": "yn", "prompt": ITEM_PROMPTS["P"]})
    assert check(put_on, b"r")  # the popup's Put on is vetted like typing it
    asked = lambda p: asked_letters({"context": {"kind": "yn", "prompt": p}})
    assert asked("What do you want to drink? [h or ?*]") == ("What do you want to drink?", {"h"})
    assert asked("What do you want to wield? [- a-cf or ?*]")[1] == {"-", "a", "b", "c", "f"}
    assert asked("Really attack the gnome? [yn] (n)") is None
    assert check(dict(base, context={"kind": "command"}), b"O")
    assert check(dict(base, context={"kind": "yn", "prompt": "Really attack? [yn] (n)"}), b"O") is None
    dig = dict(base, inventory=[{"letter": "L", "text": "a pick-axe (weapon in hand)"}],
               context={"kind": "yn", "prompt": "What do you want to use or apply? [L or ?*]"})
    assert apply_wielded(dig, b"\x1b[D") == "L"
    assert apply_wielded(dig, b"L") is None  # a letter still picks the item
    assert apply_wielded(dict(dig, inventory=[{"letter": "L", "text": "a pick-axe"}]), b"\x1b[D") is None
    print("guard ok")
