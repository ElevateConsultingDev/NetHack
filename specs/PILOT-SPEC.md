# Spec: make the pilot go deeper, unattended

## What we are building

A loop that improves the deterministic engine (`pilot/engine.py` and the
code it leans on) so the rules pilot reaches deeper dungeon levels, keeping
only what measurably helps. It runs without Dave: one pass does one task
from `IMPLEMENTATION_PLAN.md`, measures, logs, commits, stops; the ralph loop
feeds the same prompt back. Dave reads the rows and the questions when he
likes. The goal behind the goal is ascension; depth is how we measure
progress toward it (Dave, 2026-09-24).

## The score

- **Scored:** average deepest level (`maxlvl`) over a seed set's 64 games.
- **Guard:** average experience level (`xlvl`). Depth bought by dying
  young is not progress.
- **Recorded, never scored:** the failure buckets (`python3 -m pilot.buckets`),
  average turns, the killers, stats such as tins made or doors unlocked.

The rules brain only. No Jev, Haiku or Ollama calls: engine-only is the
pilot that counts (Dave, 2026-10-02), and the loop runs on the subscription
with no API key.

## Seed sets

64 games each, `--brain rules --games 64 --parallel 16`. Game i gets seed
SEED+i, so two batches with the same SEED play the same dungeons and
compare game by game (`python3 -m pilot.compare <before> <after>`).

- **Tuning:** `--seed 1000`. Every candidate is judged here.
- **Held out:** fresh each round, never used to choose: round 1 `--seed
  5000`, round 2 `--seed 6000`, round 3 `--seed 7000`. Each look at a
  held-out set tunes to it a little, so the next round gets new dungeons.
- Both sets are run for every candidate (about a minute each on a quiet
  machine). Never lower the game count to save time.

## Valid measurements

A batch counts only if the machine was quiet: load average (`uptime`, the
one minute figure) under 20 when it started, no stray `nethack` processes
from an earlier batch, and no game in it ended on the time limit
(`--max-seconds`, 600 s). A batch under load (2026-10-08, load about 100)
gave seven time-limit games and had to be redone. If the machine is busy,
wait 10 minutes and check again; up to an hour, then leave the task
unchecked with a note and stop the pass.

## When a candidate becomes the new best

Dave's rule (2026-09-24), kept as it stands; the loop may only ask to
change it. All of:

1. On tuning, average deepest rose by 0.25 or more with average XL not
   down by more than 0.25; **or** the bucket the task targets shrank and
   average deepest did not fall.
2. On held out, average deepest did not fall by more than its paired
   margin (`compare` prints `+/- se`; a fall is real at two standard
   errors). Gains made on tuning that vanish on held out are logged as
   tuned to the training seeds and dropped.
3. `python3 -m pilot.test_prayer` passes and `python3 -m pilot.buckets
   --check` passes.
4. **Correctness exception:** a fix for a verified defect (a replay shows
   the engine doing something wrong, such as marking a kill's square as
   looted) may be kept flat if no game is worse on either set. Say so in
   the row.

Both baselines in the plan's "Loop state" are the only "before". A kept
candidate's two runs become the new baselines.

## What the loop may change

- `pilot/engine.py`, `pilot/brain.py` (the rule brain only), `pilot/tactics.py`
  and the other pilot tooling (`batch`, `compare`, `buckets`, `frames`,
  replay page, dashboard), so long as recorded runs still load.
- `src/aipipe.c` observation code only (what the pilot sees and the truth
  channel for the replay page), rebuilt with `make -C src && cp src/nethack
  playground/nethack`. Both baselines must then reproduce exactly
  (`compare` shows every game SAME); if not, the change used the RNG or
  changed the game, undo it.
- Tests and self-checks for whatever it adds.
- The plan: tick tasks, add notes, add TRY tasks from what it finds.

## What the loop must never change (no superpowers)

- The game: `src/` other than `aipipe.c` observation code; `dat/`; the
  playground's `sysconf`. The pilot sees only what the screen shows. The
  truth channel (`NETHACK_TRUTH`) is stripped in `batch.py` before the
  engine sees a state and must stay stripped.
- Hard safety rules in the engine (prayer gate, never attack peacefuls or
  shopkeepers, floating eye and cockatrice handling, Elbereth rules). They
  may be made stricter or fixed when a replay shows them failing; never
  loosened to buy depth.
- `playground/batch` except by running batches. Never run `make all`,
  `make install` or `make WANT_SOURCE_INSTALL=1 all`: the install step is
  `rm -rf playground` (it wiped every run on 2026-10-04).
- Hooks, settings, the Ollama service, API keys, billing.
- Branch: `ai-player` only. Kept fixes push `ai-player` to `elevate`
  (Dave's standing order, 2026-09-24); nothing else is ever pushed. Never
  rewrite history.
- Dave's keep rule, the score, the target, and this list (locked; ask in
  "Questions for Dave").

## What each try leaves behind

- A row under "Check log" in `docs/pilot-loop.md`: date, iteration, what
  changed and why (the game drilled), tuning before and after with the
  paired margin, held out the same, target bucket before and after, kept
  or dropped, and a game to replay.
- The plan's task ticked with one line under it, "Loop state" updated.
- One commit per pass (`try(pilot): ...` or `feat(pilot): ...`), and a
  push to `elevate` if kept.

## Done

A round ends at the first of:

1. **Target:** average deepest 10 or more on both sets (Dave's number to
   change; ascension is far past it, this is the next waypoint).
2. **No gains:** 8 TRY passes in a row with no new best, or no unchecked
   TRY task left.
3. **Out of allowance:** the subscription's usage runs out. No iteration
   cap, no paid usage.

At a round's end the Report task writes, in `docs/pilot-loop.md` under a
"Round N" heading: which stop, baselines against best on both sets, what
was kept, what was dropped and why, and games to replay.

## Rounds (the loop in the loop)

Up to 3 rounds. After a round's Report, unless it hit the target or was
round 3, a **Review** pass plans the next round, doing what Dave did by
hand in October:

1. Run `python3 -m pilot.buckets <tuning> <held-out>` on the best, and
   drill the three shallowest games in each of the two biggest buckets
   (replay page, decision log, `pilot.autopsy --drill`).
2. Answer, in a few lines each, under "Review, round N" in
   `docs/pilot-loop.md`:
   - Where does the pilot still lose levels, and what is the likeliest
     cause in each bucket (the engine's actual decision, not the symptom)?
   - Did the keep rule throw away a lead that looked real (tuning up,
     held out flat)?
   - Is the noise hiding gains (the margins against the gains seen)?
   - Which ideas are untried, and which near misses would combine?
3. Write the next round into `IMPLEMENTATION_PLAN.md`: new or reordered TRY
   tasks, each with one line on why and the game that shows the problem.
   If it finds no idea worth a round, say so and the loop ends.
4. Put any question that needs Dave under "Questions for Dave" with its
   best guess, and go on with the guess unless the guess would change
   something locked; then go on without that change.

**Locked (Dave's only; the Review may only ask):** the keep rule, the
score, the target, the "must never change" list.

**The Review may change:** the TRY list and its order, the no gains stop
count, combination tasks, and tools for seeing why the pilot fails.

## Style

No em dashes or double hyphen dashes in anything written (docs, comments,
commit messages, rows). Match the surrounding code's comment voice.
