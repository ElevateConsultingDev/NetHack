---
archived: 2026-09-25
challenged_by: run 20260925-122344
superseded_by: conclusions.md
slug_story: rest unsafe at any HP threshold
---

# Conclusions: the brain's current strategy

What the run record means for how the brain should play. The brain (Haiku or Qwen) reads this file at the start of every game. `python3 -m pilot.reflect <run>` revises it after a batch, archiving the previous version first; humans edit it too. Lineage: this is the former `pilot/journal.md`, carried over as the first stratum.

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest, or guard: pay or flee. Duck behind cover from a guard's hail, not just distance (2+ games).
- Descend ~1 dlvl per XL; space prayers ~1000 turns, limit prayers per game. Weak/Fainting with no food: seek a corpse, don't just wait/pray (5+ cumulative).
- In the Gnomish Mines, dwarves, spiders, ponies, orcs, and manes hit harder than difficulty suggests; retreat toward stairs at first sighting (2 deaths this batch, 11+ cumulative).
- step_away fails often ("nowhere further to step") in corridors/dead ends; don't retry it, switch to fight (the most dangerous adjacent target) or a different direction (6+ games).
- Rest, including rest-on-Elbereth, with any hostile in view still takes hits and can kill outright; below 30% HP never rest, fight or flee instead (3+ deaths this batch).
- At critical/badly hurt HP with a monster adjacent, never spend the turn on eat, quaff/use, or inventory prompts; none stop the next hit (5+ deaths this batch).
- Elbereth's engrave sequence takes a turn; a monster can land the killing hit mid-sequence even above 15% HP; below about 25% HP fight or flee instead (4 deaths this batch).
- Floating eye: never melee, even via step_away; gas spore: never attack while adjacent, melee or thrown; step back a full square from both before acting.
- Homunculus: flee on sight, don't linger; its sleep bite is often fatal within a few turns as other monsters finish you off while asleep (3 more deaths this batch, 9+ cumulative).
- Lycanthropes (werejackal, wererat) hit harder than listed difficulty; flee at first sight even at full HP, don't pause to fight a weaker companion first (4 deaths this batch).
- With 2+ hostiles adjacent, fight/target the most dangerous one by difficulty, not a weaker companion; switching targets wastes turns while the real threat keeps hitting (3 games this batch).
- No way on after searching walls/dead ends, blocked by a peaceful or monster: don't wait; attack the blocker or push past, then go_to the stairs tile and press '>' (4 stalls this batch).
