---
timestamp: 2026-09-25T0134Z
run_id: 20260924-183622
kind: prompt-change
---

# Compact the conclusions for a small local model

## What changed
`conclusions.md` was compressed from 25115 to 8960 characters: every rule kept, lists of game names replaced by counts.

## Why
Run 20260924-183622 (Qwen 3 8B via Ollama, 3 games at a time): 13 of the first 17 brain calls timed out at 180 s. Each call carried about 7k tokens of prompt (this file plus history); one game spent 3,346 s waiting on the brain. Reflection had let the file grow by citing every game by name. The Haiku arm (20260924-182738) also lost 5% of calls to timeouts.

## What this retires
The assumption that the conclusions file can grow without bound. `pilot.reflect` should cap its length from now on.
