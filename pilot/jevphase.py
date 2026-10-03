"""JEV phase dashboard: the games, the failures, Jev's classification of each failure, and our notes.

    python3 -m pilot.jevphase <jev run> [--rules <run on the same seeds>] [--no-jev]

Reads the run records and each game's recording (replay-<name>.html),
finds the failures (the death, and every 300+ turn window with no new
depth, XL or map), asks Jev to classify each one (failure type, best
remedy, whether the state lacked what it needed), merges the hand-written
notes from playground/batch/jev-notes-<run>.md, and writes
playground/batch/jev-phase-<run>.html (and jev-phase.html, the latest).
Jev's answers are cached in jev-phase-<run>.json; --no-jev renders without them.
"""

from __future__ import annotations

import collections
import html
import json
import os
import re
import sys

from .autopsy import windows
from .batch import PLAYGROUND
from .dashboard import CSS

BATCH = os.path.join(PLAYGROUND, "batch")

FAILURE_TYPES = {
    "search_without_payoff": "Hundreds of turns searching walls on a level whose way down was never found",
    "starved_with_a_way_out": "Ran out of food while a known staircase down or uneaten safe food was available",
    "elbereth_not_working": "Kept resting on Elbereth while a monster went on hitting the pilot (the engraving had failed or been smudged)",
    "fought_too_long": "Stayed in melee until HP was critical instead of retreating, praying or writing Elbereth earlier",
    "walked_off_hurt": "Left a safe square or a rest with low HP and a hostile nearby",
    "loot_loop": "Walked toward loot it could not reach or take, again and again",
    "wrong_action_for_the_map": "Explored or probed when searching was needed, or the reverse",
    "bad_luck": "A reasonable choice that lost to dice or an unavoidable monster",
    "other": "None of the above fits",
}
REMEDIES = {
    "add_state_field": "Give Jev a fact it did not have (a new field in the state), then let it decide",
    "rewrite_description": "The fact was there; the action's description did not say clearly enough when to use it",
    "hard_rule_in_code": "Take this decision away from Jev: a code rule should forbid or force the action here",
    "fallback_order": "Jev's first choice was impossible and the engine's fallback to its next choice was the mistake",
    "new_action": "No existing action fits; the engine needs a new one (for example: flee to the stairs up)",
    "engine_bug": "The engine executed the right choice wrongly (pathing, prompt handling, a routine)",
    "no_change": "Nothing to change; this failure is noise",
}
QUESTIONS = {
    "failure_type": {"type": "choice", "instructions": "What kind of failure does `failure` describe? The pilot plays NetHack; "
                     "`failure.actions` counts what it did in the window, `failure.state` is what it knew at the end.",
                     "criteria": FAILURE_TYPES},
    "remedy": {"type": "choice", "instructions": "Which single change would most likely have prevented the failure in `failure`? "
               "Jev chooses the pilot's action each turn from `failure.state`; the engine executes it.",
               "criteria": REMEDIES},
    "state_lacked_information": {"type": "noul", "instructions": "Did `failure.state` lack a fact a careful NetHack player "
                                 "would have needed to avoid this failure?",
                                 "criteria": {"true": "A needed fact is missing from the state",
                                              "false": "The state had what was needed; the choice or its execution was the problem"}},
}


def _load_run(run: str) -> list[dict]:
    with open(os.path.join(BATCH, f"{run}.json")) as f:
        return json.load(f)["games"]


def _recording(name: str) -> dict | None:
    try:
        with open(os.path.join(BATCH, f"replay-{name}.html")) as f:
            m = re.search(r'id="data">(.*?)</script>', f.read(), re.S)
        return json.loads(m.group(1).replace("<\\/", "</")) if m else None
    except OSError:
        return None


def _action(note: str) -> str:
    if note.startswith("jev "):
        return note.split(" ")[1]
    return note.split(":")[0].split(" (")[0]


def _state_at(rec: dict, turn: int) -> dict | None:
    for e in reversed(rec["escs"]):
        if e["t"] <= turn and e["brief"].startswith("{"):
            return json.loads(e["brief"])
    return None


def failures(g: dict, rec: dict) -> list[dict]:
    """The death and every effort-without-progress window, with evidence."""
    F = rec["frames"]
    out = []
    for w in windows(g.get("trace") or []):
        fr = [f for f in F if w["start"] <= f[0] <= w["end"]]
        if not fr:
            continue
        st = _state_at(rec, w["end"]) or {}
        o = st.get("options", {})
        out.append({"kind": "stall", "label": f"T{w['start']}-{w['end']}: {w['turns']} turns with no progress on Dlvl {fr[0][1]}",
                    "turns": [w["start"], w["end"]], "dlvl": fr[0][1], "hunger_at_end": w["hunger"] or "not hungry",
                    "actions": dict(collections.Counter(_action(f[10]) for f in fr).most_common(6)),
                    "hp": [fr[0][2], fr[-1][2], fr[-1][3]], "frame": F.index(fr[-1]),
                    "state": {"level_explored": o.get("level_explored"), "stairs_down_known": o.get("stairs_down_known"),
                              "probe_spots_remain": o.get("probe_spots_remain"), "unsearched_spots_remain": o.get("unsearched_spots_remain"),
                              "safe_food_in_pack": o.get("safe_food_in_pack"), "in_gnomish_mines": o.get("in_gnomish_mines")},
                    "messages": [f[11] for f in fr if f[11]][-5:]})
    if g.get("death"):
        last = F[-40:]
        st = _state_at(rec, last[-1][0]) or {}
        out.append({"kind": "death", "label": f"T{last[-1][0]}: {g['death']} on Dlvl {last[-1][1]} at XL {g.get('xlvl')}",
                    "turns": [last[0][0], last[-1][0]], "dlvl": last[-1][1], "hunger_at_end": last[-1][7] or "not hungry",
                    "actions": dict(collections.Counter(_action(f[10]) for f in last).most_common(6)),
                    "hp": [last[0][2], 0, last[-1][3]], "frame": max(0, len(F) - 40),
                    "state": {"threats": st.get("threats"), "prayer": st.get("prayer"), "options": {k: v for k, v in st.get("options", {}).items()
                              if k in ("safe_food_in_pack", "stairs_down_known", "stairs_up_known", "in_gnomish_mines")}},
                    "messages": [f[11] for f in last if f[11]][-8:],
                    "last_steps": [f"T{f[0]} HP{f[2]}/{f[3]} {f[10]}" for f in last[-12:]]})
    return out


def classify(fail: dict) -> dict | None:
    from .jev import JevEngine, QUESTIONS as _unused  # noqa: F401  (the engine owns the key and the client)
    e = JevEngine.__new__(JevEngine)
    import httpx
    from .jev import TIMEOUT_S, URL, MODEL, _api_key
    e.key, e.client = _api_key(), httpx.Client(timeout=TIMEOUT_S)
    body = {"model": MODEL, "state": {"failure": {k: v for k, v in fail.items() if k not in ("frame", "jev", "note")}},
            "questions": QUESTIONS}
    r = e.client.post(URL, headers={"Authorization": f"Bearer {e.key}"}, json=body)
    r.raise_for_status()
    a = r.json()["answers"]
    return {"type": a["failure_type"]["choice"], "type_p": a["failure_type"]["probabilities"],
            "remedy": a["remedy"]["choice"], "remedy_p": a["remedy"]["probabilities"],
            "lacked_information": a["state_lacked_information"]["noul"]}


def _notes(run: str) -> dict[str, str]:
    """jev-notes-<run>.md: '## <game>' headings, '### <n>' per failure (1-based), '### summary' for the run."""
    path = os.path.join(BATCH, f"jev-notes-{run}.md")
    notes, key, buf = {}, None, []
    try:
        lines = open(path).read().splitlines()
    except OSError:
        return notes
    game = None
    for line in lines + ["## end"]:
        if line.startswith("## ") or line.startswith("### "):
            if key is not None:
                notes[key] = "\n".join(buf).strip()
            buf = []
            if line.startswith("## "):
                game = line[3:].strip()
                key = game
            else:
                key = f"{game}#{line[4:].strip()}"
        else:
            buf.append(line)
    return notes


def _bars(counter: dict, total: int, color: str = "#6ea8fe") -> str:
    rows = []
    for k, v in sorted(counter.items(), key=lambda kv: -kv[1])[:8]:
        rows.append(f'<div class="brow"><span>{html.escape(str(k))}</span><div class="track"><i style="width:{100 * v / max(1, total):.1f}%;background:{color}"></i></div><b>{v}</b></div>')
    return "".join(rows)


def _probs(p: dict, labels: dict) -> str:
    top = sorted(p.items(), key=lambda kv: -kv[1])[:4]
    return "".join(f'<div class="brow"><span title="{html.escape(labels.get(k, ""))}">{html.escape(k)}</span>'
                   f'<div class="track"><i style="width:{100 * v:.0f}%"></i></div><b>{v:.2f}</b></div>' for k, v in top)


def _timeline(rec: dict) -> str:
    F = rec["frames"]
    if not F:
        return ""
    W, H = 600, 70
    tmax = F[-1][0] or 1
    dmax = max(f[1] for f in F) or 1
    hmax = max(f[3] for f in F) or 1
    def X(t): return 36 + (W - 44) * t / tmax
    d, pv = "", None
    for f in F:
        y = 8 + 24 * (f[1] - 1) / max(1, dmax - 1)
        if pv is None: d = f"M{X(f[0]):.1f} {y:.1f}"
        elif f[1] != pv: d += f" H{X(f[0]):.1f} V{y:.1f}"
        pv = f[1]
    d += f" H{X(tmax):.1f}"
    hp = " ".join(f"{'M' if i == 0 else 'L'}{X(f[0]):.1f} {40 + 24 * (1 - max(0, f[2]) / hmax):.1f}" for i, f in enumerate(F))
    return (f'<svg viewBox="0 0 {W} {H}" class="tl"><text x="2" y="12" class="lbl">Dlvl</text><text x="2" y="52" class="lbl">HP</text>'
            f'<path d="{d}" fill="none" stroke="#6ea8fe" stroke-width="2"/><path d="{hp}" fill="none" stroke="#f0b35a" stroke-width="1.2"/>'
            f'<text x="{W - 4}" y="{H - 2}" text-anchor="end" class="lbl">T{tmax}</text></svg>')


def build(run: str, rules_run: str | None, use_jev: bool) -> str:
    games = _load_run(run)
    rules = {g.get("seed"): g for g in _load_run(rules_run)} if rules_run else {}
    cache_path = os.path.join(BATCH, f"jev-phase-{run}.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
    notes = _notes(run)
    sections, compare, totals, calls, secs = [], [], collections.Counter(), 0, 0.0
    for g in games:
        rec = _recording(g["name"])
        calls += g.get("brain_calls", 0); secs += g.get("brain_seconds", 0)
        for k, v in (g.get("stats") or {}).items():
            if k.startswith("jev: ") and "not possible" not in k:
                totals[k[5:]] += v
        r = rules.get(g.get("seed"))
        compare.append((g, r))
        if not rec:
            sections.append(f'<section class="game"><h2>{html.escape(g["name"])}</h2><p class="sub">no recording</p></section>')
            continue
        fails = failures(g, rec)
        cards = []
        for i, fl in enumerate(fails, 1):
            key = f"{g['name']}#{i}"
            if use_jev and key not in cache:
                try:
                    cache[key] = classify(fl)
                except Exception as exc:  # noqa: BLE001
                    cache[key] = {"error": str(exc)[:200]}
            jv = cache.get(key)
            jev_html = "<p class='sub'>not classified yet (run without --no-jev)</p>"
            if jv and "error" in jv:
                jev_html = f"<p class='sub'>Jev call failed: {html.escape(jv['error'])}</p>"
            elif jv:
                jev_html = (f"<div class='col'><h4>Failure type</h4>{_probs(jv['type_p'], FAILURE_TYPES)}"
                            f"<p class='sub'>{html.escape(FAILURE_TYPES.get(jv['type'], ''))}</p></div>"
                            f"<div class='col'><h4>Proposed remedy</h4>{_probs(jv['remedy_p'], REMEDIES)}"
                            f"<p class='sub'>{html.escape(REMEDIES.get(jv['remedy'], ''))}</p>"
                            f"<p class='sub'>State lacked a needed fact: <b>{jv['lacked_information']:.2f}</b></p></div>")
            ev = (f"<div class='kv'><span>Dlvl {fl['dlvl']}</span><span>hunger {html.escape(fl['hunger_at_end'])}</span>"
                  f"<span>HP {fl['hp'][0]} → {fl['hp'][1]} of {fl['hp'][2]}</span></div>"
                  f"<div class='bars'>{_bars(fl['actions'], sum(fl['actions'].values()), '#9aa0a6')}</div>"
                  f"<pre class='state'>{html.escape(json.dumps(fl['state'], indent=1))}</pre>"
                  + ("".join(f"<div class='msg'>{html.escape(m)}</div>" for m in fl["messages"]))
                  + ("".join(f"<div class='step'>{html.escape(s)}</div>" for s in fl.get("last_steps", []))))
            mine = notes.get(key, "")
            cards.append(f"""<div class="fail {fl['kind']}">
<h3>{i}. {html.escape(fl['label'])} <a class="jump" href="replay-{html.escape(g['name'])}.html">open in replay</a></h3>
<div class="cols3">
  <div class="col"><h4>Evidence</h4>{ev}</div>
  <div class="col jev"><h4>Jev's classification</h4>{jev_html}</div>
  <div class="col mine"><h4>Our proposed choice</h4>{('<p>' + html.escape(mine).replace(chr(10) + chr(10), '</p><p>').replace(chr(10), '<br>') + '</p>') if mine else '<p class="sub">no note yet</p>'}</div>
</div></div>""")
        acts = collections.Counter()
        for k, v in (g.get("stats") or {}).items():
            if k.startswith("jev: ") and "not possible" not in k:
                acts[k[5:]] += v
        gnote = notes.get(g["name"], "")
        sections.append(f"""<section class="game">
<h2>{html.escape(g["name"])} <span class="pill {'dead' if g.get('death') else 'stalled'}">{html.escape(g.get('death') or g.get('stall') or '')}</span>
  <a class="jump" href="replay-{html.escape(g['name'])}.html">step-by-step replay</a></h2>
<div class="stats">
  <div class="stat"><b>{g.get('deepest')}</b><span>deepest level</span></div>
  <div class="stat"><b>{g.get('xlvl')}</b><span>experience level</span></div>
  <div class="stat"><b>{int(g.get('turn') or 0):,}</b><span>turns</span></div>
  <div class="stat"><b>{r.get('deepest') if r else '?'}</b><span>rules, same dungeon</span></div>
  <div class="stat"><b>{g.get('brain_calls', 0):,}</b><span>Jev calls</span></div>
</div>
{_timeline(rec)}
<div class="cols2"><div><h4>What Jev chose</h4><div class="bars">{_bars(acts, sum(acts.values()))}</div></div>
<div><h4>Game note</h4>{('<p>' + html.escape(gnote).replace(chr(10), '<br>') + '</p>') if gnote else '<p class="sub">none</p>'}</div></div>
<h3>Failures</h3>{''.join(cards) or '<p class="sub">none found</p>'}
</section>""")
    if use_jev:
        with open(cache_path, "w") as f:
            json.dump(cache, f, indent=1)
    rows = "".join(f"<tr><td>{html.escape(g['name'])}</td><td>{g.get('seed')}</td><td class='num'>{g.get('deepest')}</td><td class='num'>{g.get('xlvl')}</td>"
                   f"<td class='num'>{int(g.get('turn') or 0):,}</td><td>{html.escape(g.get('death') or g.get('stall') or '')}</td>"
                   f"<td class='num'>{r.get('deepest') if r else ''}</td><td class='num'>{r.get('xlvl') if r else ''}</td><td>{html.escape((r.get('death') or r.get('stall') or '') if r else '')}</td></tr>"
                   for g, r in compare)
    summary = notes.get("summary", "")
    avg = lambda key, gs: sum(float(x.get(key) or 0) for x in gs) / max(1, len(gs))
    rg = [r for _, r in compare if r]
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>JEV phase {html.escape(run)}</title><style>{CSS}
.game{{margin:28px 0;padding-top:12px;border-top:1px solid #333}} .fail{{border:1px solid #333;border-radius:8px;padding:10px 14px;margin:10px 0}}
.fail.death{{border-color:#a33}} .cols3{{display:grid;grid-template-columns:1.2fr 1fr 1fr;gap:14px}} .cols2{{display:grid;grid-template-columns:1fr 1fr;gap:14px}}
@media(max-width:900px){{.cols3,.cols2{{grid-template-columns:1fr}}}} .col{{min-width:0}} .col.jev{{background:#1b2230;border-radius:6px;padding:8px 10px}} .col.mine{{background:#23201a;border-radius:6px;padding:8px 10px}}
h4{{margin:6px 0;font-size:.85rem;text-transform:uppercase;letter-spacing:.06em;color:#9aa0a6}} .kv{{display:flex;gap:14px;flex-wrap:wrap;font-size:.9rem}}
.bars{{display:flex;flex-direction:column;gap:3px;margin:6px 0}} .brow{{display:grid;grid-template-columns:150px 1fr 40px;gap:8px;align-items:center;font-size:.85rem}}
.track{{height:9px;background:#2a2d31;border-radius:3px}} .track i{{display:block;height:100%;background:#6ea8fe;border-radius:3px}} .brow b{{text-align:right;font-variant-numeric:tabular-nums}}
pre.state{{font-size:.72rem;background:#15171a;padding:6px;border-radius:4px;white-space:pre-wrap;max-height:160px;overflow:auto}} .msg,.step{{font-size:.78rem;color:#c3c2b7;font-family:ui-monospace,Menlo,monospace}}
.jump{{font-size:.75rem;margin-left:10px;color:#6ea8fe}} .tl{{width:100%;max-width:600px;height:auto;display:block;margin:8px 0}} .lbl{{font-size:10px;fill:#9aa0a6}}
table.cmp{{border-collapse:collapse;font-size:.9rem}} table.cmp td,table.cmp th{{padding:4px 10px;border-bottom:1px solid #333;text-align:left}} td.num{{text-align:right;font-variant-numeric:tabular-nums}}
</style></head><body><main>
<div class="sub"><a href="dashboard.html">&larr; dashboard</a> · JEV phase · run {html.escape(run)}{(' vs rules ' + html.escape(rules_run)) if rules_run else ''}</div>
<h1>JEV phase: {len(games)} games to {max((int(g.get('turn') or 0) for g in games), default=0):,} turns</h1>
<div class="stats">
  <div class="stat"><b>{avg('deepest', games):.2f}</b><span>avg deepest, JEV</span></div>
  <div class="stat"><b>{avg('deepest', rg):.2f}</b><span>avg deepest, rules (same dungeons)</span></div>
  <div class="stat"><b>{avg('xlvl', games):.2f}</b><span>avg XL, JEV</span></div>
  <div class="stat"><b>{calls:,}</b><span>Jev calls</span></div>
  <div class="stat"><b>{(secs / max(1, calls)):.2f}s</b><span>per call</span></div>
</div>
<h2>Game by game</h2>
<table class="cmp"><thead><tr><th>JEV game</th><th>seed</th><th>deepest</th><th>XL</th><th>turns</th><th>end</th><th>rules deepest</th><th>rules XL</th><th>rules end</th></tr></thead><tbody>{rows}</tbody></table>
<h2>What Jev chose, all games</h2><div class="bars" style="max-width:520px">{_bars(totals, sum(totals.values()))}</div>
<h2>Summary and proposed changes</h2>{('<p>' + html.escape(summary).replace(chr(10) + chr(10), '</p><p>').replace(chr(10), '<br>') + '</p>') if summary else '<p class="sub">no summary note yet (playground/batch/jev-notes-' + html.escape(run) + '.md)</p>'}
{''.join(sections)}
<p class="sub">Failure types and remedies are fixed lists; Jev picks from them with probabilities. "Our proposed choice" is written by hand after reading the recordings.</p>
</main></body></html>"""
    out = os.path.join(BATCH, f"jev-phase-{run}.html")
    with open(out, "w") as f:
        f.write(page)
    with open(os.path.join(BATCH, "jev-phase.html"), "w") as f:
        f.write(page)
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    use_jev = "--no-jev" not in args
    rules_run = args[args.index("--rules") + 1] if "--rules" in args else None
    run = [a for a in args if not a.startswith("--") and a != rules_run][0]
    print(build(run, rules_run, use_jev))
