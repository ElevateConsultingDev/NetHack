"""Rewrite the pilot's journal from a finished batch.

    python3 -m pilot.reflect <run> [--model sonnet]

Reads playground/batch/<run>.json (every game's ending, escalations and
last feed lines) and pilot/journal.md, asks a model for the revised
journal, and writes it back. The file is versioned: review with
`git diff pilot/journal.md`, keep with a commit.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile

from .batch import PLAYGROUND
from .brain import JOURNAL

SYSTEM = """You maintain the journal of a NetHack 3.6 autopilot (a Valkyrie). A deterministic ENGINE plays; a BRAIN model is consulted at checkpoints and escalations and reads this journal at the start of every game. You get the current journal and the records of a batch of games that just finished. Rewrite the journal so the next batch does better.

Rules:
- Keep the two sections and their headings exactly: "## Lessons for the brain" and "## For the engine (suspected bugs and missing rules; the improvement loop reads this)". Keep the title and the intro paragraph unchanged.
- Brain lessons: things the brain can act on (standing orders, routines, when to descend, what to avoid). One line each, concrete: condition, then action. Cite the evidence in parentheses (game name or count). At most 25 lessons.
- Keep a lesson unless this batch contradicts it; sharpen it if the evidence refines it; drop it only with a reason you can see in the records. Never drop a lesson humans wrote without contrary evidence.
- Engine section: behavior the brain can't fix (loops, a routine doing the wrong thing, a missing rule, a prompt handled badly), with the game names that show it. At most 15 items; remove ones the records show are fixed.
- A 'turn limit' or 'time limit' stall is the test harness's cap, not a failure: learn nothing from where it stopped.
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


def main() -> None:
    p = argparse.ArgumentParser(description="Rewrite pilot/journal.md from a batch")
    p.add_argument("run", help="run id, e.g. 20260923-221812")
    p.add_argument("--model", default="sonnet")
    args = p.parse_args()
    with open(os.path.join(PLAYGROUND, "batch", f"{args.run}.json")) as f:
        run = json.load(f)
    with open(JOURNAL) as f:
        journal = f.read()
    prompt = f"CURRENT JOURNAL:\n{journal}\n\nBATCH RECORDS:\n{summarize(run)}"
    out = subprocess.run(
        ["claude", "-p", "--model", args.model, "--system-prompt", SYSTEM, "--tools", "",
         "--strict-mcp-config", "--setting-sources="],
        input=prompt, capture_output=True, text=True, timeout=600, cwd=tempfile.gettempdir())
    text = out.stdout
    start, end = text.find("<journal>"), text.rfind("</journal>")
    new = text[start + len("<journal>"):end].strip() + "\n" if 0 <= start < end else ""
    if "## Lessons for the brain" not in new or "## For the engine" not in new:
        raise SystemExit(f"no usable journal in the reply; left {JOURNAL} alone.\n{out.stderr[-500:]}{text[-1500:]}")
    with open(JOURNAL, "w") as f:
        f.write(new)
    print(f"wrote {JOURNAL}; review with: git diff pilot/journal.md")


if __name__ == "__main__":
    main()
