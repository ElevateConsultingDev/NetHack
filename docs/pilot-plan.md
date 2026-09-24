# Pilot improvement plan (2026-09-23)

Ranked by a research workflow: two web researchers (strong human play; prior bots: BotHack, AutoAscend, NLE, LLM agents), a code-and-failure-data analyst (every batch CSV and saved stall), and a synthesizer. Nothing here is implemented yet; effects are estimates. Full inputs and sources: `docs/research/2026-09-23-improvement-workflow.json`.

## Summary

This is one ranked plan built from all three inputs, with duplicates combined. 81% of games end in a stall and 19% in death. Three stalls cover most of the losses: hunger (42% of games), no way on (23%) and shop traps (27 of 135 snapshots). A sound prayer gate and a wider food list come first, because hunger alone ends 42% of games. They need a gap of 1000 or more turns and must parse the prayer result. Next come fixes that stop the pilot from angering shopkeepers and from stepping into invisible or blind-shop traps. Those account for most wand and bolt deaths, 14 of 42. A small engine ordering bug also stops Elbereth from ever running. After that come floating-eye and passive-blocker handling, remembered dark floor for the Mines, and a search overhaul modeled on AutoAscend, BotHack and Saiph for no way on. Then come the brain fallbacks, a Mines branch policy, and better combat positioning. Harness diagnostics come earlier than their direct effect would place them, because they are needed to measure every other item. Longer-term items that help growth come last: Excalibur, altar BUC testing and XL-gated descent. Items 1 to 8 are mostly small changes in engine.py and brain.py. Together they target the causes behind about 60% of current game endings. Nothing here has been implemented or run yet. The ranking is a judgment from the failure data, and the expected effects are estimates.

## Ranked items

### 1. Prayer gate you can trust: 1000-turn gap, parse the result, and track Luck

- **Status (2026-09-23): done.** 16-game batch 20260923-221812: Weak stalls 1/16 (9/16 the batch before the wait fix), 57 prayers, 57 ok, avg turns 5552, avg XL 4.9. Deviation: a failed prayer closes the gate for good (pray.c angrygods raises god anger). Added: keep playing when Weak if the gate opens within 300 turns.
- **Layer:** engine · **Effort:** small
- **Why:** The Weak stall is the most common ending: 80 of 217 games, all 'Weak and no known-safe food'. Prayer restores nutrition to 900, but prayer_safe (engine.py:277-278) uses an 800-turn gap. Timeout after a successful prayer is rnz(350), which is over 1000 about 8% of the time, and major trouble needs a timeout of 200 or less (pray.c:1821). B20313002 got 'You feel that Tyr is displeased' and then stalled. 3 deaths happened while praying. B20323701 prayed after 'You murderer!'. Sources: nethackwiki Prayer_timeout; BotHack game.clj (1300); Saiph Health.cpp.
- **Change:** prayer_safe = not prayer_broken and not luck_bad and ((never prayed and turn>=300) or turn-last_prayer>=1000). Parse the prayer result from the accumulated messages (see item 3). 'You feel a hopeful feeling', 'You feel much better' or the trouble being fixed counts as success and sets last_prayer=turn. 'displeased' still sets last_prayer=turn (the prayer clock reset) and blocks prayer for another 1000 turns. 'is angry', 'smit', 'You feel guilty' or 'black glow' sets prayer_broken. 'You murderer!', 'You hear the shrieks', killing a peaceful or breaking a mirror sets luck_bad for about 3000 turns. Define major trouble as exactly: HP<6 or HP<=maxHP/7, hunger Weak or Fainting, or conditions Stone, Slime, Strngl or FoodPois/Ill (Sick), or 'You feel feverish'. Add a top-priority standing order: if major trouble and prayer_safe, then #pray. That makes Weak with no food pray first and stall only when the gate is closed. Record 'prayed_at' and the result in stats.
- **Expected effect:** Removes most of the 80 Weak stalls, since the first prayer opens at turn 300 and Weak snapshots average about 4500 turns. It also saves low-HP games and stops the 'killed while praying' deaths.

### 2. Complete SAFE_FOOD, handle tins, and drop eggs

- **Status (2026-09-24): done (loop iteration 6).** Food list completed, eggs dropped, whole-word matching (a substring match let 'tin' match 'floating eye corpse' and killed a game in the first try), tins judged by their smell message (no own-race tins, nothing while hallucinating), tins eaten last. Rules pair (seed 1000) 20260924-080536 -> this commit's batch: hunger endings 5 -> 4, avg deepest 3.38 -> 3.38, avg turns 3783 -> 3878. Reserve foods (wolfsbane, lizard) and 'stop when you have a hard time getting it down' not done.
- **Layer:** engine · **Effort:** small
- **Why:** 24 of 64 Weak-stall snapshots carried edible food missing from SAFE_FOOD (engine.py:34-36): tripe in B19492901, eucalyptus in B19551803, wolfsbane in B19470904, and a tin, tripe and garlic in B19535706. 'egg' is listed even though an unknown egg can be a cockatrice egg. The tin prompt 'Eat it?' does not match mechanics' lowercase 'eat it?' check (line 340). Sources: nethackwiki Tin and Nutrition; AutoAscend agent.py.
- **Change:** Add tripe ration, tin, eucalyptus leaf, clove of garlic, kelp frond, meatball, meat stick, huge chunk of meat, lump of royal jelly, fortune cookie, pancake, cram and lembas. Keep sprig of wolfsbane and lizard corpse as reserve food: eat them only when Weak and prayer is closed. Remove 'egg'. Make the prompt match case-insensitive. For 'It smells like X. Eat it?' answer y if X passes the corpse blacklist (item 11) and n otherwise. Open tins only when no hostile is visible and not Hallu. Eating order: fresh corpse, then the lowest-value permanent food, starting at Hungry, never while Satiated. Stop eating on 'You're having a hard time getting all of it down'.
- **Expected effect:** Removes about a third of the remaining Weak stalls outright, and stretches the food supply between prayers.

### 3. Accumulate messages across --More-- snapshots

- **Layer:** engine · **Effort:** small
- **Why:** aipipe clears its message buffer on every snapshot (aipipe.c emit_state, nmsgs=0), and mechanics() returns early on 'more' snapshots. Routines therefore miss messages. In B20313001 'Closed for inventory' was on screen and the door was kicked anyway. The elbereth-stuck snapshots end in 'Never mind.' with no handler seeing why. The prayer-result parsing (item 1) and the shop-door guard (item 5) depend on this fix.
- **Change:** In Engine.step, append every snapshot's messages to memory.recent_msgs, including 'more' snapshots. Clear the list only after the first command snapshot's routines have consumed it. Point every message check at recent_msgs: doors, shop sign, engraving, corpse, prayer, 'It hits', 'Welcome to', 'for sale'. Run the door and shop checks before r_loot in _default_activity.
- **Expected effect:** This is the prerequisite that makes items 1, 5, 6 and 8 reliable. On its own it fixes the missed shop signs and the engravings whose failure went unnoticed.

### 4. Standing orders must not pre-empt a danger routine (the Elbereth bug)

- **Layer:** engine · **Effort:** small
- **Why:** _standing() runs before self.routine. When the brain answers 'badly hurt' with elbereth, the fight standing order (engine.py:951-961) still sends F. Replaying B19470908, B19504802 and B19551810 shows the next key is 'Fk'. The B20313003 and B20313007 feeds show 'badly hurt -> elbereth' followed by 'standing order: fight the kitten' or 'little dog', then death. There were 7 'badly hurt (last order: elbereth)' loops. In 3.6, attacking also erases the engraving (nethackwiki Elbereth).
- **Change:** In _standing, after the critical-HP, prayer and retreat block, return None when self.routine is in {'elbereth','step_away','rest','pray'}, so the routine runs next. While standing on Elbereth, allow only search or rest and never F, throw or zap. After engraving, read the engraving back (':' look) and re-engrave, at most 3 times, if the text is not exactly 'Elbereth'. Handle 'Never mind.' by retrying with explicit answers to the E prompts.
- **Expected effect:** Elbereth actually runs. This saves most low-HP melee deaths, including the 4 deaths to domestic animals, and ends the 7 elbereth loops and 5 elbereth-stuck stalls.

### 5. Stop angering shopkeepers and the Watch: door kicking rules

- **Layer:** engine · **Effort:** small
- **Why:** In the B20313001 feed the pilot read 'Closed for inventory', found the door locked, kicked it, got 'How dare you break my door?', and was killed by a lightning bolt from the shopkeeper's wand. 14 wand or bolt deaths, and 13 of those had 0 gold, which is the case where paying for the door is impossible (shk.c pay_for_damage). That cause is proven for 2 of them and inferred for the rest. r_explore (lines 419-434) kicks any locked door. The shop guard also marks the wrong squares. Sources: nethackwiki Shopkeeper and Watchman; AutoAscend global_logic.py.
- **Change:** Keep a per-level set of 'Closed for inventory' engraving squares. Mark every door orthogonally next to one as dead, rather than the hero's neighbours. Never kick a door when: the dungeon is the Gnomish Mines, a shopkeeper, watchman or priest has been seen on this level, a door is next to a known shop wall, or gold is under 500. Otherwise open up to 6 times, then kick. Drop a door as a target after 4 failed opens when kicking is not allowed. In mechanics, answer y to 'pay for the door?'. Also add the Minetown fountain rule: never #dip or quaff from a fountain in Minetown.
- **Expected effect:** Removes the main wand and bolt death path, most of the 14 deaths (19% of deaths are wand or bolt).

### 6. No shoplifting: skip loot in shops, and pay for or drop unpaid items

- **Layer:** engine · **Effort:** small
- **Why:** 27 of 135 stall snapshots carry '(unpaid, N zorkmids)' goods. B19455905 has 17, B19504800 has 20 tools including pick-axes, B19470910 has 8 spellbooks. The shopkeeper blocks the door and the pilot wanders inside until it goes Weak. r_loot (lines 657-658) stops only when a shopkeeper is visible at that moment. In B20313004 the pilot looted while blind. Sources: nethackwiki Shopkeeper; BotHack pathing.clj; NetPlay, arXiv 2403.00690.
- **Change:** Set in_shop when recent_msgs contain 'Welcome to', 'for sale' or 'Closed for inventory', or when the hero is inside a room whose door has a shopkeeper next to it. Clear it after leaving the room. While in_shop, or while Blind or Hallu, skip r_loot and corpse eating. Add a standing order ahead of explore: if any inventory line contains 'unpaid', send 'p' and answer y when gold covers the total, otherwise drop each unpaid letter (D, or d per item) before moving. Never carry a pick-axe into a shop. Remove '+' from the default loot classes and narrow '(' to useful tools only: pick-axe, unicorn horn, blindfold, towel, bags.
- **Expected effect:** Removes the shop-trap stalls, about 20% of stall snapshots, which mostly show up as Weak stalls. It also removes a common path to an angry shopkeeper.

### 7. Act on status conditions and invisible attackers

- **Layer:** engine · **Effort:** medium
- **Why:** checks() copies status.conditions (line 289), but nothing reads them. In B20313004 the pilot went blind, kept looting and exploring in a shop, F-attacked an 'I' ('It gets angry!') and was killed by a wand of striking. 4 deaths are 'killed by an invisible X'. checks() counts only kind=='monster', so the rest order sends '20s' while 'It hits!' messages scroll past. Hallu also removes the peaceful flag (aipipe.c:335). Sources: AutoAscend global_logic.py; Saiph Health.cpp and Explore.cpp; nethackwiki Invisible.
- **Change:** (a) If Stone, Slime, Strngl or Sick: eat a carried lizard or acidic corpse when stoning, else pray if the gate is open, else escalate. This is covered by item 1's major-trouble list. (b) If Blind, Conf, Stun or Hallu with no adjacent hostile: send '5s' in place, with no explore, loot, travel or stairs. Apply a non-cursed unicorn horn if carried. (c) Count adjacent 'invisible' cells as hostiles in the fight and retreat checks, and attack them with F+dir, except when in_shop or when a peaceful was last seen on that square. (d) If a recent message matches 'It hits|It bites|You are hit' or HP dropped with nothing visible, block rest and search orders and send one 's' to mark the attacker. Clear the 'I' after the kill.
- **Expected effect:** Removes the invisible-monster deaths (4) and the blind-in-shop wand death, and stops confused or stunned moves into danger.

### 8. RuleBrain: never fight shopkeepers, watchmen, priests or guards

- **Layer:** brain · **Effort:** small
- **Why:** 7 brain loops read 'shopkeeper adjacent, difficulty 15 > N (last order: fight shopkeeper)'. Replaying B20234314, B20015104 and B20061114 attacks the shopkeeper at 7/37, 14/43 and 15/56 HP. brain.py:47-49 turns any over-difficulty adjacent monster into a fight order. Elbereth does not work on @-humans, shopkeepers or guards (nethackwiki Elbereth). BotHack pathing.clj has the same hard rule.
- **Change:** In decide(): never target a monster named shopkeeper, watchman, watch captain, priest or guard. For an angry shopkeeper: send 'p' if gold is above 0 and there are unpaid items or a door debt, otherwise head for the nearest known stairs, or pray if HP is critical and the gate is open. For over-difficulty monsters that are not @: step_away toward a corridor, then elbereth (with the respect check from item 13). Also in the engine: always answer n to 'Really attack?' and mark that monster peaceful. Give a peaceful's square a path cost of about 50 instead of bumping into it.
- **Expected effect:** Ends the 7 shopkeeper loops and a class of deaths from angry shopkeepers or the Watch. It also protects Luck, which keeps prayer working.

### 9. Passive blockers (floating eye, gas spore, acid blob, molds): throw, retrieve, line up, and use role-aware avoid

- **Layer:** engine · **Effort:** medium
- **Why:** Floating eye appears in 10 no-way-on reasons, gas spore in 6, acid blob in 5 and yellow mold in 2. 8 snapshots have the stairs down reachable only through a floating eye, and most have no dagger left. memory.retrieve (line 631) is filled but never read. Loot is skipped while any hostile is visible (line 998). ranged_kill never moves into line. DONT_MELEE lists brown mold, which is harmless to a cold-resistant Valkyrie. Sources: nethackwiki Floating_eye; AutoAscend monster_utils.py and fight_heur.py (brown mold and blue jelly melee at full HP); BotHack mainbot.clj.
- **Change:** (a) Let loot run when every visible hostile is on the avoid list and at distance 2 or more, and always pick up squares in memory.retrieve. (b) Add a line-up step: bfs to a square 2-8 tiles away on a straight line with a clear path, no pet or peaceful on the line and no wall, then throw. (c) Throw order: dagger, then spare weapons (orcish dagger, darts, spears), then rocks, gems or junk. Pick up and keep a stack of about 10 rocks when one is seen. (d) Give the blocker's square a high path cost rather than making it impassable, and wait or search in bursts because floating eyes move at speed 1. (e) Build the avoid list from role and intrinsics: melee brown mold and blue jelly at full HP as a Valkyrie, melee yellow mold at HP 20 or more, never melee a floating eye unless Blind, and for a gas spore stay 3 or more tiles away and throw. (f) Once a floating eye is killed, eat its corpse (telepathy), subject to the freshness rule.
- **Expected effect:** Clears about 18 named-blocker stalls, and the floating eye's slowness no longer ends games.

### 10. Remember walked floor so dark areas are walkable; probe dark areas in 8 directions

- **Status (2026-09-24): first half done (loop iteration 15).** Squares we have stood on count as walkable when drawn blank. Rules pair (seed 1000) 20260924-102621 -> 20260924-104730: avg deepest 4.44 -> 4.81, XL 4.31 -> 4.31; a dwarf crossed a dark Mines level (Dlvl 3 -> 7). Not done: squares seen as floor but never stood on, and 8-direction probing when stairs are unreachable.
- **Layer:** engine · **Effort:** small
- **Why:** B19571504, B20061113 and B20313006 show the stairs down on screen but no floor path to them, because dark floor already walked is drawn blank and View.walkable (lines 118-130) trusts only what is on screen. 12 of the 46 no-way-on snapshots are in the Mines. r_probe_dark runs only when stairs are unknown and probes only orthogonally (lines 686-691, 1008-1013).
- **Change:** Keep a per-level remembered_floor set: memory.visited, plus every square ever drawn as FLOOR_CHARS, a door, a corridor or stairs. walkable() returns True for those unless a boulder or monster is there now. Trigger r_probe_dark when no path exists to any known stairs down, not only when stairs are unknown, and probe all 8 neighbours.
- **Expected effect:** Fixes the Mines no-way-on stalls where the stairs are visible, and makes backtracking in dark rooms reliable everywhere.

### 11. Corpse diet: kill tracking, a race-aware blacklist, lichen and lizard, eat whenever not Satiated

- **Layer:** engine · **Effort:** medium
- **Why:** 80 games reach Weak with nothing to eat. SAFE_CORPSES (lines 43-49) leaves out hobbit, dwarf, gnome, the elves (for a human), giant ant, garter snake and grid bug. _record_kills (lines 874-885) credits a kill only when pending_fight is set, so throw kills are lost. Sources: nethackwiki Corpse; BotHack tracker.clj (30 turns); AutoAscend agent.py (50 turns); the arXiv 2203.11889 winner's food triad.
- **Change:** Replace the whitelist with a blacklist over all monster types. Never eat: cockatrice, chickatrice, Medusa, any were*, human or elf (own race for a human Valkyrie) and dwarf only if a dwarf, dog, cat, green slime, bat, giant bat, yellow mold, violet fungus, black light, poisonous corpses unless poison resistant, nurse, chameleon, doppelganger, sandestin, zombie, mummy, mimic, disenchanter, abbot. On 'You kill/destroy the X' or 'You kill it' after a throw, record (square, type, turn), including throw kills at the targeted square. Eat only a corpse matching a recorded kill 40 turns old or less, and no other death recorded on that square. Lichen and lizard corpses are fine from anywhere: pick them up and keep a lizard for stoning. Eat a safe fresh corpse whenever status is not Satiated and the square is not in a shop. Fix the 'eat the fresh kill' bug: send 'e' only when a corpse was seen on the square, and if the 'What do you want to eat' pack prompt appears with eating_corpse set, send ESC, clear the flag and pop the kill (fixes B20323702).
- **Expected effect:** Keeps nutrition up with little inventory food, cuts the Hungry and Weak stalls further, and removes a prompt-loop stall.

### 12. Harness diagnostics: per-game stats, deepest dlvl, failure buckets, separate replays

- **Layer:** harness · **Effort:** small
- **Why:** Engine stats (turns per activity, corpses eaten and declined, throws, prayers, waits) go only to stdout, and the CSV drops them (batch.py:490-491). finish() records the current dlvl as maxlvl for stalls. Scenario replays overwrite batch/<name>.json: B20234307.json says 'Weak' at T1463, while the CSV says 'brain loop: small mimic' at T1165. arXiv 2203.11889 recommends 'fainted' and 'killed while praying' as separate buckets.
- **Change:** Write a stats JSON column, or a per-game stats file: turns per routine, prayers with results, corpses eaten and declined, throws, retrieves, searches, kicks, in_shop turns, and the reason for each escalation. Track the deepest dlvl in the Game object. Have scenario.run write to playground/replays/. Have batch print a summary by ending bucket: Weak stall, no way on (with blocker), brain loop, wand death, while praying, fainted, Mines death.
- **Expected effect:** Lets every other item be checked against its bucket on the next 16-game run. No direct effect on scores, but it is needed to know whether items 1 to 11 worked.

### 13. Elbereth respect list and the emergency ladder

- **Layer:** engine · **Effort:** medium
- **Why:** Werejackals in @ form, shopkeepers, guards and peacefuls ignore Elbereth. 3 lycanthrope deaths. BotHack and AutoAscend use a fixed emergency ladder. Sources: nethackwiki Elbereth; BotHack mainbot.clj; AutoAscend agent.py (quaff at HP below 1/3 or below 8); Saiph Health.cpp.
- **Change:** Emergency order when HP is under retreat_below: (1) quaff a known healing, extra healing or full healing potion if HP is below 1/3 or below 8; (2) pray if the gate is open and HP counts as major trouble; (3) engrave Elbereth only if every adjacent hostile respects it (not @, A, minotaur, shopkeeper, guard, priest, peaceful, blinded monster), and the threat is not a wand user; (4) if on or within a few steps of stairs, take them, since only adjacent monsters follow; (5) step to a non-exposed square (2 or fewer walkable neighbours) with no threat next to it. Kill order among adjacent hostiles: were*, @, then 'I', then the hardest hitters. On 'You feel feverish', set lycanthropy as major trouble: eat wolfsbane if carried, else pray when the gate is open.
- **Expected effect:** Fewer melee and werecreature deaths, the other 18+3 deaths, and less HP spent on monsters that ignore Elbereth.

### 14. Search overhaul: per-tile counts, scored targets, blank-column test, escalating budgets

- **Layer:** engine · **Effort:** medium
- **Why:** About 10 no-way-on snapshots in the main dungeon have no stairs down known (B19470913, B19492911, B19535704, B19584102). r_search_dead_ends does 10 searches per dead end once, which misses a hidden spot about 21% of the time at Luck 0, and r_search_walls stops after 2 rounds. Sources: AutoAscend exploration_logic.py; BotHack pathing.clj; Saiph Explore.cpp.
- **Change:** Keep search_count per square. Once nothing is left to explore, score each reachable walkable square that touches stone or wall: -1 - 2*count^2, +250 for a dead end, +250 for a door with more than 3 stone neighbours, +bonus if the square faces a blank screen column (x in {17,20,40,60,63} with no known feature in rows 2-18; not in the Mines), minus 4*path distance. Walk to the best square, send '10s', then rescore. Run 3 rounds with budget multipliers 1, 2 and 3: dead ends up to min(30*mul,50), blank-facing squares up to 20*mul, then from round 2 corridors and doors up to 5*mul, then walls up to 15*mul, skipping shop walls and the screen edge.
- **Expected effect:** Finds hidden stairs and corridors on most main-dungeon no-way-on levels.

### 15. Stuck ladder: expiring blocks, trap doors, walkable minor traps, and a progress watchdog

- **Layer:** engine · **Effort:** medium
- **Why:** memory.blocked is permanent (lines 211-214, 1053). In B20313006 one peaceful gnome split the level. View.walkable treats every trap as a wall (line 129), which seals corridors in B19492907, B19584112 and B20313006. B20313002 looped on Dlvl2 until T10509 with two stairs down known, and 3 games hit the 20000-turn limit on Dlvl2. Sources: AutoAscend (relax constraints as search counts grow); BotHack (unstuck); NetPlay loop analysis, arXiv 2403.00690.
- **Change:** (a) Store blocked squares as (square, turn), expire them after 50 turns, and never block a square next to the target stairs. (b) Make squeaky board, arrow, dart, rust and rolling boulder traps walkable at a path cost of about 20. Treat a known trap door or hole as a go_down target when no stairs are reachable. (c) Detect loops by (position, action, top message) over the last 50 keys, and blacklist a failing target for 100 turns. (d) Add a watchdog: after 1500 turns with no new dlvl and no new explored square, force go_down if stairs are known (fight or throw past blockers); if no stairs are known, climb up and come back down once; then escalate with the loop as the reason.
- **Expected effect:** Removes the turn-limit stalls and the ping-pong loops, and turns part of the remaining no-way-on stalls into descents.

### 16. RuleBrain fallbacks for Weak and no way on

- **Layer:** brain · **Effort:** small
- **Why:** decide() returns Order(None) for everything except prompts, badly hurt, dangerous-adjacent and difficulty (brain.py:39-50), so 65% of games end on escalations the rule brain never tries. After items 1, 2, 14 and 15 these reach the brain less often, but they still need answers.
- **Change:** Weak: eat any food with the fallback tier allowed. If there is none and the gate is closed, take known stairs down (a new level means fresh kills), otherwise hunt nearby weak monsters for corpses. No way on: order another search round with doubled budgets, then order a fight or throw past the avoid-list blocker, then go back up and return, then take any trap door. Return None only after every step has been tried and logged.
- **Expected effect:** Converts most remaining terminal escalations into more play time.

### 17. Gnomish Mines policy: record the branch and stay out until strong enough

- **Status (2026-09-24): core done (loop iteration 2).** Non-dwarf, non-gnome under XL 8 leaves the Mines on arrival and never takes that staircase again. Paired batches (seed 1000) 20260924-073249 -> 20260924-074325: Mines deaths 5 -> 1, avg deepest 3.88 -> 4.50. Not done: the full stair graph and a brain-ordered Minetown visit at XL 8.
- **Layer:** engine · **Effort:** medium
- **Why:** 12 of 44 xlogfile deaths were in the Mines (deathdnum=2), and 19 of 135 stall snapshots are Mines levels, 12 of them no way on. r_go_down takes the first '>' it finds (lines 472-480). Gnome lords and dwarves with wands and mattocks are hostile to a human Valkyrie. Sources: nethackwiki Gnomish_Mines and Standard_strategy; AutoAscend and Saiph stair graph.
- **Change:** Keep a per-level stair graph: each staircase and the level it leads to. On arriving in a level where status.dungeon is 'The Gnomish Mines' while XL is under 8 (a knob the brain can tune), go back up, mark that '>' as mines_branch, and choose the other '>'. Later, the brain can order a Minetown visit (Mines levels 3-4, for the altar and temple) once XL is 8 or more, with the Minetown rules on (no kicks, no fountains, never attack peacefuls).
- **Expected effect:** Removes about a quarter of deaths and many dark-map stalls, and pushes descent down the main dungeon where depth counts.

### 18. Fight from corridors: positioning, first hit, and stairs as an escape hatch

- **Layer:** engine · **Effort:** medium
- **Why:** 18 melee deaths (giant bat 3, dwarf, gnome and others), plus crowd deaths such as soldier ants. Sources: BotHack mainbot.clj (exposed = more than 2 walkable neighbours; wait when the monster is 2 away 90% of the time); AutoAscend movement_priority.py; nethackwiki Soldier_ant.
- **Change:** If exposed and more than one mobile hostile is adjacent, move at most 2 steps to a non-exposed square without fighting on the way. If already non-exposed with 2 or more threats near, search and let them come one at a time. When a non-trivial, non-passive hostile is exactly 2 away, send one 's' so it steps into range. If HP is under retreat_below and stairs are within about 5 steps, take them. Before resting, move up to 8 steps to a non-exposed square. Rest from HP below 4/7 to HP above 6/7 (Saiph).
- **Expected effect:** Fewer melee deaths and more XP per fight, raising the XL average.

### 19. Stay off wand lines and kill wand users first

- **Layer:** engine · **Effort:** medium
- **Why:** 8 wand deaths, 4 magic missile and 2 fire or lightning bolt deaths. Some are not from shopkeepers. Elbereth does not stop ranged attacks. Sources: nethackwiki Standard_strategy; AutoAscend movement_priority.py (-1 on the lines of hostiles).
- **Change:** On 'zaps a wand', 'The bolt of', 'The magic missile' or a monster seen picking up a wand, flag that monster as a wand user. If you can close to melee in 1 move, do it and target it first. Otherwise move to a square off its row, column and diagonals, or break line of sight around a corner. Loot its wand after the kill. Add a -1 path cost to squares on hostile lines within range 7 when you have no ranged option.
- **Expected effect:** Cuts the non-shop wand and bolt deaths.

### 20. Throw safety: no pets or peacefuls in the line of fire

- **Layer:** engine · **Effort:** small
- **Why:** r_throw (lines 626-633) picks any matching monster cell, including peacefuls, and never checks the line. Hitting the pet makes it hostile, which may explain the 4 domestic-animal deaths (an inference). Sources: BotHack pathing.clj; AutoAscend fight_heur.py.
- **Change:** Take targets only from visible_hostiles. Walk the line square by square and refuse the throw if a pet, peaceful, wall or door frame comes before the target. Apply the same check to zapped wands.
- **Expected effect:** Avoids turning the pet hostile and avoids Luck and alignment hits. It also makes item 9's throwing safe to use widely.

### 21. Brain sets the descent pace by XL, HP and food

- **Layer:** brain · **Effort:** small
- **Why:** The deepest-level average is under 3, so depth is the north-star metric. Diving without XP kills early characters, and camping on Dlvl 1-2 starves them (AutoAscend and NetPlay both saw starvation from over-camping). Sources: nethackwiki Standard_strategy; AutoAscend global_logic.py; arXiv 2403.00690 and 2203.11889.
- **Change:** The brain sets the 'descend' standing order from max_depth = XL+1, requiring HP at 70% or more. Fully explore Dlvl 1-4 for items and XP. The engine enforces a food override: descend anyway when carried nutrition is under 1000 and prayer is on cooldown. Log the gate decision in stats.
- **Expected effect:** Steadier descent with fewer out-of-depth deaths, and a direct push on deepest-level and XL.

### 22. Excalibur: dip the long sword at XL5 outside Minetown

- **Layer:** engine · **Effort:** medium
- **Why:** A lawful Valkyrie gets Excalibur at a 1/6 chance per #dip from XL5. It is the largest single melee upgrade for this role and supports survival past Dlvl 5-10. The best run so far reached XL 8. Sources: nethackwiki Excalibur and Valkyrie.
- **Change:** When XL is 5 or more, the long sword is not already Excalibur, a fountain is known and the level is not Minetown, and HP is 80% or more with no hostile visible: walk to the fountain and #dip the long sword. Repeat while HP stays above 60%. Handle water moccasins, water demons and nymphs with normal combat. Stop when the fountain dries up or 'From the murky depths, a hand reaches up' appears.
- **Expected effect:** A large boost to melee damage and to-hit, lifting XL and depth for runs that already reach XL5.

### 23. Nymph and leprechaun keep-away

- **Layer:** engine · **Effort:** small
- **Why:** Nymphs steal the main weapon, and leprechauns take gold, which then makes shopkeeper debts unpayable (linked to the 0-gold wand deaths). Sources: nethackwiki Wood_nymph; AutoAscend movement_priority.py; BotHack mainbot.clj.
- **Change:** Leave sleeping nymphs alone and route around them. Kill awake nymphs at range, or engrave Elbereth when one is within 3 squares (they respect it). After 'stole', re-wield the best remaining weapon, and chase only if the main weapon was taken. Drop gold before a leprechaun reaches you, and pick it up after the kill.
- **Expected effect:** Fewer weapon losses and fewer games that die of weakness afterward. A small but steady survival gain.

### 24. Altar BUC testing before wearing found gear

- **Status (2026-09-24): partial substitute (loop iteration 19).** Instead of BUC testing, the pilot now wears only armor whose name hides nothing (fixed appearances: body armor up to chain mail, orcish/dwarvish/elven/dented-pot helmets, low/high boots, iron shoes); gloves, random helmets and boots and cloaks are skipped. Rules seed 1000 (64 games) 20260924-115129 -> 20260924-121902: deepest 4.11 -> 4.52, XL 4.02 -> 4.19; held-out seed 5000 4.45 -> 4.25.
- **Layer:** engine · **Effort:** medium
- **Why:** Wearing unknown armor or rings is risky: cursed gear, teleportitis, strangulation. Altars are common. Sources: nethackwiki Altar and Standard_strategy.
- **Change:** When standing on any altar that is not in a temple with a hostile priest, drop all items of unknown BUC, then pick them back up. Record black flash as cursed, amber flash as blessed and no flash as uncursed. Wear only armor tested uncursed or blessed, and never put on untested rings or amulets. Offering sacrifices at a co-aligned altar is left for later.
- **Expected effect:** Better AC from found armor with no cursed-item disasters, supporting deeper runs.

### 25. Keep all safety rules in the engine and give the Haiku brain events

- **Layer:** brain · **Effort:** small
- **Why:** BALROG (arXiv 2411.13543) found a knowing-doing gap: models say rotten food is dangerous and then eat it. NetPlay's LLM failed at menus and had to use a scripted explorer. Our loops came from brain orders that override engine safety, such as the fight-shopkeeper order.
- **Change:** Validate every brain order in the engine against hard rules before it runs: no fight on a peaceful, shopkeeper or watchman, no eating a blacklisted corpse, no prayer with the gate closed, no kicking in the Mines or next to a shop. Give the brain a short event log and the failure reason for the last routine, and let it choose only skills, never raw keys.
- **Expected effect:** Keeps the Haiku brain from undoing items 1 to 8 when it replaces RuleBrain, and makes its escalations cheaper and more accurate.
