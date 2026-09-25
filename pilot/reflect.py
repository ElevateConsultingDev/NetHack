"""Reflect on a finished batch into the brain's memory (pilot/memory, a Stratigraph).

    python3 -m pilot.reflect <run> [--model sonnet]

1. Writes the batch's run event to memory/events/ (immutable: outcome per
   game, what the brain did, what worked, what failed).
2. Asks a model for the revised conclusions; if they changed, archives the
   current conclusions.md verbatim to memory/conclusions-archive/ FIRST
   (with what challenged it), then writes the new one.
3. Regenerates memory/agent-now.md (the live edge).
Review with `git diff pilot/memory`, keep with a commit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile

import collections
import datetime as dt
import re

from .batch import PLAYGROUND
from .brain import JOURNAL, MEMORY

SYSTEM = """You maintain the conclusions file (the current strategy) of a NetHack 3.6 autopilot (a Valkyrie). A deterministic ENGINE plays; a BRAIN model is consulted at checkpoints and escalations and reads this journal at the start of every game. You get the current conclusions and the records of a batch of games that just finished. Rewrite the conclusions so the next batch does better.

Rules:
- The lessons are RULES THE BRAIN CAN FOLLOW, keyed to a situation and telling it what TO DO: "<situation>: <action>" (e.g. "Dlvl 5 or deeper at XL 5 or less: set descend false and clear the level first"; "a soldier ant or killer bee in view: step_away toward the stairs up, never fight"). Not cautions, not lists of what fails, not narratives: a small model given a list of don'ts hesitates and dies sooner (the 2026-09-25 learning curve: every stratum of cautions tested below no conclusions).
- A rule needs support in at least 3 games of the records (say the count). Drop rules that lost their support. At most 12 brain rules, each one line under 200 characters.
- Keep the two sections and their headings exactly: "## Lessons for the brain" and "## For the engine (suspected bugs and missing rules; the improvement loop reads this)". Keep the title and the intro paragraph unchanged.
- Start the reply with one line "SLUG: <3-6 words, what assumption this batch retired>" before the <journal> block; write "SLUG: none" if nothing of substance changed.
- Brain lessons: things the brain can act on (standing orders, routines, when to descend, what to avoid). One line each, concrete: condition, then action. Cite the evidence in parentheses (game name or count). At most 25 lessons.
- Keep a lesson unless this batch contradicts it; sharpen it if the evidence refines it; drop it only with a reason you can see in the records. Never drop a lesson humans wrote without contrary evidence.
- Engine section: behavior the brain can't fix (loops, a routine doing the wrong thing, a missing rule, a prompt handled badly), with the game names that show it. At most 15 items; remove ones the records show are fixed.
- A 'turn limit' or 'time limit' stall is the test harness's cap, not a failure: learn nothing from where it stopped.
- Cite games by count ("(6 games)"), not by name: names bloated the file to 25k characters and a local model timed out reading it.
- Keep the whole file under 6000 characters.
- Only claim what the records show. No em dashes or double hyphens.
Reply with the whole new journal between <journal> and </journal>, and nothing else."""


def summarize(run: dict) -> str:
    lines = [f"RUN {run['run']} ({run['brain']} brain), {len(run['games'])} games"]
    for g in run["games"]:
        lines.append(f"\n## {g['name']} ({g.get('race')}): {g['bucket']}: {g.get('death') or g.get('stall')}"
                     f"{' while ' + g['died_while'] if g.get('died_while') else ''}; deepest Dlvl {g.get('maxlvl')}, "
                     f"XL {g.get('xlvl')}, T{g.get('turn')}, prayers {g.get('prayers')}")
        for turn, events, routine in g.get("escalations", [])[-10:]:
            lines.append(f"  brain T{turn}: {events[:160]} -> {routine}")
        for turn, kind, text in g.get("feed", [])[-15:]:
            lines.append(f"  feed T{turn} {kind}: {text[:160]}")
    return "\n".join(lines)


MAX_CHARS = 7000  # a small local model re-reads this every call


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:48] or "event"


def write_event(run: dict) -> str:
    """The batch's immutable run record."""
    games = run["games"]
    n = len(games) or 1
    avg = lambda k: sum(float(g.get(k) or 0) for g in games) / n
    buckets = collections.Counter(g["bucket"] for g in games)
    stamp = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H%MZ")
    slug = _slugify(f"run {run['run']} {run['brain']} {buckets.most_common(1)[0][0] if buckets else ''}")
    path = os.path.join(MEMORY, "events", f"{stamp}_{slug}.md")
    rows = "\n".join(f"| {g['name']} | {g.get('race','')} | {g.get('maxlvl','')} | {g.get('xlvl','')} | {g.get('turn','')} | "
                     f"{g['bucket']} | {(g.get('death') or g.get('stall') or '')[:60]} | {g.get('brain_calls', 0)} |"
                     for g in sorted(games, key=lambda g: g["name"]))
    body = f"""---
timestamp: {stamp}
run_id: {run['run']}
kind: run
brain: {run.get('brain')}{' (' + str(run.get('model')) + ')' if run.get('model') else ''}
seed: {run.get('seed')}
conclusions_in_prompt: {run.get('journal', True)}
---

# Run {run['run']}: {n} games, {run.get('brain')} brain

## Outcome
- Avg deepest level: {avg('maxlvl'):.2f}; avg XL: {avg('xlvl'):.2f}; avg turns: {avg('turn'):.0f}
- Endings: {', '.join(f'{k} {v}' for k, v in buckets.most_common())}
- Brain: {sum(g.get('brain_calls', 0) for g in games)} calls, {sum(g.get('brain_failures', 0) for g in games)} fell back to rules
- Records: `playground/batch/{run['run']}.json` (keys, brain answers, traces per game)

## Games
| game | race | deepest | XL | turns | ending | detail | brain calls |
|---|---|---|---|---|---|---|---|
{rows}

## What the brain did
Escalations and checkpoints with the brain's answers are in the records; the conclusions revision that followed this run (if any) is in `conclusions-archive/` with this run as `challenged_by`.
"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(body)
    return path


def archive(current: str, run_id: str, slug: str) -> str:
    """Copy the current conclusions verbatim into the archive with a lineage note."""
    date = dt.date.today().isoformat()
    path = os.path.join(MEMORY, "conclusions-archive", f"{date}_{_slugify(slug)}.md")
    i = 1
    while os.path.exists(path):
        i += 1
        path = os.path.join(MEMORY, "conclusions-archive", f"{date}_{_slugify(slug)}-{i}.md")
    with open(path, "w") as f:
        f.write(f"---\narchived: {date}\nchallenged_by: run {run_id}\nsuperseded_by: conclusions.md\n"
                f"slug_story: {slug}\n---\n\n{current}")
    return path


def write_agent_now(run: dict) -> None:
    """The live edge: current model, last run, active files. Regenerable."""
    games = run["games"]
    n = len(games) or 1
    avg = lambda k: sum(float(g.get(k) or 0) for g in games) / n
    with open(os.path.join(MEMORY, "agent-now.md"), "w") as f:
        f.write(f"""# Agent now (live edge, regenerated by pilot.reflect; never archived)

- Updated: {dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}
- Brain of the last reflected run: {run.get('brain')}{' (' + str(run.get('model')) + ')' if run.get('model') else ''}
- Last run: {run['run']}, {n} games, seed {run.get('seed')}: avg deepest {avg('maxlvl'):.2f}, avg XL {avg('xlvl'):.2f}
- Strategy in force: `conclusions.md` (archive in `conclusions-archive/`)
- Engine: `pilot/engine.py` at the current commit; standing-order defaults in `DEFAULT_ORDERS`
""")


def main() -> None:
    p = argparse.ArgumentParser(description="Rewrite pilot/journal.md from a batch")
    p.add_argument("run", help="run id, e.g. 20260923-221812")
    p.add_argument("--model", default="sonnet")
    args = p.parse_args()
    with open(os.path.join(PLAYGROUND, "batch", f"{args.run}.json")) as f:
        run = json.load(f)
    with open(JOURNAL) as f:
        journal = f.read()
    write_event(run)
    prompt = f"CURRENT CONCLUSIONS:\n{journal}\n\nBATCH RECORDS:\n{summarize(run)}"
    out = subprocess.run(
        ["claude", "-p", "--model", args.model, "--system-prompt", SYSTEM, "--tools", "",
         "--strict-mcp-config", "--setting-sources="],
        input=prompt, capture_output=True, text=True, timeout=600, cwd=tempfile.gettempdir())
    text = out.stdout
    start, end = text.find("<journal>"), text.rfind("</journal>")
    new = text[start + len("<journal>"):end].strip() + "\n" if 0 <= start < end else ""
    if "## Lessons for the brain" not in new or "## For the engine" not in new:
        raise SystemExit(f"no usable conclusions in the reply; left {JOURNAL} alone.\n{out.stderr[-500:]}{text[-1500:]}")
    if len(new) > MAX_CHARS:
        raise SystemExit(f"revised conclusions are {len(new)} chars (cap {MAX_CHARS}); left {JOURNAL} alone. "
                         f"Rerun, or compact by hand (archive first).")
    slug = re.search(r"SLUG:\s*(.+)", text)
    slug = (slug.group(1).strip() if slug else "revised").rstrip(".")
    if new.strip() != journal.strip():
        archive(journal, run["run"], slug)  # Archive first, then update: the order is mandatory.
        with open(JOURNAL, "w") as f:
            f.write(new)
    write_agent_now(run)
    print(f"event written; conclusions {'revised (' + slug + ')' if new.strip() != journal.strip() else 'unchanged'}; "
          f"review with: git diff pilot/memory")


if __name__ == "__main__":
    main()
