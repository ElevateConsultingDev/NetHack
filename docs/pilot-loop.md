# The improvement loop

Two loops improve the pilot. Both leave everything in git, so any step can be read, edited or reverted.

**Inner loop (the brain learns).** After every batch, `python3 -m pilot.reflect <run>` rewrites `pilot/journal.md` from the games' records. HaikuBrain reads the journal at the start of every game. Humans can edit the journal at any time; the reflection keeps human lessons unless the records contradict them.

**Outer loop (the engine improves).** A Claude Code session runs one iteration per wake-up:

1. **Baseline.** Use the latest Haiku batch `playground/batch/<run>.json` as the baseline (run `python3 -m pilot.batch --games 16 --parallel 4 --brain haiku --seed 1000` if there is none since the last engine change). Always `--seed 1000`: baseline and candidate then play the same dungeons, which removes most of the game-to-game noise.
2. **Reflect.** `python3 -m pilot.reflect <run>`; commit the journal change on its own (`journal: <run>`).
3. **Pick one fix.** Take the largest failure bucket from the baseline. Choose the fix from, in order: the journal's "For the engine" section, `docs/pilot-plan.md`'s next undone item that targets that bucket, or the records themselves. One fix per iteration, smallest diff that does it.
4. **Check.** `python3 -m pilot.test_prayer` and any other self-checks; replay the failed seeded games in that bucket (`python3 -m pilot.batch --replay <run>/<name>`: identical until the fix changes a decision, then shows what the fix did) and any saved scenarios (`python3 -m pilot.scenario list`, `run <name>`).
5. **Measure.** Decide on a deterministic pair: `--brain rules --seed 1000` without the change (stash it) and with it. Rules plus a seed repeats exactly, so every game that differs differs because of the change (games with identical keys confirm it), and 16 games take about a minute. Then run the 16-game Haiku batch with `--seed 1000` for the journal and as the next baseline; live Haiku answers vary run to run, so its bucket counts are too noisy to decide on (iteration 3: Haiku said melee 6 -> 8 while every targeted game improved; the rules pair showed the change was really worse).
6. **Keep or drop.** Keep (commit, with the before and after numbers in the message) if the target bucket shrank and the average deepest level did not fall by more than 0.5. Otherwise drop the engine change (`git checkout -- pilot/engine.py` and whatever else changed), and add a note to the journal's engine section saying what was tried and what happened.
7. **Record.** Mark finished plan items done in `docs/pilot-plan.md` with the batch numbers. The new batch is the next baseline.

Guardrails: work on the `ai-player` branch only; after each kept fix, push `ai-player` to the `elevate` remote (ElevateConsultingDev/NetHack; Dave, 2026-09-24), never anything else; never edit hooks or settings; hard safety rules stay in the engine, never in the journal alone. 16 games is noisy: a change that only moves one or two games is not evidence.
