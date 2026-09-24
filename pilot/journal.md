# Pilot journal

Lessons the brain reads at the start of every game (HaikuBrain puts this file in its prompt). `python3 -m pilot.reflect <run>` rewrites it after a batch; humans edit it too. It is versioned: `git log -p pilot/journal.md` shows how it changed and why.

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest or guard, whatever the difficulty says. Pay (routine keys "p") or leave by the stairs. (seed: 7 brain loops fighting a shopkeeper)
- Elbereth only helps if you then stay on the square and only rest or search. It does not stop @ humans, minotaurs, shopkeepers or guards. (seed: nethackwiki; Astra run 3)
- Badly hurt next to a monster that respects Elbereth: engrave. Next to one that doesn't: step away toward a corridor or take the stairs if they're a few steps away. (seed)
- Engraving Elbereth still costs a turn in which adjacent monsters get to attack; don't wait until HP is critical (single digits) to act. Retreat or engrave while HP is still well above a sliver, especially with two or more monsters adjacent (B22443603 died at HP 3/18 with a fox and sewer rat adjacent despite calling elbereth).
- Floating eye: never melee it (unless blind). Throw daggers at it from a distance; its corpse gives telepathy. (seed: Astra, all three runs)
- Don't search for hidden passages for thousands of turns while food is low: searching burns food. Go down if stairs are known. (seed: Astra run 1 went Weak three times this way)
- Descend about one level per experience level early (Dlvl up to XL+1, XL+2 once armor is decent). Camping on Dlvl 1-2 starves; diving past XL+3 dies. (seed: Astra ran about XL+2)

## For the engine (suspected bugs and missing rules; the improvement loop reads this)

- Loot routine can loop indefinitely near the stairs when a pet blocks the tile ("Your kitten is in the way!"), alternating loot and go_down for many turns without ever actually descending, burning the run to the turn limit (B22443600, B22443601).
