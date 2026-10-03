"""Spoiler table: what the pilot should know about every monster, from the game's own src/monst.c.

    from pilot.spoilers import SPOILERS, spoiler
    spoiler("soldier ant") -> {"speed": 18, "level": 3, "attacks": 2, "max_damage": 20, "symbol": "a",
                               "elbereth": True, "hazards": ["poison"], "flies": False, ...}

The pilot (a Valkyrie) moves at speed 12. A monster faster than that cannot be outrun; one with
`elbereth` False (humans '@', minotaurs, shopkeepers, guards, priests, the Riders) ignores the
engraving. Hazards name the attacks a careful player avoids: stoning touch, paralysing passive
(the floating eye), level drain, acid or fire passives, engulfing, weapon users that may shoot.

    python3 -m pilot.spoilers [name ...]   # print rows (default: the usual killers)
"""

from __future__ import annotations

import os
import re
import sys

PILOT_SPEED = 12
_SRC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src", "monst.c")

_HAZARD = {
    "AD_STON": "stoning", "AD_DRLI": "level drain", "AD_PLYS": "paralysis", "AD_SLIM": "sliming",
    "AD_DISE": "disease", "AD_DRST": "poison", "AD_DRDX": "poison", "AD_DRCO": "poison", "AD_SLEE": "sleep",
    "AD_BLND": "blinding", "AD_CONF": "confusion", "AD_STUN": "stun", "AD_DREN": "energy drain",
    "AD_SITM": "theft", "AD_SEDU": "theft", "AD_SGLD": "gold theft", "AD_TLPT": "teleport",
    "AD_WRAP": "drowning", "AD_RUST": "rust", "AD_CORR": "corrosion", "AD_DCAY": "rot",
    "AD_LYCA": "lycanthropy", "AD_HALU": "hallucination", "AD_WERE": "lycanthropy", "AD_CURS": "curse",
    "AD_ELEC": "shock", "AD_FIRE": "fire", "AD_COLD": "cold", "AD_ACID": "acid", "AD_DGST": "digestion",
}
_SYMBOLS = {  # S_ constants -> map glyph
    "S_ANT": "a", "S_BLOB": "b", "S_COCKATRICE": "c", "S_DOG": "d", "S_EYE": "e", "S_FELINE": "f",
    "S_GNOME": "G", "S_HUMANOID": "h", "S_IMP": "i", "S_JELLY": "j", "S_KOBOLD": "k", "S_LEPRECHAUN": "l",
    "S_MIMIC": "m", "S_NYMPH": "n", "S_ORC": "o", "S_PIERCER": "p", "S_QUADRUPED": "q", "S_RODENT": "r",
    "S_SPIDER": "s", "S_TRAPPER": "t", "S_UNICORN": "u", "S_VORTEX": "v", "S_WORM": "w", "S_XAN": "x",
    "S_LIGHT": "y", "S_ZRUTY": "z", "S_ANGEL": "A", "S_BAT": "B", "S_CENTAUR": "C", "S_DRAGON": "D",
    "S_ELEMENTAL": "E", "S_FUNGUS": "F", "S_GNOME_": "G", "S_GIANT": "H", "S_JABBERWOCK": "J", "S_KOP": "K",
    "S_LICH": "L", "S_MUMMY": "M", "S_NAGA": "N", "S_OGRE": "O", "S_PUDDING": "P", "S_QUANTMECH": "Q",
    "S_RUSTMONST": "R", "S_SNAKE": "S", "S_TROLL": "T", "S_UMBER": "U", "S_VAMPIRE": "V", "S_WRAITH": "W",
    "S_XORN": "X", "S_YETI": "Y", "S_ZOMBIE": "Z", "S_HUMAN": "@", "S_GHOST": " ", "S_GOLEM": "'",
    "S_DEMON": "&", "S_EEL": ";", "S_LIZARD": ":",
}
_IGNORE_ELBERETH = {"minotaur", "shopkeeper", "guard", "watchman", "watch captain", "aligned priest",
                    "high priest", "Death", "Pestilence", "Famine"}


def _parse() -> dict[str, dict]:
    with open(_SRC) as f:
        src = f.read()
    table: dict[str, dict] = {}
    for chunk in src.split('MON("')[1:]:
        name = chunk.split('"', 1)[0]
        body = chunk.split("),\n    MON(")[0]  # up to the next entry is plenty; fields are near the top
        sym = re.search(r'",\s*(S_[A-Z_]+)', chunk)
        lvl = re.search(r"LVL\((-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+),\s*(-?\d+)\)", chunk)
        atk_block = re.search(r"A\((.*?)\),\s*SIZ\(", chunk, re.S)
        attacks = re.findall(r"ATTK\((AT_\w+),\s*(AD_\w+),\s*(\d+),\s*(\d+)\)", atk_block.group(1)) if atk_block else []
        flags = re.search(r"SIZ\(.*?\),\s*[^,]+,\s*[^,]+,\s*(.*?),\s*(\d+),\s*CLR_", chunk, re.S)
        flagtext = flags.group(1) if flags else ""
        difficulty = int(flags.group(2)) if flags else 0
        hazards, passive = [], []
        for at, ad, n, d in attacks:
            h = _HAZARD.get(ad)
            if at == "AT_BOOM":
                h = "explodes when killed"
            elif at == "AT_ENGL":
                h = "engulfs"
            elif at == "AT_EXPL":
                h = "explodes on contact"
            if at in ("AT_NONE", "AT_BOOM"):  # Passive: it hurts the one who hits it.
                if h and h not in passive:
                    passive.append(h)
            elif h and h not in hazards:
                hazards.append(h)
        active = [(at, ad, int(n), int(d)) for at, ad, n, d in attacks if at not in ("AT_NONE", "AT_BOOM")]
        symbol = _SYMBOLS.get(sym.group(1), "?") if sym else "?"
        human = symbol == "@" or "M2_HUMAN" in flagtext
        table[name] = {
            "symbol": symbol,
            "level": int(lvl.group(1)) if lvl else 0,
            "speed": int(lvl.group(2)) if lvl else 0,
            "ac": int(lvl.group(3)) if lvl else 10,
            "difficulty": difficulty,
            "attacks": len(active),
            "max_damage": sum(n * d for _, _, n, d in active),
            "ranged": any(at in ("AT_WEAP",) for at, *_ in active) and "M1_NOHANDS" not in flagtext,
            "hazards": hazards,
            "passive": passive,
            "flies": "M1_FLY" in flagtext,
            "mindless": "M1_MINDLESS" in flagtext,
            "elbereth": not (human or name in _IGNORE_ELBERETH),
            "outrun": (int(lvl.group(2)) if lvl else 0) < PILOT_SPEED,
            "group": "G_LGROUP" in chunk.split("A(")[0] or "G_SGROUP" in chunk.split("A(")[0],
        }
    return table


SPOILERS = _parse()


def spoiler(name: str) -> dict:
    return SPOILERS.get(name) or SPOILERS.get(name.replace("the ", "")) or {}


if __name__ == "__main__":
    names = sys.argv[1:] or ["killer bee", "soldier ant", "hill orc", "giant bat", "rothe", "wererat", "jaguar",
                             "floating eye", "cockatrice", "yellow light", "gnome lord", "dwarf", "watchman",
                             "minotaur", "gas spore", "leprechaun", "water nymph", "jackal", "homunculus", "raven"]
    print(f"{'monster':16} {'sym':3} {'lvl':>3} {'spd':>3} {'atk':>3} {'dmg':>3} {'diff':>4} {'outrun':6} {'elber':5} {'group':5} hazards")
    for n in names:
        r = spoiler(n)
        if not r:
            print(f"{n:16} (not found)"); continue
        print(f"{n:16} {r['symbol']:3} {r['level']:>3} {r['speed']:>3} {r['attacks']:>3} {r['max_damage']:>3} {r['difficulty']:>4} "
              f"{str(r['outrun']):6} {str(r['elbereth']):5} {str(r['group']):5} {', '.join(r['hazards'] + r['passive'])}")
    print(f"{len(SPOILERS)} monsters")
