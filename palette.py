"""Fuzzy search (F8 in helper.py) over commands, inventory actions and map things.

Commands come from NetHack's own table (extcmdlist in src/cmd.c), so the list
matches the game. An entry is {label, detail, action}; helper.py runs the action:
("keys", bytes) | ("item", key, letter, text) | ("goto", x, y) | ("fkey", bytes).
"""
import re

import guard

CMD_RE = re.compile(r'\{\s*([^,{}]+?),\s*"([^"]+)",((?:\s*"(?:[^"\\]|\\.)*")+)\s*,\s*(\w+)\s*(?:,\s*([^}]*?))?\s*\}', re.S)


def _key(k, name):
    """(bytes to send, key as shown) for a command's key in cmd.c notation."""
    m = re.fullmatch(r"'(.)'", k)
    if m and m.group(1) not in "#\\":
        return m.group(1).encode(), m.group(1)
    m = re.fullmatch(r"C\('(.)'\)", k)
    if m:
        return bytes([ord(m.group(1).lower()) & 0x1f]), "^" + m.group(1).upper()
    m = re.fullmatch(r"M\('(.)'\)", k)
    return f"#{name}\r".encode(), ("M-" + m.group(1)) if m else "#" + name


def load_commands(cmd_c):
    src = open(cmd_c).read()
    start = src.index("struct ext_func_tab extcmdlist[] = {")
    out = []
    for m in CMD_RE.finditer(src[start:src.index("\n};", start)]):
        key, name, desc, _func, flags = m.groups()
        if "WIZMODECMD" in (flags or "") or name in ("#", "?"):
            continue
        desc = "".join(re.findall(r'"((?:[^"\\]|\\.)*)"', desc))
        send, shown = _key(key.strip(), name)
        out.append(dict(label=name, detail=f"{desc}  [{shown}]", action=("keys", send)))
    return out


def entries(state, commands, extras):
    """Everything searchable right now: extras, commands, item actions, map things."""
    out = list(extras) + list(commands)
    for item in state.get("inventory", []):
        for key, label in guard.item_actions(item.get("class", ""), item["text"]):
            if key != "?":
                out.append(dict(label=f"{label} {item['text']}", detail=f"{key}{item['letter']}",
                                action=("item", key, item["letter"], item["text"])))
    you = state.get("player") or {}
    rev = state.get("reveal") or {}
    things = [(c["name"], c["kind"], c["x"], c["y"]) for c in state.get("cells", []) if c["kind"] != "you"]
    things += [(o["text"], "item", o["x"], o["y"]) for o in rev.get("objects", [])]
    things += [(m["name"], "monster", m["x"], m["y"]) for m in rev.get("monsters", [])]
    seen = set()
    for name, kind, x, y in things:
        if (name, x, y) in seen or (x, y) == (you.get("x"), you.get("y")):
            continue
        seen.add((name, x, y))
        far = max(abs(x - you.get("x", 0)), abs(y - you.get("y", 0)))
        out.append(dict(label=f"go to {name}", detail=f"{kind}, {far} away", action=("goto", x, y)))
    return out


def score(query, text):
    """Higher is better; None if some query word doesn't match at all."""
    t, total = text.lower(), 0.0
    for w in query.lower().split():
        i = t.find(w)
        if i >= 0:
            total += (100 if i == 0 or not t[i - 1].isalnum() else 50) - i * 0.1
            continue
        pos = -1
        for ch in w:  # letters in order, with gaps
            pos = t.find(ch, pos + 1)
            if pos < 0:
                return None
        total += 10
    return total - len(t) * 0.01


def search(query, items, n=12):
    if not query.strip():
        return items[:n]
    scored = [(score(query, f"{e['label']} {e['detail']}"), e) for e in items]
    return [e for s, e in sorted((x for x in scored if x[0] is not None), key=lambda x: -x[0])][:n]


if __name__ == "__main__":
    import os
    cmds = load_commands(os.path.join(os.path.dirname(os.path.abspath(__file__)), "src", "cmd.c"))
    by = {c["label"]: c for c in cmds}
    assert by["pray"]["action"] == ("keys", b"#pray\r")
    assert by["eat"]["action"] == ("keys", b"e")
    assert by["kick"]["action"] == ("keys", b"\x04")
    assert "wizmap" not in by and len(cmds) > 80
    assert search("pra", cmds)[0]["label"] == "pray"
    state = {"player": {"x": 5, "y": 5},
             "inventory": [{"letter": "f", "class": "!", "text": "a potion of healing"}],
             "cells": [{"x": 9, "y": 5, "kind": "feature", "name": "altar"}]}
    found = search("quaff heal", entries(state, cmds, []))
    assert found[0]["action"] == ("item", "q", "f", "a potion of healing")
    assert search("altar", entries(state, cmds, []))[0]["action"] == ("goto", 9, 5)
    print("palette ok")
