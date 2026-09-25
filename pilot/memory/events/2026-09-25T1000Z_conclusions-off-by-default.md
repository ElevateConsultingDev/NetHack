---
timestamp: 2026-09-25T1000Z
run_id: 20260924-220459
kind: design
---

# Conclusions leave the brain's prompt by default; the reflection changes what it writes

## What happened
The learning curve (Haiku, 64 test games on seed 3000, four arms against the no-conclusions base at 5.08): every stratum tested below the base, -0.33, -0.17, -0.52 and -0.67 levels, the last two real. Games with conclusions were shorter and ended the same ways. Two of three reflections were refused at the 10k-character cap.

## What it retires
The assumption that a file of lessons distilled from batch records helps the brain, and that more strata help more. As written, the lessons were cautions (what fails, what not to do), and a small model given cautions dies sooner.

## What changed
- `pilot.batch` runs the brain without conclusions unless `--with-conclusions` or `--conclusions <stratum>` is given.
- `pilot.reflect` now writes at most 12 rules, each keyed to a situation and telling the brain what to do, supported by at least 3 games, the whole file under 6000 characters (hard cap 7000).
- A stratum returns to the prompt only when `pilot.strat` shows it beating the base on the test seeds.
