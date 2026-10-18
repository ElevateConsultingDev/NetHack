# One pass of the pilot loop

You are making the NetHack rules pilot go deeper. Each pass does exactly
one task, then stops.

1. Read `specs/PILOT-SPEC.md` and `IMPLEMENTATION_PLAN.md` in full. Check
   `git log --oneline -10` and `git status` so you know where the last pass
   left off. You are on branch `ai-player`; if not, switch to it. Read
   `docs/pilot.md` once for how the pilot and its tools work.
2. If a stop condition in the spec's "Done" is already met (target reached
   on both sets, "TRY passes in a row with no new best" is 8 or more, or no
   unchecked TRY task is left):
   - Report not ticked: do Report as this pass's task.
   - Report ticked, and the target was reached, or this is round 3, or the
     last Review found no new idea: output `<promise>PILOT DONE</promise>`
     and stop.
   - Otherwise: do Review (spec, "Rounds") as this pass's task.
3. Otherwise pick the top unchecked task in the plan (section 1 before 2).
   Do that task and nothing else.
4. Rules while doing it:
   - Never touch what the spec lists under "must never change". No
     superpowers: the pilot decides only from what the screen shows.
   - Before any batch: `uptime` one minute load under 20 and
     `pgrep -fl playground/nethack` empty. Busy: wait 10 minutes and check
     again, up to an hour; then leave the task unchecked with a note and
     stop the pass. A batch with a time-limit game is invalid: rerun it.
   - A TRY starts with a drill, not with code: run `python3 -m pilot.buckets`
     on the two baselines, replay one or two games from the target bucket
     (`python3 -m pilot.batch --replay <run>/<name>`, the replay page's
     decision log, `python3 -m pilot.autopsy --drill`), and write the cause
     you found in one line under the task before changing anything. The
     fix is the smallest diff that removes that cause; one engine change
     per pass, cheap variants of it allowed in the same pass.
   - Measure every candidate on both sets: `python3 -m pilot.batch --brain
     rules --seed 1000 --games 64 --parallel 16` and the same with the
     round's held-out seed, then `python3 -m pilot.compare <baseline>
     <candidate>` for each. Judge only by the spec's keep rule. Never lower
     the game counts.
   - A new best: update "Loop state" (baselines, best, set "TRY passes in a
     row with no new best" to 0). A TRY with no new best adds 1 to it and
     the code change is reverted (`git checkout -- <files>`), keeping any
     tool or test that stands on its own.
   - A C change (`src/aipipe.c` only) is rebuilt with `make -C src && cp
     src/nethack playground/nethack`, never `make all` or `make install`,
     and both baselines must reproduce exactly.
   - A task that has failed in 3 passes (see the notes under it): mark it
     `[!] blocked` with one line on why, and move on to the next task.
   - Never set or use an API key, never call Jev, Haiku or Ollama, never
     change billing or usage settings: this loop runs only on the
     subscription with the rules brain.
   - Long commands may be moved to the background by a hook: wait for the
     result before reading it or committing.
5. Run the checks: `python3 -m pilot.test_prayer` and `python3 -m
   pilot.buckets --check`. They must pass. If you cannot make them pass,
   undo this pass's code change, add a line under the task saying
   "failed: <why>", and leave it unchecked.
6. Add the row to `docs/pilot-loop.md` "Check log" (spec, "What each try
   leaves behind"). Tick the task `[x]` in the plan and add one line under
   it saying what happened (numbers, kept or dropped, a game to replay).
7. Commit everything from this pass in one commit with a plain message
   saying what changed and the result. End the message with:

       Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>

   If the candidate was kept: `git push elevate ai-player`. Push nothing
   else, ever. Never rewrite history.
8. Stop. Do not start another task. Output the promise only under step 2.

Style: no em dashes or double hyphen dashes anywhere you write.
