---
timestamp: 2026-09-25T0400Z
run_id: 20260924-215112
kind: discovery
---

# The brain's memory still measures at about zero

## What happened
Haiku played the same 32 dungeons (seed 3000) with conclusions.md (run 20260924-195151: deepest 4.59, XL 3.62) and without it (run 20260924-215112: deepest 4.41, XL 3.84). Paired difference +0.19 +/- 0.38 levels, 11 games better, 11 worse. The two earlier journal A/Bs gave +0.31 and -0.41 with the same margin.

## What it means
Whatever the conclusions say, Haiku's decisions with them do not reach deeper than its decisions without them, at this sample size. Either the lessons are not the ones that matter for depth, or the engine decides depth and the brain's calls are too few or too late to move it, or the effect is under 0.4 levels and needs hundreds of games to see.

## What is being tested next
`pilot.strat`: training batches on seeds 4100, 4200, 4300 with a reflection (new stratum) after each, and a 64-game test on seed 3000 after every stratum against a no-conclusions base. A rising curve is the Stratigraph working; a flat one says the reflection is not producing lessons that transfer.
