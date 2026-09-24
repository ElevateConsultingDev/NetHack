"""A live HTML dashboard for batch runs: playground/batch/dashboard.html.

Self-contained and self-refreshing (meta refresh), so it works straight
from the file system with no server. The batch runner rewrites it every
few seconds while games run and once more at the end.
"""

from __future__ import annotations

import csv
import glob
import html
import os
import time

REFRESH_S = 3

CSS = """
:root { --bg:#f6f5f2; --card:#fff; --ink:#1d1d1f; --dim:#6b6b70; --line:#e2e0da;
        --ok:#2f7d4f; --warn:#b7791f; --bad:#b83232; --map:#faf9f6; --accent:#3b5bdb; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#16171a; --card:#1f2024; --ink:#ececf0; --dim:#9a9aa3; --line:#2e2f35;
          --ok:#5cc58a; --warn:#e0b050; --bad:#ef6b6b; --map:#18191c; --accent:#8aa2ff; } }
* { box-sizing: border-box; }
body { margin:0; background:var(--bg); color:var(--ink);
       font:14px/1.45 -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
main { max-width:1400px; margin:0 auto; padding:20px 16px 40px; }
h1 { font-size:20px; margin:0 0 4px; } h2 { font-size:15px; margin:28px 0 10px; }
.sub { color:var(--dim); font-size:13px; }
.stats { display:flex; flex-wrap:wrap; gap:10px; margin-top:12px; }
.stat { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 14px; min-width:120px; }
.stat b { display:block; font-size:22px; font-variant-numeric:tabular-nums; }
.stat span { color:var(--dim); font-size:12px; }
.grid { display:grid; grid-template-columns:repeat(auto-fill, minmax(330px, 1fr)); gap:12px; }
.card { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 12px; overflow:hidden; }
.card h3 { font-size:13px; margin:0; display:flex; justify-content:space-between; gap:8px; }
.pill { font-size:11px; padding:1px 7px; border-radius:99px; border:1px solid currentColor; white-space:nowrap; }
.playing { color:var(--accent); } .dead { color:var(--bad); } .stalled { color:var(--warn); } .done { color:var(--ok); }
.meta { color:var(--dim); font-size:12px; margin:4px 0 6px; font-variant-numeric:tabular-nums; }
.note { font-size:12px; margin-bottom:6px; min-height:1.4em; }
pre { background:var(--map); border:1px solid var(--line); border-radius:6px; margin:0;
      font:9px/1.05 ui-monospace, Menlo, monospace; padding:6px; overflow-x:auto; }
.bars { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 14px; }
.bar { display:grid; grid-template-columns:130px 1fr 44px; gap:8px; align-items:center; font-size:12px; margin:3px 0; }
.bar i { display:block; height:10px; background:var(--accent); border-radius:3px; }
table { width:100%; border-collapse:collapse; background:var(--card); border:1px solid var(--line);
        border-radius:8px; font-size:12px; font-variant-numeric:tabular-nums; }
th, td { text-align:left; padding:6px 10px; border-bottom:1px solid var(--line); vertical-align:top; }
th { color:var(--dim); font-weight:600; }
.ends li { margin:2px 0; } ul.ends { margin:0; padding-left:18px; }
"""


def _map_text(state: dict) -> str:
    rows = [r.rstrip() for r in state.get("map", [])]
    rows = [r for r in rows if r.strip()] or ["(no map yet)"]
    return html.escape("\n".join(rows))


def _game_card(g) -> str:
    st = g.last.get("status", {}) if g.last else {}
    if g.result is None:
        state, label = "playing", "playing"
    elif g.result.get("death"):
        state, label = "dead", "died"
    elif g.stall:
        state, label = "stalled", "stalled"
    else:
        state, label = "done", "ended"
    why = g.result.get("death") if g.result and g.result.get("death") else (g.stall or g.engine.note or "")
    meta = (f"Dlvl {st.get('dlvl', '?')} · XL {st.get('xlvl', '?')} · HP {st.get('hp', '?')}/{st.get('hpmax', '?')} · "
            f"T{st.get('turn', 0)} · ${st.get('gold', 0)} {html.escape(st.get('hunger', '') or '')}")
    return (f'<div class="card"><h3>{html.escape(g.name)} <span class="pill {state}">{label}</span></h3>'
            f'<div class="meta">{meta}</div><div class="note">{html.escape(why)}</div>'
            f'<pre>{_map_text(g.last or {})}</pre></div>')


def _history(batch_dir: str) -> str:
    rows = []
    for path in sorted(glob.glob(os.path.join(batch_dir, "*.csv")))[-20:][::-1]:
        with open(path) as f:
            games = list(csv.DictReader(f))
        if not games:
            continue

        def avg(key):
            vals = [float(r[key]) for r in games if r.get(key) not in ("", None, "None")]
            return f"{sum(vals) / len(vals):.1f}" if vals else "-"
        ends: dict[str, int] = {}
        for r in games:
            e = (r.get("death") or ("stalled: " + r.get("stall", "")))[:60]
            ends[e] = ends.get(e, 0) + 1
        top = "; ".join(f"{n}× {html.escape(e)}" for e, n in sorted(ends.items(), key=lambda kv: -kv[1])[:3])
        run = os.path.basename(path)[:-4]
        rows.append(f"<tr><td>{run}</td><td>{len(games)}</td><td>{avg('maxlvl')}</td><td>{avg('xlvl')}</td>"
                    f"<td>{avg('turn')}</td><td>{top}</td></tr>")
    return ("<table><tr><th>Run</th><th>Games</th><th>Avg deepest</th><th>Avg XL</th><th>Avg turns</th>"
            "<th>Most common endings</th></tr>" + "".join(rows) + "</table>") if rows else "<p class=sub>No runs yet.</p>"


def write(path: str, run: str, brain: str, games: list, batch_dir: str) -> None:
    finished = [g for g in games if g.result is not None]
    playing = [g for g in games if g.result is None and g.last]
    turns = [g.last.get("status", {}).get("turn", 0) for g in games if g.last]
    depths = [g.last.get("status", {}).get("dlvl", 0) for g in games if g.last]
    xls = [g.last.get("status", {}).get("xlvl", 0) for g in games if g.last]
    spent: dict[str, int] = {}
    for g in games:
        for k, v in g.engine.memory.stats.items():
            if k.startswith("turns: "):
                spent[k[7:]] = spent.get(k[7:], 0) + v
    total = sum(spent.values()) or 1
    bars = "".join(f'<div class="bar"><span>{html.escape(k)}</span><i style="width:{100 * v / total:.1f}%"></i>'
                   f"<span>{100 * v / total:.0f}%</span></div>"
                   for k, v in sorted(spent.items(), key=lambda kv: -kv[1])[:10])

    def avg(xs):
        return f"{sum(xs) / len(xs):.1f}" if xs else "-"
    done_note = "all games finished" if len(finished) == len(games) else f"{len(playing)} playing"
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_S}">
<title>Pilot Runs</title><style>{CSS}</style></head><body><main>
<h1>NetHack pilot: run {html.escape(run)}</h1>
<div class="sub">{len(games)} games · {brain} brain · {done_note} · updated {time.strftime('%H:%M:%S')}</div>
<div class="stats">
  <div class="stat"><b>{avg(depths)}</b><span>avg dungeon level</span></div>
  <div class="stat"><b>{avg(xls)}</b><span>avg experience level</span></div>
  <div class="stat"><b>{avg(turns)}</b><span>avg turns</span></div>
  <div class="stat"><b>{sum(1 for g in finished if g.result.get('death'))}</b><span>died</span></div>
  <div class="stat"><b>{sum(1 for g in finished if g.stall)}</b><span>stalled</span></div>
</div>
<h2>Where the turns go</h2><div class="bars">{bars or '<span class=sub>no turns yet</span>'}</div>
<h2>Games</h2><div class="grid">{''.join(_game_card(g) for g in games)}</div>
<h2>Past runs</h2>{_history(batch_dir)}
</main></body></html>"""
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        f.write(page)
    os.replace(tmp, path)
