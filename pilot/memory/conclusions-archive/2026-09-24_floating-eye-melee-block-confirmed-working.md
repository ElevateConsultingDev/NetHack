---
archived: 2026-09-24
challenged_by: run 20260924-195151
superseded_by: conclusions.md
slug_story: floating eye melee block confirmed working
---

# Conclusions: the brain's current strategy

What the run record means for how the brain should play. The brain (Haiku or Qwen) reads this file at the start of every game. `python3 -m pilot.reflect <run>` revises it after a batch, archiving the previous version first; humans edit it too. Lineage: this is the former `pilot/journal.md`, carried over as the first stratum.

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest, or guard: pay or flee. If a shopkeeper, guard, or wand/spell-wielding monster is hostile, break line of sight fully; stepping away one square at a time still lets a death ray, bolt, or wand zap land and kill (multiple games).
- Elbereth only helps if you then stay and rest/search. It does not stop @ humans, minotaurs, shopkeepers, guards, mindless monsters (oozes, golems), ordinary animals, or spellcasters, all of which keep hitting through it (many games). Treat engrave+rest as a gamble: recheck HP after one turn, don't blindly repeat.
- Praying takes a turn or more to resolve ("begin"/"finish praying"); an adjacent monster can still land a killing hit during that window.
- Step_away doesn't guarantee safety: an adjacent monster as fast or faster than you still gets its attack first. Don't escalate max_steps if it fails once; switch to fight or elbereth.
- Badly hurt: engrave if the monster respects Elbereth; otherwise step away toward a corridor/stairs. If cornered, fight rather than engrave-and-rest (the monster keeps hitting through the rest anyway). Exception: never melee a floating eye even when cornered, since paralysis is worse than losing a turn.
- Don't order "rest" while a hostile monster is adjacent or in view: it fails ("something's in view") and wastes the decision, often cascading into a stall. Only rest once the monster is fled, dead, or out of sight.
- The critical-HP prayer/elbereth/fight fallback chain is where most melee deaths happen (roughly half in recent batches). Retreat or engrave while HP is still well above a sliver, especially with 2+ monsters adjacent or after step_away has already failed; engraving can also fail outright ("can't reach the ground"), losing the turn for nothing.
- At critical HP with a monster adjacent, don't spend the turn on inventory, eating, quaffing an unidentified potion, or a malformed/non-combat order; none stop the enemy's next hit. If prayer isn't safe, go straight to fight or elbereth.
- Floating eye: never melee it (unless blind); throw daggers instead, its corpse gives telepathy. If it blocks the only path and you have nothing to throw, wait it out, even for thousands of turns.
- Don't search or explore for thousands of turns while hungry; eat as soon as you're Hungry, not after reaching Weak/Fainting. This starvation stall remains the single most common failure mode. A prayer that cures Weak/Fainting is only a one-time fix; you still must eat afterward.
- Descend roughly one dungeon level per experience level early (Dlvl up to XL+1/+2 once armor is decent); camping starves, diving too fast dies.
- In the Gnomish Mines, dwarves, watchmen, and giant spiders hit far harder than their difficulty suggests; retreat toward stairs at first sighting of difficulty 4+ Mines monsters rather than fighting or resting nearby. A string of smaller Mines monsters can also grind HP down via repeated trades; retreat fully instead of fighting each new arrival.
- Prayer needs roughly 1000 turns of spacing; praying too soon is "not safe" and can anger the god (XP drain) instead of helping. Spaced correctly it works repeatedly across a whole game, but it only buys time against an underlying food shortage and can still be refused even at proper spacing.
- Don't order go_down before the stairs down are known. If explore stalls with no stairs found, order search_walls, then search_dead_ends if every wall's been searched twice.
- When go_to fails ("no path"), don't fall back to raw movement keys; the engine rejects them and wastes the turn. Order explore or a different go_to target instead.
- Don't quaff unidentified potions speculatively away from healing backup; some kill outright, others (like fire) burn HP when you can least afford it. At critical HP the follow-up naming prompt burns extra turns while a monster keeps attacking. Prefer price-ID or identify scrolls, or test-quaff only at full HP away from danger.
- Don't attack (melee or throw at) an adjacent gas spore: killing it triggers an explosion that can also kill you. Step back at least one square first.
- Don't melee a homunculus: its bite can put you to sleep, leaving you helpless for other monsters to finish off.

## For the engine (suspected bugs and missing rules; the improvement loop reads this)

- Loot/pickup/probe routines can loop indefinitely when a peaceful creature blocks the tile or pick_up has no path/target (multiple games).
- go_to pathfinding fails repeatedly against unreachable coordinates and cascades through fallback orders in one turn without trying an alternate target or giving up cleanly.
- "No way on" stalls persist even after search_walls and search_dead_ends are both exhausted, with no further fallback beyond wait; one case shows a locked door kicked open and re-locked across cycles before giving up; another shows search_walls itself getting stuck on "'u' changes nothing here" with no further routine to try.
- The "What are you looking for? The exit?" search prompt can repeat for 10+ turns straight, apparently an unresolved vault/hidden-area search state.
- When a consult returns no order or exhausts its fallback chain, the engine defaults to "wait," leaving the pilot idle next to danger or a dead end instead of a safer default (very common across batches).
- Cascading same-turn fallback chains (badly hurt -> rest fails -> step_away/go_to fails -> elbereth/pray/fight) can trip the engine's loop detector and end the run as a stall instead of completing one turn's action, even though each order was individually reasonable.
- No safety block on a "fight" order targeting a floating eye, despite melee being a near-guaranteed paralysis risk.
- A dwarf Valkyrie ate its own race ("You cannibal!") in one game; the eat path allowing this (floor corpse, pack food, or brain order) is unidentified.
- Living on prayer alone fails long-term: the spacing gate is sound, but the engine has no push to find/carry more food or descend when food runs short, even with correctly spaced prayers; characters have died fainted from starvation after multiple successful, well-spaced prayers.
- Multi-prompt/multi-turn action sequences leave a window where an adjacent monster's attack can land and kill before the sequence completes: Elbereth's "choose implement"/"type text" prompts, an unidentified potion's "Call a ___ potion" naming prompt, the eating sequence's "Continue eating?" prompt, and the prayer "begin"/"finish" sequence have all cost fatal turns this way. A malformed "use" order (bad item letter) has also produced no effect and wasted a critical turn.
- A failed pick_up (no path) can cascade the same-turn fallback straight into an unnecessary "elbereth" order against a trivial nearby monster.
- explore's "wait for the monster to move out of the way" fallback can repeat for many turns with no badly-hurt consult firing, sometimes ending in death or a stall with no re-engagement.
- Standing orders (fight, rest) appear to override or persist under an explicitly chosen escape/elbereth order in the same turn window; rest-on-Elbereth in particular can keep re-running for many turns and multiple hits without a fresh consult, even as HP crashes. Tried-and-dropped fixes (blocking standing-order pre-emption; having rest give up on taking a hit) were a wash or regression; the underlying "escape/rest routine doesn't recheck safety turn by turn" issue still needs a real fix.
- No safety block on attacking an adjacent gas spore; the engine could warn or force a step-back before that specific kill order, similar to the floating-eye case.
- History of tried-and-dropped brain-side tweaks (loop iterations 11-27, kept so they aren't retried blind): Hungry-with-no-food go_down-before-clearing; wider rest HP band; multi-round wall search with quality fallback; keep-fighting-instead-of-Elbereth when badly hurt (no net gain, deaths cluster at depth ~= XL, i.e. too weak for depth, not too deep); Excalibur fountain-dipping (too rare to matter); eating fresh floating eyes for telepathy (no gain, nothing uses blindfold); stepping into a corridor/doorway with 2+ hostiles adjacent (tried three ways, all within noise); sticky explore target with visited-square path cost (worsened no-way-on stalls); remembering every seen-floor square for pathing (let dwarves map whole dark Mines levels, net real loss); sticky explore target plus loot-only-near-hostiles (real loss, cause unclear). None produced a net gain; revisit only after the "no way on" or "too weak for depth" problems get a real fix.
