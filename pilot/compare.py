"""Compare two batch runs game by game (same --seed: same dungeons).

    python3 -m pilot.compare <run_a> <run_b>

SAME means every key matched (the change never touched that game).
"""

from __future__ import annotations

import collections
import json
import os
import statistics
import sys

from .batch import PLAYGROUND


def load(run: str) -> list[dict]:
    with open(os.path.join(PLAYGROUND, "batch", f"{run}.json")) as f:
        return json.load(f)["games"]


def summary(games: list[dict]) -> str:
    n = len(games) or 1
    avg = lambda k: sum(float(g.get(k) or 0) for g in games) / n
    buckets = collections.Counter(g["bucket"] for g in games)
    return (f"deepest {avg('maxlvl'):.2f}  XL {avg('xlvl'):.2f}  turns {avg('turn'):.0f}  "
            + ", ".join(f"{k} {v}" for k, v in buckets.most_common()))


def game(name: str) -> str:
    """The game's index within its run: names are "B" + six digits of the run id + the index
    (two digits, three from game 100 on), so the last two characters collide in a 128-game run."""
    return name[7:]


def diffs(a: list[dict], b: list[dict], key: str) -> list[float]:
    """Per-game differences b minus a, games matched by their index."""
    after = {game(g["name"]): g for g in b}
    out = []
    for g in a:
        k = game(g["name"])
        if k in after:
            out.append(float(after[k].get(key) or 0) - float(g.get(key) or 0))
    return out


def mean_se(d: list[float]) -> tuple[float, float]:
    if len(d) < 2:
        return (d[0] if d else 0.0), 0.0
    return statistics.mean(d), statistics.stdev(d) / len(d) ** 0.5


def pool(pairs: list[tuple[list[dict], list[dict]]]) -> dict:
    """Campaign 2's keep rule (specs/PILOT-SPEC.md): pool the per-game differences of both sets.
    keep: pooled depth gain >= 2 SE, no set falls by more than its own 2 SE, pooled XL not down 2 SE.
    flat: pooled depth change no worse than -1 SE (the bucket clause may keep it). Otherwise drop."""
    sets, all_d, all_x = [], [], []
    for a, b in pairs:
        d, x = diffs(a, b, "maxlvl"), diffs(a, b, "xlvl")
        sets.append((mean_se(d), mean_se(x), len(d)))
        all_d += d
        all_x += x
    (dm, ds), (xm, xs) = mean_se(all_d), mean_se(all_x)
    set_ok = all(m >= -2 * se for (m, se), _, _ in sets)
    if dm >= 2 * ds and ds > 0 and set_ok and xm >= -2 * xs:
        verdict = "keep"
    elif dm >= -ds:
        verdict = "flat"
    else:
        verdict = "drop"
    return {"sets": sets, "depth": (dm, ds), "xl": (xm, xs), "n": len(all_d), "verdict": verdict}


def check() -> None:
    mk = lambda depths, xls=None: [{"name": f"B000000{i:02d}", "maxlvl": d, "xlvl": (xls or depths)[i]} for i, d in enumerate(depths)]
    base = mk([5] * 40)
    up = mk([6] * 20 + [5] * 20)
    r = pool([(base, up), (base, up)])
    assert r["verdict"] == "keep" and abs(r["depth"][0] - 0.5) < 1e-9, r
    r = pool([(base, base), (base, base)])
    assert r["verdict"] == "flat", r
    down = mk([4] * 30 + [5] * 10)
    r = pool([(base, up), (base, down)])
    assert r["verdict"] == "drop", r
    big = [{"name": f"B123456{i:02d}", "maxlvl": 5, "xlvl": 5} for i in range(128)]
    other = [{"name": f"B654321{i:02d}", "maxlvl": 5, "xlvl": 5} for i in range(128)]
    assert len(diffs(big, other, "maxlvl")) == 128  # matched by index across runs, 100+ included
    print("ok")


def main() -> None:
    if sys.argv[1:] == ["--check"]:
        check()
        return
    if sys.argv[1:2] == ["--pool"]:
        runs = sys.argv[2:]
        assert len(runs) % 2 == 0, "--pool takes pairs: base1 cand1 base2 cand2 ..."
        pairs = [(load(runs[i]), load(runs[i + 1])) for i in range(0, len(runs), 2)]
        for i, (a, b) in enumerate(pairs):
            print(f"set {i + 1}: {runs[2 * i]} -> {runs[2 * i + 1]}")
            print("  before", summary(a))
            print("  after ", summary(b))
        r = pool(pairs)
        for i, ((dm, ds), (xm, xs), n) in enumerate(r["sets"]):
            print(f"set {i + 1}: deepest {dm:+.2f} +/- {ds:.2f}, XL {xm:+.2f} +/- {xs:.2f} (n={n})")
        print(f"pooled: deepest {r['depth'][0]:+.2f} +/- {r['depth'][1]:.2f}, XL {r['xl'][0]:+.2f} +/- {r['xl'][1]:.2f} "
              f"(n={r['n']}): {r['verdict']}")
        return
    a, b = load(sys.argv[1]), load(sys.argv[2])
    print("before", summary(a))
    print("after ", summary(b))
    after = {game(g["name"]): g for g in b}
    # Game by game on the same seeds: the mean difference and its standard
    # error say whether a change is real or noise (|diff| < 2 SE: noise).
    pairs = [(float(g.get("maxlvl") or 0), float(after[game(g["name"])].get("maxlvl") or 0),
              float(g.get("xlvl") or 0), float(after[game(g["name"])].get("xlvl") or 0))
             for g in a if game(g["name"]) in after]
    for label, i in (("deepest", 0), ("XL", 2)):
        d = [p[i + 1] - p[i] for p in pairs]
        if len(d) > 1:
            mean, se = statistics.mean(d), statistics.stdev(d) / len(d) ** 0.5
            verdict = "real" if abs(mean) >= 2 * se and se > 0 else "noise"
            print(f"{label} change {mean:+.2f} +/- {se:.2f} (n={len(d)}, better {sum(x > 0 for x in d)}, "
                  f"worse {sum(x < 0 for x in d)}): {verdict}")
    for g in a:
        h = after.get(game(g["name"]))
        if h is None:
            continue
        same = g.get("keys") == h.get("keys")
        print(f"{game(g['name'])} {'SAME' if same else 'diff'} {g['bucket'][:22]:22} max{g['maxlvl']} T{g['turn']:>5}"
              f" -> {h['bucket'][:22]:22} max{h['maxlvl']} T{h['turn']:>5}"
              + ("" if same else "  " + (h.get("death") or h.get("stall") or "")[:40]))


if __name__ == "__main__":
    main()
