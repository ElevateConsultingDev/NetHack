---
archived: 2026-09-25
challenged_by: run 20260925-120244
superseded_by: conclusions.md
slug_story: full HP no longer safe near lycanthropes
---

# Conclusions: the brain's current strategy

What the run record means for how the brain should play. The brain (Haiku or Qwen) reads this file at the start of every game. `python3 -m pilot.reflect <run>` revises it after a batch, archiving the previous version first; humans edit it too. Lineage: this is the former `pilot/journal.md`, carried over as the first stratum.

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest, or guard: pay or flee. A guard is lethal even at first hail (difficulty 14); duck behind cover, not just distance (2+ games).
- Descend ~1 dlvl per XL; space prayers ~1000 turns; many prayers in one game risk anger. Weak/Fainting with no food: seek a corpse, don't just wait/pray (1 starvation death).
- In the Gnomish Mines, dwarves, watchmen, spiders, gold golems, ponies, and orcs hit far harder than their difficulty; retreat toward stairs at first sighting (9 of 32 deaths this batch in Mines).
- step_away fails often ("nowhere further to step") in corridors and dead ends; don't retry it, switch straight to fight or a different direction (10+ games).
- Rest, including rest-on-Elbereth, with any hostile in view still takes hits from many monster types (bats, dogs, cats, spiders, orcs); below 30% HP fight or flee instead (7+ deaths this batch).
- At critical/badly hurt HP with a monster adjacent, never spend the turn on eat, quaff/use, potion prompts, or inventory; none stop the next hit (7+ deaths this batch).
- Elbereth's engrave sequence takes a turn; a monster can land the killing hit mid-sequence; below about 15% HP fight or flee instead of engraving (recurring).
- Floating eye: never melee it, even if step_away would leave you attacking it; unless blind, throw daggers or route around (1 more death this batch).
- Homunculus: flee on sight; if step_away fails once, fight immediately rather than retry; sleep bite kills within 1-2 turns of hesitation (6+ deaths cumulative).
- Lycanthropes (werejackal, wererat) and mind flayers hit harder than listed difficulty once adjacent; flee at first sight unless already at full HP (2 werejackal deaths this batch).
- Never attack a gas spore while adjacent, melee or thrown; step back a full square first.
- No way on after search_walls/search_dead_ends, blocked by a peaceful or monster: don't wait; walk into or attack the blocker, or go_to the stairs tile then press '>' (5 stalls this batch).
