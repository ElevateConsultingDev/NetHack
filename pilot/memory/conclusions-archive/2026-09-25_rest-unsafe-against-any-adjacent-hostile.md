---
archived: 2026-09-25
challenged_by: run 20260925-032033
superseded_by: conclusions.md
slug_story: rest unsafe against any adjacent hostile
---

# Conclusions: the brain's current strategy

What the run record means for how the brain should play. The brain (Haiku or Qwen) reads this file at the start of every game. `python3 -m pilot.reflect <run>` revises it after a batch, archiving the previous version first; humans edit it too. Lineage: this is the former `pilot/journal.md`, carried over as the first stratum.

**Status (2026-09-25):** not in the brain's prompt by default. The learning curve (events/2026-09-25T0404Z_stratigraph-efficacy-haiku.md) measured every stratum of this file below the no-conclusions base on the test seeds (-0.33 to -0.67 levels). It stays as the record and as the engine loop's notes; the reflection now writes short situation-keyed rules, and a stratum goes back into the prompt when it beats the base (`python3 -m pilot.strat`).

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest, or guard: pay or flee. Hostile shopkeepers/NPCs with wands keep killing during multi-step retreats (step_away, go_to) even when not adjacent; a zap can land on any turn you're still in line of sight, so prioritize ducking behind a corner or closed door over just increasing distance (2 wand deaths this batch).
- Elbereth is unreliable, and ordering it (or "rest" once Elbereth is down) against an animal-type monster (dog, giant ant, rock mole, giant bat, killer bee, hobbit-sized golems) is actively dangerous: the rest can run several turns while the monster keeps landing hits, and HP crashes to zero before a fresh consult happens. Do not order elbereth/rest against known Elbereth-immune monsters; fight or flee instead (5+ deaths this batch: rock mole, giant ant, dog, giant bat, small mimic, hill orc).
- Homunculus is now the single most common specific killer (4 games this batch, all via sleep bite): at first sight or any consult while one is adjacent, step_away immediately. Do not eat, rest, wait, or engrave near it; those actions all leave you exposed to the sleep bite, and once asleep you cannot act until you're dead.
- Don't attack a gas spore while it is still adjacent by any method, melee or thrown weapon: a throw from range 1 still triggered a fatal explosion this batch. Step back at least one full square before attacking it at all.
- Praying takes a turn or more to resolve ("begin"/"finish praying"); an adjacent monster can still land a killing hit during that window.
- Step_away doesn't guarantee safety: an adjacent monster as fast or faster than you still gets its attack first. Don't escalate max_steps if it fails once; switch to fight or a real Elbereth-eligible target only.
- The critical-HP prayer/elbereth/fight fallback chain is where most melee deaths happen (roughly a third this batch: straw golem, snake, hill orc, wolf, giant ant). Retreat or engrave while HP is still well above a sliver, especially with 2+ monsters adjacent or after step_away has already failed. If elbereth is ordered twice in a row at critical HP and HP keeps dropping, escalate to flee/fight, don't repeat elbereth a third time.
- At critical HP with a monster adjacent, don't spend the turn on inventory, eating, quaffing an unidentified potion, or a malformed/non-combat order; none stop the enemy's next hit.
- Floating eye: never melee it (unless blind); throw daggers instead. If it blocks the only path and you have nothing left to throw, route around it rather than repeating a doomed throw order.
- Don't search or explore for thousands of turns while hungry; eat as soon as you're Hungry. Starvation despite multiple well-spaced successful prayers happened three times this batch; prayer only cures the immediate Weak/Fainting status, it does not give you food, so actively hunt for a corpse or ration well before the next Hungry warning.
- When Weak with no known-safe food in inventory, look for a safe corpse on the floor to eat rather than cycling failed pick_up/use/eat orders.
- Descend roughly one dungeon level per experience level early (Dlvl up to XL+1/+2 once armor is decent); camping starves, diving too fast dies.
- In the Gnomish Mines, dwarves, watchmen, watch captains, giant spiders, and even ponies/dogs hit far harder than their difficulty suggests; retreat toward stairs the moment one is sighted, even before it's adjacent.
- Prayer needs roughly 1000 turns of spacing; praying too soon is "not safe" and can anger the god instead of helping.
- Don't order go_down before the stairs down are known. If explore stalls with no stairs found, order search_walls, then search_dead_ends if every wall's been searched twice.
- When go_to fails ("no path"), don't fall back to raw movement keys; the engine rejects them. However, once you're actually standing on/adjacent to a known stairs tile and go_down still fails, a raw '>' keypress can succeed where go_down doesn't (worked in one game this batch).
- Don't quaff unidentified potions speculatively away from healing backup. Also don't get drawn into naming a potion ("Call a ___ potion:") while a monster is adjacent; that prompt costs a combat turn for no safety benefit (2 deaths this batch involved this prompt firing mid-fight).
- Don't melee a homunculus, ever; see above, it is now the top priority monster to flee at first sight.
- If a guard or watch captain hails you ("who are you?"), answering costs a turn it can close distance in; if already hurt, flee instead.
- Stationary or slow-moving monsters that block your only path (molds, fungi, shriekers) never resolve by waiting; fight through or route around rather than looping 10-20+ turns of no progress.
- Mind flayers (including master mind flayers) can kill via repeated brain-eating tentacle attacks extremely fast, even outright; flee at first sight rather than engaging, especially below Dlvl 10 where you have no protection.
- Werejackals, wererats, and other lycanthropes hit harder than their listed difficulty once adjacent; treat first sighting as a flee trigger, not a fight trigger, unless already at full HP.
