---
archived: 2026-09-25
challenged_by: run 20260925-003957
superseded_by: conclusions.md
slug_story: elbereth-rest loop kills through animals
---

# Conclusions: the brain's current strategy

What the run record means for how the brain should play. The brain (Haiku or Qwen) reads this file at the start of every game. `python3 -m pilot.reflect <run>` revises it after a batch, archiving the previous version first; humans edit it too. Lineage: this is the former `pilot/journal.md`, carried over as the first stratum.

## Lessons for the brain

- Never fight a shopkeeper, watchman, priest, or guard: pay or flee. If a shopkeeper, guard, or wand/spell-wielding monster is hostile, break line of sight fully; stepping away one square at a time still lets a death ray, bolt, or wand zap land and kill (multiple games).
- Elbereth is unreliable: this batch it failed to stop a homunculus, gray ooze, hill orc, wererat, werejackal, and gnome lord, on top of the previously known immune list (@ humans, minotaurs, shopkeepers, guards, mindless monsters, ordinary animals, spellcasters). Treat engrave+rest as a last-resort gamble, not a plan; recheck HP after every single turn and be ready to switch to fight or flee immediately.
- Praying takes a turn or more to resolve ("begin"/"finish praying"); an adjacent monster can still land a killing hit during that window.
- Step_away doesn't guarantee safety: an adjacent monster as fast or faster than you still gets its attack first. Don't escalate max_steps if it fails once; switch to fight or elbereth.
- Engraving Elbereth itself costs a full turn of prompts (implement, text); at single-digit HP against a strong/fast hitter (guard, watch captain, elf), the monster still gets its hit while you write, so fighting may be no worse a bet than engraving (multiple deaths this batch).
- Don't order "rest" while a hostile monster is adjacent or in view, and never at critical HP even against an unseen/felt monster: the "in view" check misses invisible monsters, and rest can still get you killed with the attacker undetected (one game this batch).
- The critical-HP prayer/elbereth/fight fallback chain is where most melee deaths happen (roughly half in recent batches). Retreat or engrave while HP is still well above a sliver, especially with 2+ monsters adjacent or after step_away has already failed.
- At critical HP with a monster adjacent, don't spend the turn on inventory, eating, quaffing an unidentified potion, or a malformed/non-combat order; none stop the enemy's next hit. If prayer isn't safe, go straight to fight or elbereth.
- Floating eye: never melee it (unless blind); throw daggers instead, its corpse gives telepathy. If it blocks the only path and you have nothing left to throw, route around it via a different path rather than repeating a doomed throw order; wait it out only if no alternate route exists.
- Don't search or explore for thousands of turns while hungry; eat as soon as you're Hungry, not after reaching Weak/Fainting. This starvation stall remains the single most common failure mode. A prayer that cures Weak/Fainting is only a one-time fix; you still must eat afterward, and prayer spacing alone cannot substitute for a real food supply over a long game (one game starved despite two well-spaced successful prayers).
- When Weak with no known-safe food in inventory, look for a safe corpse on the floor to eat rather than cycling failed pick_up/use/eat orders; reading random unidentified scrolls at this point wastes turns and risks a bad effect.
- Descend roughly one dungeon level per experience level early (Dlvl up to XL+1/+2 once armor is decent); camping starves, diving too fast dies.
- In the Gnomish Mines, dwarves, watchmen, watch captains (difficulty ~12, hits as hard as a guard), and giant spiders hit far harder than their difficulty suggests; retreat toward stairs the moment one is sighted, even before it's adjacent, rather than fighting or resting nearby.
- Prayer needs roughly 1000 turns of spacing; praying too soon is "not safe" and can anger the god (XP drain) instead of helping.
- Don't order go_down before the stairs down are known. If explore stalls with no stairs found, order search_walls, then search_dead_ends if every wall's been searched twice.
- When go_to fails ("no path"), don't fall back to raw movement keys; the engine rejects them and wastes the turn. Order explore or a different go_to target instead.
- Don't quaff unidentified potions speculatively away from healing backup; some kill outright, others burn HP or freeze your feet in place when you can least afford it (a frozen-feet death to a mimic this batch). Prefer price-ID or identify scrolls, or test-quaff only at full HP away from danger.
- Don't attack (melee or throw at) an adjacent gas spore: killing it triggers an explosion that can also kill you. Step back at least one square first.
- Don't melee a homunculus: its bite can put you to sleep, leaving you helpless for other monsters to finish off. Don't rely on Elbereth against it either; its sleep bite has landed through engrave+rest twice this batch. Step fully away instead.
- If a guard or watch captain hails you ("who are you?"), answering costs a turn it can close distance in; if already hurt, flee instead of engaging the dialogue.
- Violet fungus and other stationary monsters (molds, fungi) never "move out of the way"; if one blocks your only path, fight it or route around rather than waiting, which can loop 20+ turns with no resolution.

## For the engine (suspected bugs and missing rules; the improvement loop reads this)

- Loot/pickup/probe routines can loop indefinitely when a peaceful creature blocks the tile or pick_up has no path/target (multiple games).
- go_to pathfinding fails repeatedly against unreachable coordinates and cascades through fallback orders in one turn without trying an alternate target or giving up cleanly.
- "No way on" stalls persist even after search_walls and search_dead_ends are exhausted, sometimes running 4000-11000+ turns before resolving or stalling. One case shows search_walls oscillating between the same two coordinates for many cycles without ever registering "searched every wall twice."
- go_down can fail "no known way down" even when the character is standing on or right next to the actual stairs tile; the map's known-stairs state doesn't update, wasting thousands of turns in one case until a raw '>' keypress finally worked.
- The "What are you looking for? The exit?" search prompt can repeat for 10+ turns straight, apparently an unresolved vault/hidden-area search state.
- When a consult returns no order or exhausts its fallback chain, the engine defaults to "wait," leaving the pilot idle next to danger or a dead end instead of a safer default (very common across batches).
- Cascading same-turn fallback chains (badly hurt -> rest fails -> step_away/go_to fails -> elbereth/pray/fight) can trip the engine's loop detector and end the run as a stall instead of completing one turn's action.
- Multi-prompt/multi-turn action sequences leave a window where an adjacent monster's attack can land and kill before the sequence completes: Elbereth's implement/text prompts, an unidentified potion's naming prompt, the eating "Continue eating?" prompt, the prayer begin/finish sequence, and a guard/watchman's "who are you?" dialogue have all cost fatal turns this way.
- explore's/no-way-on's "wait for the monster to move out of the way" fallback never resolves against stationary monsters (molds, fungi) and can repeat 20+ turns with no re-engagement or fresh consult.
- A failed pick_up (no path) can cascade the same-turn fallback straight into an unnecessary "elbereth" order against a trivial nearby monster.
- Standing orders (fight, rest) appear to override or persist under an explicitly chosen escape/elbereth order in the same turn window without a fresh consult, even as HP crashes; tried-and-dropped fixes were a wash or regression.
- No safety block on attacking an adjacent gas spore, similar to the floating-eye block (which is now confirmed working: a "fight" order against a floating eye is correctly rejected as of this batch).
- Once "keys rejected: walking is the engine's job" fires, the brain keeps retrying nonsensical raw keys (ESC, 'q', 'y', 'u') for the same no-way-on stall instead of giving up cleanly to wait.
- One case (game with checkpoint text "This run ended long ago. Stop.") shows the engine had no clean way to end an effectively-finished run: a standing "fight" order kept executing for two more turns and the character died instead of the run being flagged over immediately.
- History of tried-and-dropped brain-side tweaks (loop iterations 11-27, kept so they aren't retried blind): Hungry-with-no-food go_down-before-clearing; wider rest HP band; multi-round wall search with quality fallback; keep-fighting-instead-of-Elbereth when badly hurt; Excalibur fountain-dipping; eating fresh floating eyes for telepathy; stepping into a corridor/doorway with 2+ hostiles adjacent; sticky explore target with visited-square path cost; remembering every seen-floor square for pathing; sticky explore target plus loot-only-near-hostiles. None produced a net gain; revisit only after the "no way on" or "too weak for depth" problems get a real fix.
