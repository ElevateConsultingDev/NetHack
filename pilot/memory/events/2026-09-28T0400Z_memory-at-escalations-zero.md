---
timestamp: 2026-09-28T0400Z
run_id: 20260928-032924
kind: discovery
---

# Memory at escalations only: no effect

## What happened
Haiku answering escalations only, with branch recall (the leaves matching each moment in the brief), 64 held-out dungeons: avg deepest 5.23 / XL 4.38, 338 brain calls. Against the same brain without memory (5.25 / 4.38): -0.02 +/- 0.11, 54 of 64 games identical. Against the rule brain alone (5.28 / 4.39): -0.05 +/- 0.15.

## What it means
With checkpoints gone, the memory neither helps nor hurts: the brain, asked only at escalations, gives the same answers as the fixed rules whether or not it is shown what past runs learned. Earlier memory designs measured negative because they rode on checkpoints, which were themselves the harm. At this engine there is nothing for a memory to improve, because the brain's decisions are not what limits depth.

## What this retires
Further investment in what the brain is told, until the brain has decisions that move depth. The Stratigraph stays as the record and the test harness for that day.
