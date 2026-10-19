"""Price identification: what an unidentified item can be, from a shop's quote.

    python3 -m pilot.prices --check

Stepping onto a shop item shows "You see here a scroll labeled X (for sale, 80 zorkmids)". The
quote is get_cost() in src/shk.c: the base price, times 4/3 for about a third of unidentified
items (fixed per object), times the charisma factor, rounded. Inverting it over the base prices
of the item's class (read from src/objects.c) leaves the types it can be; a class with one member
is an identification.
"""

from __future__ import annotations

import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SALE = re.compile(r"(?:You see here|You see) (?:an? |the |(\d+) )?(.+?) \(for sale, (\d+) zorkmids?\)")
_COSTS: dict[str, dict[str, int]] = {}


def costs() -> dict[str, dict[str, int]]:
    """{"scroll": {"identify": 20, ...}, "potion": ..., "wand": ..., "ring": ...} from objects.c."""
    if _COSTS:
        return _COSTS
    src = open(os.path.join(HERE, "..", "src", "objects.c")).read()
    pats = {"scroll": r'^SCROLL\("([^"]+)",\s*(?:"[^"]*"|None),\s*\d+,\s*\d+,\s*(\d+)\)',
            "potion": r'^POTION\("([^"]+)",\s*(?:"[^"]*"|None),\s*\d+,\s*\w+,\s*\d+,\s*(\d+),',
            "wand": r'^WAND\("([^"]+)",\s*(?:"[^"]*"|None),\s*\d+,\s*(\d+),',
            "ring": r'^RING\("([^"]+)",\s*(?:"[^"]*"|None),\s*\w+,\s*(\d+),'}
    for cls, pat in pats.items():
        _COSTS[cls] = {m.group(1): int(m.group(2)) for m in re.finditer(pat, src, re.M)}
    _COSTS["scroll"].pop("mail", None)
    return _COSTS


def quote(base: int, cha: int, surcharge: bool, dunce: bool = False) -> int:
    """get_cost() for one item (shk.c), not angry."""
    tmp, mul, div = base or 5, 1, 1
    if surcharge:
        mul, div = mul * 4, div * 3
    if dunce:
        mul, div = mul * 4, div * 3
    if cha > 18:
        div *= 2
    elif cha == 18:
        mul, div = mul * 2, div * 3
    elif cha >= 16:
        mul, div = mul * 3, div * 4
    elif cha <= 5:
        mul *= 2
    elif cha <= 7:
        mul, div = mul * 3, div * 2
    elif cha <= 10:
        mul, div = mul * 4, div * 3
    tmp *= mul
    if div > 1:
        tmp = ((tmp * 10) // div + 5) // 10
    return max(tmp, 1)


def kind(name: str) -> tuple[str, str] | None:
    """("scroll", "labeled FOO") style key for an unidentified magic item's appearance, or None."""
    for cls in ("scroll", "potion", "wand", "ring"):
        if f"{cls} of " in name or f"{cls}s of " in name:
            return None  # already identified
        if re.search(rf"\b{cls}s?\b", name):
            app = re.sub(r"^(?:\d+ |an? |the )?(?:uncursed |blessed |cursed )?", "", name)
            return cls, re.sub(rf"\s*\b{cls}s?\b\s*", " ", app).strip()
    return None


def candidates(cls: str, price: int, cha: int, qty: int = 1) -> set[str]:
    each = price // max(qty, 1)
    return {n for n, base in costs()[cls].items()
            if any(quote(base, cha, s) == each for s in (False, True))}


def check() -> None:
    c = costs()
    assert c["scroll"]["identify"] == 20 and c["scroll"]["genocide"] == 300 and "mail" not in c["scroll"], c["scroll"]
    assert c["potion"]["healing"] == 100 or c["potion"]["healing"] > 0
    assert c["wand"]["wishing"] == 500
    assert quote(20, 12, False) == 20 and quote(20, 12, True) == 27 and quote(80, 9, False) == 107
    assert candidates("scroll", 20, 12) == {"identify"}
    assert "identify" in candidates("scroll", 27, 12) and "light" not in candidates("scroll", 27, 12)
    assert candidates("scroll", 80, 12) >= {"enchant armor", "remove curse"}
    m = SALE.search("You see here a scroll labeled ZELGO MER (for sale, 80 zorkmids).")
    assert m and m.group(2) == "scroll labeled ZELGO MER" and m.group(3) == "80", m
    assert kind("scroll labeled ZELGO MER") == ("scroll", "labeled ZELGO MER")
    assert kind("2 uncursed puce potions") == ("potion", "puce")
    assert kind("scroll of identify") is None
    print("ok")


if __name__ == "__main__":
    if sys.argv[1:] == ["--check"]:
        check()
