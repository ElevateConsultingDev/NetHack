"""The tactics page: what the pilot decided, what it predicted, and what happened.

    python3 -m pilot.tacticspage <run>     # writes playground/batch/tactics-<run>.html and tactics.html

Laid out after jev-doom's dashboard (docs/pilot-tactics-design.md, section 2.1): the run and its
controller, a game's decisions, the chosen tactic with its prediction and measured outcome, the
feasible menu and what was omitted, Jev's raw probabilities when it was asked, the ledger across
the run, the last tactic before each death (the raw material for investigation), and calls.
`pilot.batch` writes it at the end of every run.
"""

from __future__ import annotations

import html
import json
import os
import sys

from .dashboard import CSS
from .engine import DEFAULT_ORDERS
from .jev import USD_PER_INPUT_TOKEN, spent
from .ledger import BATCH, rows, table
from .tactics import PREDICTION

EXTRA = """
.panels { display:grid; grid-template-columns:minmax(220px,1fr) minmax(0,2fr) minmax(0,2fr); gap:12px; align-items:start; }
@media (max-width: 1100px) { .panels { grid-template-columns:1fr; } }
.panel { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:10px 12px; min-width:0; }
.panel h3 { margin:0 0 8px; font-size:12px; letter-spacing:.06em; text-transform:uppercase; color:var(--dim); }
.list { max-height:560px; overflow:auto; font-size:12.5px; }
.row { display:flex; gap:8px; padding:4px 6px; border-radius:5px; cursor:pointer; font-variant-numeric:tabular-nums; }
.row:hover { background:rgba(127,127,127,.12); } .row.on { outline:1px solid var(--accent); background:rgba(127,127,127,.12); }
.row .t { color:var(--dim); width:54px; flex:none; } .grow { flex:1; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.tag { font-size:11px; padding:1px 7px; border-radius:9px; border:1px solid var(--line); white-space:nowrap; }
.met { color:var(--ok); border-color:var(--ok); } .not_met { color:var(--bad); border-color:var(--bad); }
.unknown, .ended_early { color:var(--dim); }
table { border-collapse:collapse; width:100%; font-size:12.5px; font-variant-numeric:tabular-nums; }
th, td { text-align:right; padding:3px 8px; border-bottom:1px solid var(--line); } th:nth-child(-n+2), td:nth-child(-n+2) { text-align:left; }
th { color:var(--dim); font-weight:500; } .bar { display:inline-block; height:8px; background:var(--bad); border-radius:2px; vertical-align:middle; }
.kv { display:grid; grid-template-columns:auto 1fr; gap:3px 12px; font-size:13px; } .kv span:nth-child(odd) { color:var(--dim); }
.p { display:grid; grid-template-columns:90px 1fr 44px; gap:6px; align-items:center; font-size:12.5px; margin:3px 0; }
.p i { display:block; height:8px; background:var(--accent); border-radius:2px; }
button.by { font:inherit; font-size:12px; padding:2px 9px; border-radius:9px; border:1px solid var(--line); background:none; color:var(--ink); cursor:pointer; }
button.by.on { border-color:var(--accent); color:var(--accent); }
.flow { display:flex; flex-wrap:wrap; align-items:stretch; gap:4px; font-size:12px; }
.node { border:1px solid var(--line); border-radius:6px; padding:5px 8px; max-width:190px; } .node b { display:block; font-size:11px; color:var(--dim); font-weight:500; }
.node.jev { border-color:#e08a2c; background:rgba(224,138,44,.12); } .arrow { align-self:center; color:var(--dim); }
iframe#view { width:100%; height:680px; border:1px solid var(--line); border-radius:8px; background:var(--card); }
textarea, input.say { width:100%; font:12px/1.4 ui-monospace, Menlo, monospace; background:var(--map); color:var(--ink); border:1px solid var(--line); border-radius:6px; padding:6px; }
button.go { font:inherit; padding:4px 12px; border-radius:6px; border:1px solid var(--accent); background:none; color:var(--accent); cursor:pointer; }
"""

JS = """
const D = JSON.parse(document.getElementById('data').textContent);
const $ = (s) => document.querySelector(s), esc = (s) => String(s).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const label = {met:'met', not_met:'not met', unknown:'unknown', ended_early:'ended early'};
let game = 0, pick = 0;
function games() {
  $('#games').innerHTML = D.games.map((g, i) => `<div class="row ${i === game ? 'on' : ''}" data-g="${i}">
    <span class="t">Dlvl ${g.deepest}</span><span class="grow" title="${esc(g.end)}">${esc(g.end)}</span>
    <span class="t">${g.outcomes.length}</span></div>`).join('');
}
function decisions() {
  const g = D.games[game];
  $('#gname').innerHTML = `${esc(g.name)} · XL ${g.xl} · turn ${g.turn} · <a href="replay-${esc(g.name)}.html">step-by-step replay</a>`;
  $('#decisions').innerHTML = g.outcomes.map((o, i) => `<div class="row ${i === pick ? 'on' : ''}" data-o="${i}">
    <span class="t">T${o.turn}</span><span class="grow">${esc(o.tactic)}${o.target ? ' · ' + esc(o.target) : ''}</span>
    <span class="t">${o.hp}/${o.hpmax}</span><span class="tag ${o.status}">${label[o.status]}</span></div>`).join('') || '<span class="sub">No fight or escape tactics in this game.</span>';
  const on = $('#decisions .on'); if (on) on.scrollIntoView({block: 'nearest'});
}
function detail() {
  const o = D.games[game].outcomes[pick];
  if (!o) { $('#outcome').innerHTML = $('#menu').innerHTML = $('#probs').innerHTML = '<span class="sub">Nothing selected.</span>'; return; }
  $('#outcome').innerHTML = `<div class="kv">
    <span>Tactic</span><span><b>${esc(o.tactic)}</b>${o.target ? ' against the ' + esc(o.target) : ''}${o.fast ? ' (faster than the pilot)' : ''}</span>
    <span>Prediction</span><span>${esc(D.prediction[o.tactic])}</span>
    <span>Measured</span><span><span class="tag ${o.status}">${label[o.status]}</span> after ${o.turns} turn${o.turns === 1 ? '' : 's'}</span>
    <span>HP</span><span>${o.hp} at the start, ${o.low} at the lowest, ${o.hp_end} at the end, of ${o.hpmax}</span>
    <span>Where</span><span>Dlvl ${o.dlvl}, XL ${o.xl}, ${o.adjacent} adjacent, ${o.in_view} in view</span>
    <span>Chosen by</span><span>${o.jev ? 'Jev judge routed to <b>' + esc(o.jev.route) + '</b>' : 'the rules (fixed selector)'}</span></div>`;
  $('#menu').innerHTML = (o.menu.length || o.omitted.length) ? `<div class="kv">` +
    o.menu.map(t => `<span>${t === o.tactic ? '<b>' + esc(t) + '</b>' : esc(t)}</span><span>${esc(D.prediction[t])}${t === o.tactic ? ' · chosen' : ''}</span>`).join('') +
    o.omitted.map(t => `<span style="text-decoration:line-through">${esc(t.id)}</span><span class="sub">omitted: ${esc(t.reason)}</span>`).join('') + '</div>'
    : '<span class="sub">This tactic continued an earlier decision; the menu is recorded where a tactic starts.</span>';
  const node = (t, x, jev) => `<div class="node ${jev ? 'jev' : ''}"><b>${t}</b>${x}</div>`, arrow = '<span class="arrow">&rarr;</span>';
  $('#flow').innerHTML = [
    node('Observe', `${o.adjacent} adjacent, ${o.in_view} in view, HP ${o.hp}/${o.hpmax}`),
    node('Build menu', `${o.menu.length} feasible, ${o.omitted.length} omitted`),
    o.jev ? node('Jev: three yes/no answers', Object.entries(o.jev.p).map(([k, v]) => `${esc(k)} ${v.toFixed(2)}`).join(', '), true) : '',
    node(o.jev ? 'Route (code, on the answers)' : 'Select (rules, fixed order)', esc(o.jev ? o.jev.route : o.tactic)),
    node('Safety rules', 'passed'),
    node('Motor', `${esc(o.tactic)} for ${o.turns} turn${o.turns === 1 ? '' : 's'}`),
    node('Measure', `<span class="tag ${o.status}">${label[o.status]}</span>`),
  ].filter(Boolean).join(arrow);
  const src = `replay-${D.games[game].name}.html#t=${o.turn}`; if ($('#view').getAttribute('src') !== src) $('#view').setAttribute('src', src);
  history.replaceState(null, '', `#g=${D.games[game].name}&o=${pick}`);
  $('#probs').innerHTML = o.jev ? Object.entries(o.jev.p).map(([k, v]) => `<div class="p"><span>${esc(k)}</span><span><i style="width:${Math.round(v * 100)}%"></i></span><span>${v.toFixed(2)}</span></div>`).join('')
    : '<span class="sub">Jev was not asked at this decision.</span>';
}
function ledger(by) {
  document.querySelectorAll('button.by').forEach(b => b.classList.toggle('on', b.dataset.by === by));
  $('#ledger').innerHTML = '<tr><th>Tactic</th><th>Against</th><th>Tried</th><th>Met</th><th>Not met</th><th>Unknown</th><th>Ended early</th><th>Met</th><th>Dead within 20 turns</th></tr>' +
    D.ledger[by].map(r => `<tr><td>${esc(r[0])}</td><td>${esc(r[1])}</td><td>${r[2]}</td><td>${r[3]}</td><td>${r[4]}</td><td>${r[5]}</td><td>${r[6]}</td>
      <td>${Math.round(100 * r[3] / r[2])}%</td><td><span class="bar" style="width:${Math.round(120 * r[7] / r[2])}px"></span> ${(100 * r[7] / r[2]).toFixed(1)}%</td></tr>`).join('');
}
document.addEventListener('click', e => {
  const g = e.target.closest('[data-g]'), o = e.target.closest('[data-o]'), b = e.target.closest('button.by');
  if (g) { game = +g.dataset.g; pick = Math.max(0, D.games[game].outcomes.length - 1); games(); decisions(); detail(); }
  if (o) { pick = +o.dataset.o; decisions(); detail(); }
  if (b) ledger(b.dataset.by);
});
pick = Math.max(0, D.games[0] ? D.games[0].outcomes.length - 1 : 0);
const h = /g=([^&]+)&o=(\d+)/.exec(location.hash);  // keep the selection across live refreshes
if (h) { const k = D.games.findIndex(g => g.name === h[1]); if (k >= 0) { game = k; pick = Math.min(+h[2], D.games[k].outcomes.length - 1); } }
games(); decisions(); detail(); ledger('symbol');
if (D.live) setTimeout(() => location.reload(), 20000);
const served = location.protocol.startsWith('http');
$('#orders').value = JSON.stringify(D.orders, null, 1);
$('#ordernote').textContent = served ? 'Applies to games in flight within a turn; each game that takes them is marked "live orders applied" in its stats.'
  : 'Opened as a file, this page cannot send orders. Start `python3 -m pilot.serve` and open http://127.0.0.1:3067/tactics.html to apply them to a running batch.';
$('#apply').disabled = !served;
$('#apply').addEventListener('click', async () => {
  let body; try { body = JSON.stringify({orders: JSON.parse($('#orders').value || '{}'), say: $('#say').value}); } catch (e) { $('#ordernote').textContent = 'Not valid JSON: ' + e.message; return; }
  const r = await fetch('orders', {method: 'POST', headers: {'Content-Type': 'application/json'}, body}), j = await r.json();
  $('#ordernote').textContent = r.ok ? 'Applied: ' + JSON.stringify(j.applied) : 'Refused: ' + j.error;
});
"""


def write(run: str, live: bool = False) -> str:
    with open(os.path.join(BATCH, f"{run}.json")) as f:
        d = json.load(f)
    gs = sorted(d["games"], key=lambda g: (-g["deepest"], g["name"]))
    data = rows([run])
    calls = sum(g.get("brain_calls") or 0 for g in gs)
    secs = sum(g.get("brain_seconds") or 0 for g in gs)
    last = {}  # the tactic open or just closed when each dead pilot died
    for g in gs:
        os_ = g.get("outcomes") or []
        if not g.get("stall") and os_ and int(g.get("turn") or 0) - os_[-1]["turn"] <= 20:
            o = os_[-1]
            k = (o["tactic"], ", ".join(t for t in o["menu"] if t != o["tactic"]) or "nothing else")
            last[k] = last.get(k, 0) + 1
    tokens = sum(g.get("brain_tokens") or 0 for g in gs)
    payload = {
        "live": live, "orders": {k: v for k, v in DEFAULT_ORDERS.items() if k in ("retreat_below", "rest_below", "fight_up_to", "descend", "eat_at")},
        "prediction": PREDICTION,
        "games": [{"name": g["name"], "deepest": g["deepest"], "xl": g.get("xlvl"), "turn": g.get("turn"),
                   "end": g.get("death") or g.get("stall") or "", "outcomes": g.get("outcomes") or []} for g in gs],
        "ledger": {by: table(data, by) for by in ("symbol", "fast", "hp", "target")},
    }
    n = len(gs) or 1
    blob = json.dumps(payload).replace("</", "<\\/")
    deaths = "".join(f"<tr><td>{html.escape(t)}</td><td>{html.escape(alt)}</td><td>{c}</td></tr>"
                     for (t, alt), c in sorted(last.items(), key=lambda kv: -kv[1]))
    page = f"""<!doctype html><html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Pilot Tactics</title><style>{CSS}{EXTRA}</style></head><body><main>
<div class="sub"><a href="dashboard.html">&larr; all games</a> · design: docs/pilot-tactics-design.md</div>
<h1>Tactics, predictions and outcomes: run {html.escape(run)}</h1>
<div class="sub">Controller: {html.escape(d.get("brain") or "rules")} · seed {d.get("seed")} · every fight-or-escape tactic the pilot chose, what it predicted, and what the next turns showed.</div>
<div class="stats">
  <div class="stat"><b>{len(gs)}</b><span>games</span></div>
  <div class="stat"><b>{sum(g["deepest"] for g in gs) / n:.2f}</b><span>avg deepest level</span></div>
  <div class="stat"><b>{len(data):,}</b><span>tactic outcomes</span></div>
  <div class="stat"><b>{100 * sum(o["status"] == "met" for o in data) / max(len(data), 1):.0f}%</b><span>predictions met</span></div>
  <div class="stat"><b>{calls:,}</b><span>model calls</span></div>
  <div class="stat"><b>{(secs / calls if calls else 0):.2f}s</b><span>per call</span></div>
  <div class="stat"><b>{tokens:,}</b><span>input tokens</span></div>
  <div class="stat"><b>${tokens * USD_PER_INPUT_TOKEN:.4f}</b><span>this run, estimated · ${spent():.4f} all runs</span></div>
</div>
{'<div class="sub" style="margin-top:8px">Run in progress: this page reloads every 20 seconds as games finish.</div>' if live else ''}
<h2>What the pilot decided</h2>
<div class="panels">
  <div class="panel"><h3>Games (deepest first) · tactics</h3><div class="list" id="games"></div></div>
  <div class="panel"><h3>Decisions in this game</h3><div class="sub" id="gname"></div><div class="list" id="decisions"></div></div>
  <div>
    <div class="panel"><h3>Tactic and measured outcome</h3><div id="outcome"></div></div>
    <div class="panel" style="margin-top:12px"><h3>Feasible menu and omitted candidates</h3><div id="menu"></div></div>
    <div class="panel" style="margin-top:12px"><h3>Raw probabilities (Jev)</h3><div id="probs"></div></div>
  </div>
</div>
<h2>Composition of this decision</h2>
<div class="sub" style="margin-bottom:8px">Orange nodes are Jev's judgments. Every other node is code: observation, the menu, routing, safety rules, the motor and the measurement.</div>
<div class="panel"><div class="flow" id="flow"></div></div>
<h2>The game at this decision</h2>
<iframe id="view" title="Game replay at the selected decision"></iframe>
<h2>Standing orders</h2>
<div class="panel"><div class="sub" id="ordernote" style="margin-bottom:8px"></div>
  <textarea id="orders" rows="7" aria-label="Standing orders as JSON"></textarea>
  <input class="say" id="say" placeholder="Free-text order for Jev, for example: avoid melee with ants and bees" aria-label="Free-text order" style="margin:8px 0">
  <button class="go" id="apply">Apply orders</button></div>
<h2>Ledger: how often each prediction came true</h2>
<div class="sub" style="margin-bottom:8px">Group by
  <button class="by" data-by="symbol">monster letter</button> <button class="by" data-by="target">monster</button>
  <button class="by" data-by="fast">speed</button> <button class="by" data-by="hp">starting HP</button>
  · rows with at least 15 tries · the bar is how often the pilot was dead within 20 turns of starting the tactic</div>
<div class="panel"><table id="ledger"></table></div>
<h2>Between-run investigation: the last tactic before each death</h2>
<div class="sub" style="margin-bottom:8px">Deaths within 20 turns of a recorded tactic, with what else was on the menu when it started.
  Forced replay (trying each alternative from the same turn) is the next phase and is not built yet, so this table shows where an alternative existed, not whether it would have worked.</div>
<div class="panel"><table><tr><th>Last tactic</th><th>Also feasible</th><th>Deaths</th></tr>{deaths or '<tr><td colspan=3 class=sub>none</td></tr>'}</table></div>
<script type="application/json" id="data">{blob}</script>
<script>{JS}</script>
</main></body></html>"""
    out = os.path.join(BATCH, f"tactics-{run}.html")
    for path in (out, os.path.join(BATCH, "tactics.html")):
        with open(path, "w") as f:
            f.write(page)
    return out


if __name__ == "__main__":
    for r in sys.argv[1:]:
        print(write(r))
