# This Is A Stratigraph

You are reading the genome of a Stratigraph — a knowledge system defined by its protocol, not its content. This file holds the protocol only: how the system thinks and records, independent of what it is thinking about. What *this particular* system is for lives in `README.md`. Read this, and proceed.

---

## What This Stratigraph Is For

This is a **NetHack agent Stratigraph**. It records the evolution of prompt strategies used by an AI brain (Claude) to guide a NetHack engine toward better play outcomes.

The system has two parts:
- **Engine** — the machine layer that interfaces with NetHack, observes game state, and drives execution.
- **Brain** — the prompt layer that reads game state and conclusions, and generates decisions for the engine.

This Stratigraph is the brain's memory. It records what happened in each run, synthesizes what those runs mean for prompt strategy, and evolves that strategy over time.

---

## What A Stratigraph Is

A Stratigraph applies event-sourcing not just to facts, but to **meaning**.

- **Events** are immutable. Things happened; you record them, append-only, and never edit them after.
- **Conclusions** are derived meaning — what the events *mean*, synthesized and maintained separately from the raw events.
- **Conclusions are versioned, never destroyed.** When new events challenge a conclusion, the old one is archived — verbatim, with a note on what challenged it and what replaced it. You never overwrite understanding. You stratify it.

The result is a record that holds not only *what* changed, but *why*, and *how the understanding evolved over time*. It is read the way a geologist reads rock layers: drill down, and the history is legible.

The aim is **stratigraphic memory, not photographic memory.** Photographic memory recalls every pixel and understands nothing. Stratigraphic memory keeps the layers — how the thinking moved, and why — and lets you read, query, and reanimate them.

---

## The Layers

```
nethack-agent/
  README.md                    ← project front door — what this system is,
                                  how to use it, where things live
  STRATIGRAPH.md               ← the genome (this file) — the protocol
  agent-now.md                 ← live edge — current best prompt strategy,
                                  active parameters, last run state. Regenerable.
  conclusions.md               ← current synthesized prompt strategy — what
                                  works, what doesn't, and why
  conclusions-archive/
    <date>_<slug>.md           ← superseded strategies, verbatim + lineage note
  events/
    <timestamp>_<slug>.md      ← immutable run records and discovery events
```

---

## The Protocol

**1. Events are immutable.** Record what happened, append-only. Never edit an event after writing it. Use a sortable UTC timestamp in the filename.

**2. Conclusions are derived meaning.** `conclusions.md` is the living synthesized prompt strategy — what the events *mean* for how the brain should prompt, not just what happened in runs.

**3. Conclusions are versioned, never destroyed — archive FIRST.** When a new run challenges the current strategy:
  1. **Archive first.** Copy the current `conclusions.md` to `conclusions-archive/<date>_<slug>.md` with the frontmatter below — *before* touching the live file.
  2. Then write the new strategy into `conclusions.md`.

The order is mandatory. Archive-then-update, never update-then-archive.

```yaml
---
archived: <date>
challenged_by: <event filename or run that broke this strategy>
superseded_by: conclusions.md
slug_story: <one line — why this strategy was retired>
---
```

**4. Archive naming:** `<date>_<slug>.md`. The slug captures the spirit of what's being retired — what prompt assumption died on this run.

**5. The genome is a stratum too.** STRATIGRAPH.md is itself a node. When the design changes, log the design-pressure as events and cut the change as its own genome event.

**6. One event log, two derivations.**

- **Projection** (`agent-now.md`) — current *state*. Best active prompt strategy, current parameters, last run outcome. Cheap to regenerate, never archived.
- **Conclusions** — derived *meaning*. What patterns actually work across runs, and why. Always versioned, always archived on change.

Never pour projection-state into conclusions. State churn drowns evolving strategy.

**7. The live edge is `agent-now.md`.** Overwrite freely. It is regenerable from `events/` + `conclusions.md` at any time.

**8. When to write an event.** Write an event for:
- Any completed run — record outcome, dungeon depth reached, cause of death, notable decisions, what the prompt did that was smart or stupid.
- Any prompt change — what changed, why, what failure or discovery prompted it.
- Any discovery about NetHack mechanics or agent behavior that changes how prompts should be written.
- Any design decision about the system itself.

*Not* required for mechanical state updates already covered by `agent-now.md`.

**The test:** if the reasoning behind a prompt change would be lost without writing an event, write it. When in doubt, write it.

**9. Commit continuously.** Checkpoint the byte layer often. The commit log is the safety net, not the meaning record.

---

## What Goes In An Event

A run event should capture enough to reconstruct why the brain made the decisions it did:

```markdown
---
timestamp: <UTC>
run_id: <sequential or uuid>
kind: run | prompt-change | discovery | design
---

# <slug>

## Outcome
- Depth reached: <dungeon level>
- Cause of death: <how it died>
- Score: <if available>

## What The Brain Did
<what prompt strategy was active, what decisions it produced>

## What Worked
<specific decisions or patterns that helped>

## What Failed
<specific decisions or patterns that hurt>

## What Changed (if prompt-change event)
<what was revised in the prompt and why>
```

---

## What Goes In Conclusions

`conclusions.md` is the brain's current best understanding of how to play NetHack well via prompting. It should read like a prompt design document, not a run log:

- What the brain should prioritize at each phase of the game (early dungeon, mid-game, Mines, late)
- What heuristics reliably help vs. hurt
- What failure modes the prompts tend to produce and how to guard against them
- What NetHack mechanics the brain must understand to prompt well
- Open questions — things the record doesn't yet have enough runs to answer

---

## Beginning

This system records its own becoming.

The first stratum is **conception**: the moment recording begins. Before any run is logged, write an event that captures why this system was built, what problem it is trying to solve, and what the initial prompt strategy is. That is the unconformity marker — everything before it happened off-record.

---

> **Stratigraph** is a named architecture coined by Jeremy Iglehart, June 8, 2026 — discovered while building Karma Atmos. This adaptation for agent prompt optimization was derived from the master genome at `/home/ubuntu/dave/STRATIGRAPH.md`.
