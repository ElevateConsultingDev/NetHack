---
timestamp: 2026-09-25T2245Z
run_id: 20260925-201627
kind: discovery
---

# The brain does not beat the rules, and no memory design has helped it

## What happened
On the same 64 test dungeons (seed 3000): the deterministic rule brain alone reached avg deepest 5.28 / XL 4.39 (run 20260925-201627); Haiku with no memory 5.08 / 3.86 (depth -0.20 +/- 0.36, XL -0.53 +/- 0.17 real). Five memory designs (flat cautions, flat rules, branch recall x3 strata) all tested 0.3 to 0.9 levels below Haiku-with-no-memory. Qwen 3 8B behaved like Haiku (no memory 4.78 vs with 4.44 on 32 games).

## What it means
At this engine the brain's decisions do not add depth over the rules, and every attempt to inform the brain has cost depth. With branch recall the brain answered "badly hurt" with fight far more often (49 -> 117 of the escalation answers) and step_away/elbereth less; the leaves told it Elbereth and step_away fail. Whatever the memory says, a small model acting on it plays no better than the engine's fixed rules.

## What this retires
The premise that the next gain is in what the brain knows. The engine still spends about half of all turns stuck (autopsy 2026-09-24), and the brain is consulted mostly at checkpoints that do not change depth.

## Next
Measure the brain's contribution piece by piece: Haiku with escalations only (no checkpoints) vs rules; then decide what the brain should be asked at all.
