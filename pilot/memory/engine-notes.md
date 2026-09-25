# Engine notes (suspected bugs and missing rules; the improvement loop reads this)

Derived from the run records by `pilot.reflect`, alongside `conclusions.md`. Not in the brain's prompt.

- Elbereth engrave/prompt sequence still lets an adjacent monster's attack land mid-sequence, killing the player before Elbereth takes effect (5+ games this batch: pony, werejackal x2, tengu, hill orc). Unfixed.
- step_away still fails "nowhere further away to step" very frequently (6+ games this batch); the fallback often fights the wrong/weaker adjacent monster instead of the threat that triggered the consult.
- "rest" (including rest-on-Elbereth) still executes or is ordered while a hostile is adjacent and does not stop attacks; 4 deaths this batch trace directly to a rest order executing mid-combat.
- No-way-on stalls persist after search_walls/search_dead_ends exhaust, blocked by a peaceful or hostile: 5 of 32 games this batch stalled this way; pilot defaults to wait/blind keys when the brain returns None or nonsense keys.
- Weak/Fainting stalls: check-in consults return None for thousands of turns with no food-seeking fallback; one game ran from T7500 to T11457 doing nothing productive before starving, another idled similarly before a failed prayer.
- Prayer punishment despite proper turn spacing: two games this batch had a prayer fail/anger the god as the 4th and 10th prayer respectively even though spacing exceeded 1000 turns; suggests a per-game prayer count cap, not just spacing, triggers punishment.
- Critical-HP fallback still issues eat/use/quaff/prompt-answer with no useful outcome, wasting the turn adjacent to a killer (7+ games this batch); one game lost the turn to an item-naming prompt ("Call a ruby potion:") at critical HP, then died.
- go_down still fails "no known way down" when apparently near but not on the stairs tile (4 games this batch); unchanged from prior batches.
- go_to pathfinding still fails against blocked/unreachable coordinates or ignores a blocking monster in the path (3 games this batch).
- Sleep-chain deaths: once put to sleep (homunculus bite), the pilot log shows multiple unanswered hits across turns with no consult firing until death (3 games this batch); same shape as prior batches, unresolved.
- Loot/probe/search routines still loop against a stationary blocker (peaceful hobbit, floating eye, cave spider, brown mold) for 10+ turns before falling back (3 games this batch).
- "Brain loop" stalls (repeated contradictory step_away/fight/go_to for the same adjacent monster without progress) triggered the stall detector in 3 games this batch; may need a forced-decision cap after N repeats.
- History of tried-and-dropped brain-side tweaks (loop iterations 11-27, kept so they aren't retried blind): Hungry-with-no-food go_down-before-clearing; wider rest HP band; multi-round wall search with quality fallback; keep-fighting-instead-of-Elbereth when badly hurt; Excalibur fountain-dipping; eating fresh floating eyes for telepathy; stepping into a corridor/doorway with 2+ hostiles adjacent; sticky explore target with visited-square path cost; remembering every seen-floor square for pathing; sticky explore target plus loot-only-near-hostiles. None produced a net gain; revisit only after the "no way on" or "rest doesn't interrupt" problems get a real fix.
