# The brain's memory (a Stratigraph)

This directory is the memory of the NetHack pilot's brain, kept as a Stratigraph: immutable events, versioned conclusions, a regenerable live edge. The protocol is `STRATIGRAPH.md`; read it first.

| File | What |
|---|---|
| `STRATIGRAPH.md` | the protocol (the genome) |
| `conclusions.md` | the brain's current strategy: what the runs mean for how to play. The brain reads it at the start of every game. |
| `conclusions-archive/<date>_<slug>.md` | every superseded strategy, verbatim, with what challenged it |
| `events/<timestamp>_<slug>.md` | immutable records: one per batch (with a per-game table), plus prompt changes, discoveries and design decisions |
| `agent-now.md` | live edge: active model, standing orders, last run. Regenerated after each batch; never archived. |

How it is used:
- `python3 -m pilot.batch --brain haiku|qwen ...` loads `conclusions.md` into the brain's system prompt (`--no-journal` plays without it, for the A/B).
- `python3 -m pilot.reflect <run>` writes the batch's run event, archives `conclusions.md` (archive first, then update), writes the revised conclusions and regenerates `agent-now.md`.
- Per-game detail (keys, brain answers, traces) stays in `playground/batch/<run>.json`, referenced by run id from the events.
