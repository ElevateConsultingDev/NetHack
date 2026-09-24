# Pilot journal

Lessons the brain reads at the start of every game (HaikuBrain puts this file in its prompt). `python3 -m pilot.reflect <run>` rewrites it after a batch; humans edit it too. It is versioned: `git log -p pilot/journal.md` shows how it changed and why.

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest or guard, whatever the difficulty says. Pay (routine keys "p") or leave by the stairs. If a shopkeeper is already hostile and attacking with a wand or spell, flee the room/level entirely, not just one step away, since ranged attacks still land at range (B22535006 died to a wand of striking after stepping away only once).
- Elbereth only helps if you then stay on the square and only rest or search. It does not stop @ humans, minotaurs, shopkeepers or guards. (seed: nethackwiki; Astra run 3)
- Badly hurt next to a monster that respects Elbereth: engrave. Next to one that doesn't: step away toward a corridor or take the stairs if they're a few steps away. When cornered (step_away fails with nowhere to go) against a weak adjacent animal like a jackal, just fight it instead of cycling elbereth/step_away with no result; each cycle still costs a turn and HP (B22535004).
- Engraving Elbereth still costs a turn in which adjacent monsters get to attack; don't wait until HP is critical (single digits) to act. Retreat or engrave while HP is still well above a sliver, especially with two or more monsters adjacent (B22443603 died at HP 3/18 with a fox and sewer rat adjacent despite calling elbereth).
- Floating eye: never melee it (unless blind). Throw daggers at it from a distance; its corpse gives telepathy. If a floating eye blocks the only path forward, throw a weapon to clear it rather than waiting indefinitely; waiting can leave you exposed to something else while stuck (B22535008 waited 1000+ turns and was then hit repeatedly by an unseen monster). (seed: Astra, all three runs)
- Don't search for hidden passages for thousands of turns while hungry or weak: searching and probing burns food and time without progress. If Hungry, eat available food right away instead of continuing to explore or search; waiting until Weak or Fainting to act risks death by starvation or by being caught helpless (B22535001, B22535009, B22535012, B22535015 all starved, fainted, or died fainting this batch).
- Descend about one level per experience level early (Dlvl up to XL+1, XL+2 once armor is decent). Camping on Dlvl 1-2 starves; diving past XL+3 dies (B22535002 died on Dlvl6 at XL4, two levels past the guideline).
- Don't rely on repeated prayers in quick succession: a prayer used within roughly 1000 turns of the last one is "not safe" and gives no help; an angered god can drain XP instead of saving you (B22535009 prayed too soon and got "thou art arrogant... you feel foolish," losing a level; B22535011 died right after a "prayer isn't safe" state).
- At a check-in or emergency, don't order go_down if the stairs down aren't yet known; it fails immediately and wastes the decision on that turn. Order explore or search_walls instead (B22535001 T4001, B22535011 T2501, B22535014 T3001 all cycled go_down/go_to failures within a single turn without progress).

## For the engine (suspected bugs and missing rules; the improvement loop reads this)

- Loot/pickup routine can loop indefinitely when a peaceful creature blocks the tile ("Your kitten is in the way!" or a peaceful shopkeeper won't move), alternating explore/loot for many turns without ever completing the pickup (B22443600, B22443601; this batch: B22535003 with a shopkeeper blocking a helm pickup for 20+ turns).
- "No way on" with an unkillable or unreachable blocker (a ghost that passes through walls, a floating eye, an unseen engulfing monster) leaves the pilot waiting indefinitely with no fallback tried, running to the turn limit or getting killed while stuck (B22535005, B22535008, B22535010).
- Probe routine can bounce back and forth between two adjacent squares for many turns without resolving or making progress (B22535015, probing (8,2)/(9,2) repeatedly while Weak).
- go_to pathfinding can fail repeatedly against the same unreachable coordinate and loop with search_walls without trying an alternate target or giving up cleanly (B22535014).
- The "What do you want to eat?" prompt (choices field empty) sometimes gets no keystroke response from the brain, stalling the game outright even very early (B22535013, stalled at T219 on a trivial eat prompt).
- A dwarf Valkyrie ate its own race ("You cannibal!  You will regret this!", Luck penalty, aggravate monster) in B22535004. Find which eat path allowed it (floor corpse check, pack food, or a brain order).
- Living on prayer alone fails: B22535009 camped on Dlvl 1 for 10000 turns on 8 prayers about 1000 turns apart; the 9th (gap 1008) was refused ("Thou art arrogant"). The gate is sound; the engine needs food (plan item 2) and a push to descend when food is short (plan item 21).
