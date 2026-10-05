"""Danger guard and warnings for helper.py: plain rules over an aipipe state.

check(state, key) says why a key about to go to the game is dangerous (or None);
warnings(state) lists what deserves a heads-up right now. No model calls.
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
    print("guard ok")
