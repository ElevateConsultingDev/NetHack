"""The story: how the pilot's depth moved, with what changed when.

    python3 -m pilot.story            # writes playground/batch/story.html

Two charts. ENGINE: average deepest level of the rules brain on the fixed
seed sets over time, each run a dot, each kept engine fix a marker on the
day it landed (from the git log). BRAIN: the model arms on the test seeds
(with and without conclusions, per brain) so the memory's effect and the
strata can be read as a curve. Every value is also in the tables below.
"""

from __future__ import annotations

import datetime as dt
import html
import json
import os
import subprocess

from .runs import BATCH, HERE, summaries

# Categorical hues in fixed order (light, dark); see the dataviz reference palette.
SERIES = [("#2a78d6", "#3987e5"), ("#eb6834", "#d95926"), ("#1baf7a", "#199e70"), ("#eda100", "#c98500"),
          ("#e87ba4", "#d55181"), ("#008300", "#008300")]
W, H, PAD_L, PAD_R, PAD_T, PAD_B = 900, 300, 44, 120, 16, 36


def run_time(run: str) -> dt.datetime:
    return dt.datetime.strptime(run[:15], "%Y%m%d-%H%M%S")


def kept_fixes() -> list[tuple[dt.datetime, str]]:
    """Engine commits that changed play: feat/fix touching pilot/engine.py or src/."""
    out = subprocess.run(["git", "log", "--format=%ct %s", "--", "pilot/engine.py", "src/hacklib.c"],
                         capture_output=True, text=True, cwd=HERE).stdout
    fixes = []
    for line in out.splitlines():
        ts, _, subject = line.partition(" ")
        if subject.startswith(("feat", "fix", "perf")):
            fixes.append((dt.datetime.fromtimestamp(int(ts)), subject.split(":", 1)[-1].strip()[:70]))
    return sorted(fixes)


def chart(title: str, series: list[tuple[str, list[tuple[dt.datetime, float, str]]]],
          marks: list[tuple[dt.datetime, str]] = ()) -> str:
    """One SVG line chart: series -> [(time, value, tooltip)], marks -> (time, label)."""
    pts = [p for _, s in series for p in s]
    if not pts:
        return f"<p>{html.escape(title)}: no runs yet.</p>"
    t0, t1 = min(p[0] for p in pts), max(p[0] for p in pts)
    if t1 == t0:
        t1 = t0 + dt.timedelta(hours=1)
    lo, hi = 0.0, max(6.0, max(p[1] for p in pts) + 0.5)
    x = lambda t: PAD_L + (W - PAD_L - PAD_R) * ((t - t0).total_seconds() / (t1 - t0).total_seconds())
    y = lambda v: PAD_T + (H - PAD_T - PAD_B) * (1 - (v - lo) / (hi - lo))
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{html.escape(title)}">']
    for v in range(int(lo), int(hi) + 1):  # recessive hairline grid, clean ticks
        out.append(f'<line class="grid" x1="{PAD_L}" x2="{W - PAD_R}" y1="{y(v):.1f}" y2="{y(v):.1f}"/>'
                   f'<text class="tick" x="{PAD_L - 6}" y="{y(v) + 4:.1f}" text-anchor="end">{v}</text>')
    for t, label in marks:  # kept fixes: a small triangle on the baseline with the subject in its tooltip
        out.append(f'<g class="mark"><title>{html.escape(t.strftime("%m-%d %H:%M"))}: {html.escape(label)}</title>'
                   f'<path d="M{x(t):.1f},{H - PAD_B - 8} l4,8 l-8,0 z"/></g>')
    legend = []
    for i, (name, s) in enumerate(series):
        c = SERIES[i % len(SERIES)]
        cls = f"s{i}"
        d = " ".join(f"{'M' if k == 0 else 'L'}{x(t):.1f},{y(v):.1f}" for k, (t, v, _) in enumerate(s))
        out.append(f'<path class="line {cls}" d="{d}"/>')
        for t, v, tip in s:
            out.append(f'<g class="dot {cls}"><title>{html.escape(tip)}</title>'
                       f'<circle class="ring" cx="{x(t):.1f}" cy="{y(v):.1f}" r="6"/>'
                       f'<circle cx="{x(t):.1f}" cy="{y(v):.1f}" r="4"/></g>')
        t, v, _ = s[-1]
        out.append(f'<text class="label" x="{x(t) + 10:.1f}" y="{y(v) + 4:.1f}">{html.escape(name)} {v:.2f}</text>')
        legend.append(f'<span><i class="key {cls}"></i>{html.escape(name)}</span>')
    out.append("</svg>")
    style = "".join(f".s{i}{{--c:{c[0]};--cd:{c[1]}}}" for i, c in enumerate(SERIES))
    return (f'<section><h2>{html.escape(title)}</h2><div class="legend">{"".join(legend)}</div>'
            f'{"".join(out)}<style>{style}</style></section>')


def table(title: str, rows: list[tuple]) -> str:
    body = "".join("<tr>" + "".join(f"<td>{html.escape(str(c))}</td>" for c in r) + "</tr>" for r in rows)
    return (f'<details><summary>{html.escape(title)}: table</summary><table><tr><th>run</th><th>brain</th><th>seed</th>'
            f'<th>games</th><th>avg deepest</th><th>avg XL</th><th>conclusions</th></tr>{body}</table></details>')


def main() -> None:
    runs = summaries()
    fixes = kept_fixes()
    # ENGINE: rules brain, 64-game runs, one series per seed set.
    engine = []
    for seed, name in ((1000, "seed 1000 (decisions)"), (5000, "seed 5000 (held out)")):
        pts = [(run_time(r["run"]), r["deepest"], f"{r['run']}: deepest {r['deepest']:.2f}, XL {r['xl']:.2f}, {r['games']} games")
               for r in sorted(runs, key=lambda r: r["run"])
               if r["brain"] == "rules" and r["seed"] == seed and r["games"] == 64]
        if pts:
            engine.append((name, pts))
    # BRAIN: model arms on the test seeds, one series per brain and condition.
    brain = []
    for b in ("haiku", "qwen"):
        for with_c in (True, False):
            name = f"{b} {'with' if with_c else 'without'} conclusions"
            pts = [(run_time(r["run"]), r["deepest"], f"{r['run']}: deepest {r['deepest']:.2f}, XL {r['xl']:.2f}, "
                    f"{r['games']} games, {r['calls']} brain calls, {r['failed']} failed"
                    + (f", stratum {os.path.basename(r['conclusions'])}" if r.get("conclusions") else ""))
                   for r in sorted(runs, key=lambda r: r["run"])
                   if r["brain"] == b and r["seed"] == 3000 and r["games"] >= 32 and bool(r["journal"]) == with_c]
            if pts:
                brain.append((name, pts))
    rows = [(r["run"], r["brain"] + (" " + r["model"] if r.get("model") else ""), r["seed"], r["games"],
             f"{r['deepest']:.2f}", f"{r['xl']:.2f}", "no" if r["journal"] is False else (os.path.basename(r["conclusions"]) if r.get("conclusions") else "yes"))
            for r in sorted(runs, key=lambda r: r["run"], reverse=True)]
    page = f"""<!doctype html><html><head><meta charset="utf-8"><title>Pilot story</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
:root{{--bg:#fcfcfb;--ink:#0b0b0b;--ink2:#52514e;--grid:#e6e5e1;--mark:#9b9a95}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]){{--bg:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#333331;--mark:#6f6e69}}}}
:root[data-theme="dark"]{{--bg:#1a1a19;--ink:#fff;--ink2:#c3c2b7;--grid:#333331;--mark:#6f6e69}}
body{{margin:0;padding:16px;background:var(--bg);color:var(--ink);font:15px/1.4 -apple-system,Helvetica,Arial,sans-serif;max-width:960px}}
h1{{font-size:22px;margin:0 0 4px}} h2{{font-size:16px;margin:24px 0 6px}} p.sub{{color:var(--ink2);margin:0 0 12px}}
svg{{width:100%;height:auto;display:block}} .grid{{stroke:var(--grid);stroke-width:1}} .tick{{fill:var(--ink2);font-size:11px}}
.line{{fill:none;stroke:var(--c);stroke-width:2;stroke-linejoin:round;stroke-linecap:round}}
.dot circle{{fill:var(--c)}} .dot .ring{{fill:var(--bg)}} .dot:hover circle:not(.ring){{r:6}}
.label{{fill:var(--ink2);font-size:12px}} .mark path{{fill:var(--mark)}} .mark:hover path{{fill:var(--ink)}}
@media (prefers-color-scheme: dark){{:root:not([data-theme="light"]) .line{{stroke:var(--cd)}} :root:not([data-theme="light"]) .dot circle:not(.ring){{fill:var(--cd)}}}}
.legend span{{margin-right:14px;color:var(--ink2);font-size:13px}} .key{{display:inline-block;width:14px;height:2px;background:var(--c);vertical-align:middle;margin-right:5px}}
details{{margin:8px 0 16px}} table{{border-collapse:collapse;font-size:13px}} td,th{{padding:3px 10px;border-bottom:1px solid var(--grid);text-align:left}}
</style></head><body>
<h1>Pilot story</h1><p class="sub">Average deepest level per run. Dots are runs (hover for the numbers); the small triangles are the engine commits that changed play (hover for the subject). Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}.</p>
{chart("Engine: rules brain on the fixed seed sets (64 games each)", engine, fixes)}
{chart("Brain: model arms on the test seeds (seed 3000, same 32 dungeons)", brain)}
{table("All runs", rows)}
<p class="sub">The brain chart is the Stratigraph's report card: a rising "with conclusions" line while "without" stays flat means the strata are teaching something that transfers.</p>
</body></html>"""
    path = os.path.join(BATCH, "story.html")
    with open(path, "w") as f:
        f.write(page)
    print(f"wrote {path}: {len(runs)} runs, {len(fixes)} engine commits")


if __name__ == "__main__":
    main()
