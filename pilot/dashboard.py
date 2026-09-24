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
import threading
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
.card { display:block; color:inherit; text-decoration:none; background:var(--card); border:1px solid var(--line);
        border-radius:8px; padding:10px 12px; overflow:hidden; }
a.card:hover { border-color:var(--accent); }
a { color:var(--accent); }
.big { font:13px/1.15 ui-monospace, Menlo, monospace; padding:10px; }
.m-you { color:var(--ink); font-weight:700; background:rgba(255,200,0,.35); } .m-mon { color:var(--bad); font-weight:600; }
.m-pet { color:var(--ok); font-weight:600; } .m-obj { color:var(--warn); } .m-feat { color:var(--accent); }
.m-trap { color:#c14fd6; } .cols { display:grid; grid-template-columns:minmax(0,3fr) minmax(260px,1fr); gap:16px; }
@media (max-width: 900px) { .cols { grid-template-columns:1fr; } }
.feed { font-size:12px; max-height:420px; overflow:auto; background:var(--card); border:1px solid var(--line);
        border-radius:8px; padding:8px 10px; }
.feed div { padding:2px 0; border-bottom:1px dashed var(--line); } .feed .t { color:var(--dim); margin-right:6px; }
.f-brain { color:var(--accent); } .f-pilot { color:var(--dim); }
.inv { font-size:12px; background:var(--card); border:1px solid var(--line); border-radius:8px; padding:8px 10px; }
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
.north { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:16px; margin-bottom:22px; }
.ladder { display:grid; grid-template-columns:repeat(auto-fill, minmax(300px, 1fr)); gap:4px 24px; margin-top:14px; }
.rung { display:grid; grid-template-columns:150px 1fr 36px; gap:8px; align-items:center; font-size:12px; color:var(--dim); }
.rung i { display:block; height:8px; border-radius:3px; background:var(--line); }
.rung.got { color:var(--ink); } .rung.got i { background:var(--ok); }
.rung b { text-align:right; font-variant-numeric:tabular-nums; }
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
    return (f'<a class="card" href="game-{html.escape(g.name)}.html">'
            f'<h3>{html.escape(g.name)} <span class="pill {state}">{label}</span></h3>'
            f'<div class="meta">{meta}</div><div class="note">{html.escape(why)}</div>'
            f'<pre>{_map_text(g.last or {})}</pre></a>')


# NetHack 3.6 xlogfile "achieve" bits.
ACHIEVE = [(0x0200, "Mines' End"), (0x0400, "Sokoban prize"), (0x0800, "killed Medusa"),
           (0x0002, "entered Gehennom"), (0x0020, "got the Amulet"), (0x0100, "ASCENDED")]


def _all_games(batch_dir: str) -> list[dict]:
    """Every batch game ever: CSV rows, with achievements from the xlogfile."""
    xlog = {}
    try:
        with open(os.path.join(os.path.dirname(batch_dir), "xlogfile")) as f:
            for line in f:
                rec = dict(kv.split("=", 1) for kv in line.rstrip("\n").split("\t") if "=" in kv)
                xlog[rec.get("name", "")] = rec
    except FileNotFoundError:
        pass
    games = []
    for path in sorted(glob.glob(os.path.join(batch_dir, "*.csv"))):
        with open(path) as f:
            for r in csv.DictReader(f):
                rec = xlog.get(r["name"], {})
                r["achieve"] = int(rec.get("achieve", "0"), 16) if rec.get("achieve", "0").startswith("0x") \
                    else int(rec.get("achieve", "0") or 0)
                r["run"] = os.path.basename(path)[:-4]
                games.append(r)
    return games


def _num(v) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def _north_star(batch_dir: str) -> str:
    games = _all_games(batch_dir)
    if not games:
        return ""
    n = len(games)
    deep = [_num(g.get("maxlvl")) for g in games]
    xl = [_num(g.get("xlvl")) for g in games]
    turns = [_num(g.get("turn")) for g in games]
    points = [_num(g.get("points")) for g in games]
    runs = sorted({g["run"] for g in games})
    last = [g for g in games if g["run"] == runs[-1]]
    last_deep = sum(_num(g.get("maxlvl")) for g in last) / len(last)
    all_deep = sum(deep) / n
    trend = "▲" if last_deep > all_deep + 0.05 else "▼" if last_deep < all_deep - 0.05 else "="

    def rung(label, hit):
        k = sum(1 for g in games if hit(g))
        pct = 100 * k / n
        return (f'<div class="rung{" got" if k else ""}"><span>{html.escape(label)}</span>'
                f'<i style="width:{max(pct, 0.6 if k else 0):.1f}%"></i><b>{k}</b></div>')
    ladder = [rung(f"reached Dlvl {d}", lambda g, d=d: _num(g.get("maxlvl")) >= d) for d in (3, 5, 10, 15, 20)]
    ladder += [rung(f"reached XL {x}", lambda g, x=x: _num(g.get("xlvl")) >= x) for x in (5, 10)]
    ladder += [rung(f"survived {t:,} turns", lambda g, t=t: _num(g.get("turn")) >= t) for t in (5000, 10000, 20000)]
    ladder += [rung(label, lambda g, b=b: g["achieve"] & b) for b, label in ACHIEVE]
    return f"""<section class="north">
<h2 style="margin-top:0">North star: how well the pilot plays (all {n} games, {len(runs)} runs)</h2>
<div class="stats">
  <div class="stat"><b>{max(deep):.0f}</b><span>deepest level ever</span></div>
  <div class="stat"><b>{max(xl):.0f}</b><span>highest XL ever</span></div>
  <div class="stat"><b>{max(turns):,.0f}</b><span>longest game (turns)</span></div>
  <div class="stat"><b>{max(points):,.0f}</b><span>best score</span></div>
  <div class="stat"><b>{all_deep:.1f}</b><span>avg deepest level, all time</span></div>
  <div class="stat"><b>{last_deep:.1f} {trend}</b><span>avg deepest, latest run</span></div>
</div>
<div class="ladder">{''.join(ladder)}</div>
<div class="sub">Each bar: games (of {n}) that reached the milestone. Winning = ASCENDED.</div>
</section>"""


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
{_north_star(batch_dir)}
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
    tmp = f"{path}.{threading.get_ident()}.tmp"  # One per writer: the refresher and a worker can collide.
    with open(tmp, "w") as f:
        f.write(page)
    os.replace(tmp, path)


KIND_CLASS = {"you": "m-you", "monster": "m-mon", "pet": "m-pet", "object": "m-obj",
              "feature": "m-feat", "trap": "m-trap", "invisible": "m-mon"}


def _map_html(state: dict) -> str:
    """The map with each named cell colored by what it is (hover for its name)."""
    kinds = {(c["x"], c["y"]): (KIND_CLASS.get(c["kind"], ""), c["name"]) for c in state.get("cells", [])}
    lines = []
    for y, row in enumerate(state.get("map", [])):
        if not row.strip():
            continue
        out = []
        for x, ch in enumerate(row.rstrip(), start=1):
            cls, name = kinds.get((x, y), ("", ""))
            text = html.escape(ch)
            out.append(f'<span class="{cls}" title="{html.escape(name)}">{text}</span>' if cls else text)
        lines.append("".join(out))
    return "\n".join(lines) or "(no map yet)"


def write_game(path: str, g, run: str) -> None:
    """A live page for one game: big colored map, status, inventory, feed."""
    s = g.last or {}
    st = s.get("status", {})
    if g.result is None:
        state, label = "playing", "playing"
    elif g.result.get("death"):
        state, label = "dead", "died: " + g.result["death"]
    elif g.stall:
        state, label = "stalled", "stalled: " + g.stall
    else:
        state, label = "done", "ended"
    inv = "".join(f"<div>{html.escape(i['letter'])} - {html.escape(i['text'])}</div>" for i in s.get("inventory", []))
    feed = "".join(f'<div class="f-{kind}"><span class="t">T{t}</span>{html.escape(text)}</div>'
                   for t, kind, text in g.feed)  # Oldest first; the newest is at the bottom.
    routine = g.engine.routine or "default activity"
    refresh = '<meta http-equiv="refresh" content="1">' if g.result is None else ""
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">{refresh}
<title>Pilot Game</title><style>{CSS}</style></head><body><main>
<div class="sub"><a href="dashboard.html">&larr; all games</a> · run {html.escape(run)}</div>
<h1>{html.escape(g.name)} <span class="pill {state}">{html.escape(label)}</span></h1>
<div class="stats">
  <div class="stat"><b>{st.get('dlvl', '?')}</b><span>dungeon level</span></div>
  <div class="stat"><b>{st.get('xlvl', '?')}</b><span>experience level</span></div>
  <div class="stat"><b>{st.get('hp', '?')}/{st.get('hpmax', '?')}</b><span>HP</span></div>
  <div class="stat"><b>{st.get('turn', 0):,}</b><span>turn</span></div>
  <div class="stat"><b>{st.get('ac', '?')}</b><span>AC</span></div>
  <div class="stat"><b>${st.get('gold', 0)}</b><span>gold</span></div>
  <div class="stat"><b>{html.escape(st.get('hunger', '') or 'fed')}</b><span>{html.escape(' '.join(st.get('conditions', [])) or 'hunger')}</span></div>
</div>
<p class="note"><b>Now:</b> {html.escape(routine)}: {html.escape(g.engine.note or '')}</p>
<div class="cols">
  <div><pre class="big">{_map_html(s)}</pre>
    <p class="sub">Highlighted @ is you · red monsters · green your pet · amber items · blue features. Hover a symbol for its name.</p></div>
  <div><h2 style="margin-top:0">Feed</h2><div class="feed" id="feed">{feed or '<span class=sub>nothing yet</span>'}</div>
    <h2>Inventory</h2><div class="inv">{inv or '<span class=sub>empty</span>'}</div></div>
</div>
<script>
// Keep the feed pinned to the newest line across refreshes, unless the
// reader has scrolled up; then keep their place until they scroll back down.
(() => {{
  const feed = document.getElementById("feed");
  let saved = null;
  try {{ saved = JSON.parse(sessionStorage.getItem("feed-scroll") || "null"); }} catch (e) {{}}
  if (saved && saved.pinned === false) feed.scrollTop = saved.top;
  else feed.scrollTop = feed.scrollHeight;
  feed.addEventListener("scroll", () => {{
    const pinned = feed.scrollTop + feed.clientHeight >= feed.scrollHeight - 12;
    try {{ sessionStorage.setItem("feed-scroll", JSON.stringify({{pinned, top: feed.scrollTop}})); }} catch (e) {{}}
  }});
}})();
</script>
</main></body></html>"""
    tmp = f"{path}.{threading.get_ident()}.tmp"  # One per writer: the refresher and a worker can collide.
    with open(tmp, "w") as f:
        f.write(page)
    os.replace(tmp, path)
