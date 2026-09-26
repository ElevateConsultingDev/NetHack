---
timestamp: 2026-09-26T0045Z
run_id: 20260926-004022
kind: discovery
---

# Checkpoints were the harm; at escalations the brain ties the rules

## What happened
Haiku answering escalations only (no new-level, first-sight or check-in consults), no memory, 64 held-out dungeons (seed 3000): avg deepest 5.25 / XL 4.38 with 288 brain calls. The rule brain alone on the same dungeons: 5.28 / 4.39; 43 of the 64 games were identical key for key. Haiku with checkpoints (2,322 calls): 5.08 / 3.86, so the checkpoints cost about half a level of XL and gained no depth.

## What it means
The brain's 288 escalation answers changed 21 games and netted zero against the fixed rules. Three quarters of the brain's calls were consults that made play worse. Every memory design tested so far (2026-09-24 and 25) rode on those consults.

## What changed
Brain batches run escalations only unless `--checkpoints` is given.

## Next
Two candidates, both measurable against run 20260925-201627 on the same seeds: memory at escalations only (does recall help where the brain actually decides?), and the engine's stuck turns (autopsy 2026-09-24: 54% of turns with nothing changing), which no brain change addresses.
