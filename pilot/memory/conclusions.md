# Conclusions: the brain's current strategy

What the run record means for how the brain should play. The brain (Haiku or Qwen) reads this file at the start of every game. `python3 -m pilot.reflect <run>` revises it after a batch, archiving the previous version first; humans edit it too. Lineage: this is the former `pilot/journal.md`, carried over as the first stratum.

**Status (2026-09-25):** not in the brain's prompt by default. The learning curve (events/2026-09-25T0404Z_stratigraph-efficacy-haiku.md) measured every stratum of this file below the no-conclusions base on the test seeds (-0.33 to -0.67 levels). It stays as the record and as the engine loop's notes; the reflection now writes short situation-keyed rules, and a stratum goes back into the prompt when it beats the base (`python3 -m pilot.strat`).

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest, or guard: pay or flee. A guard is lethal even at first hail (difficulty 14); duck behind cover, not just distance (2+ games).
- Never order rest with any hostile adjacent, regardless of type: it repeats turns unattended while HP crashes to zero (7+ deaths: ants, wererat pack, cats, giant bats, sewer rat, mummy).
- Elbereth's engrave (pick implement, then write) takes a turn; a monster can land the killing hit mid-sequence. Below about 15% HP, fight or flee instead (4+ deaths).
- step_away often fails ("nowhere further to step") in corridors; don't retry it, switch straight to fight or a different direction (9+ games this batch).
- Homunculus: flee on sight; if step_away fails once, fight immediately rather than retry step_away/elbereth/pray. Sleep bite kills within 1-2 turns of hesitation (5 deaths).
- At critical HP with a monster adjacent, never spend the turn on eat, quaff/use, inventory, or malformed keys; none stop the next hit (6+ deaths).
- Giant bat, rock mole, giant ant, and cats/dogs keep hitting through Elbereth/rest; treat first sighting as flee-or-fight-now (3+ giant bat deaths).
- Praying takes a turn or more; an adjacent monster can land a killing hit before it resolves, so don't pray as last resort if that hit would kill first.
- Floating eye: never melee it (unless blind); throw daggers, or route around it if nothing left to throw.
- Don't quaff unidentified potions, or answer a potion-naming prompt, while a monster is adjacent; the prompt and the effect both cost a fatal turn (3 deaths).
- Weak with no known-safe food: don't wait or repeat prayer; actively seek a floor corpse. Prayer fixes the status, not the hunger (3 stalls/deaths despite prayers).
- Never attack a gas spore while adjacent, melee or thrown; step back a full square first.
- In the Gnomish Mines, dwarves, watchmen, giant spiders, gold golems, even ponies hit far harder than their difficulty; retreat toward stairs on first sighting.
- Don't order go_down before stairs down are known; search_walls then search_dead_ends if explore stalls. On a known stairs tile, a raw '>' can work when go_down fails.
- Mind flayers and lycanthropes (werejackal, wererat) hit harder than listed difficulty once adjacent; flee at first sight unless already at full HP.
- Stationary/slow monsters (molds, fungi, shriekers) blocking your only path never resolve by waiting; fight through or route around.
- Descend roughly one dungeon level per experience level early; camping starves, diving too fast dies. Prayer needs roughly 1000 turns of spacing.
