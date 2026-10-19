# Pilot loop plan

Read `specs/PILOT-SPEC.md` first. One task per pass, top unchecked first.
Tick a task `[x]` when done and add one line under it saying what happened.
Iterations continue the numbering in `docs/pilot-loop.md` (last: 59).

## Loop state

- Round: 3 of 3; held-out seed this round 7000
- Baselines (the only "before"): tuning `20261018-181737` (seed 1000, deepest 7.25, XL 5.09); held out `20261018-183938` (seed 7000, deepest 6.67, XL 5.00)
- Buckets on the baselines (`python3 -m pilot.buckets 20261018-154632 20261018-154726`): died in melee/other 68, died in the Mines 33, starving 8, wand or bolt 7, stall: no way on 6, praying 3, invisible monster 2, brain loop 1
- Current best: the engine at the iteration 94 commit (iteration 89's numbers; handless pilots fight at critical HP)
- TRY passes in a row with no new best: 4 (the stop is 8, or no TRY left)
  (only tasks marked TRY count; a TRY with no new best adds 1, a new best resets it to 0)

## 1. Tools (do these first: every later task leans on them)

- [x] **Why the pilot fails.** `python3 -m pilot.buckets <run>...`: buckets
  across runs, killers in each, the shallowest games to drill with their
  replay command and page. Self-check `--check`.
  Done 2026-10-18: on the baselines, melee 50%, Mines 20%, no way on 12%; soldier ants, killer bees and fire ants lead the killers.
- [x] **Melee death drill table.** For each game that died in melee or in the
  Mines, print from its recorded tactic outcomes (`outcomes` in the batch
  record, `pilot.ledger`) the last tactic before death, HP fraction at that
  moment, whether Elbereth and stairs were feasible, and the killer. One
  table for both baselines, in `docs/pilot-loop.md` under "Round 1". This
  tells the TRY tasks below which fights were lost by choice (an escape
  was feasible) and which by arriving unready (XL behind the level).
  Done 2026-10-18: `python3 -m pilot.buckets --deaths`; 91 deaths, last tactic melee 82, 71 of them with an escape on the menu, 49 under a third HP; XL two or more behind in 61 (67%). Table in docs/pilot-loop.md "Round 1".
- [x] **Forced replay** (`docs/pilot-tactics-design.md`, phase 3): replay a
  melee death from a chosen turn with one tactic forced (Elbereth, stairs,
  corridor, pray), report whether the pilot survived 50 turns. Needs the
  seeded replay plus a forced first decision; no API calls. Run it on the
  ten shallowest melee deaths and record how many had a surviving move.
  A tool task, not a TRY.
  Done 2026-10-18: `python3 -m pilot.forced <runs>`; all 91 deaths: 55 (60%) had a surviving move, Elbereth 41 of 91, stairs 25 of 77, corridor 23 of 85, prayer 15 of 37; ten shallowest 8 of 10. 455 replays in 6 min at parallel 12.

## 2. Tries (each is a TRY: drill first, one engine change, both seed sets)

Order follows the buckets: melee first, Mines, then stalls, then hunger.

### Round 3 (from 2026-10-18; held-out seed 7000; confirmation round, the last)

- [x] **Held-out baseline for round 3.** Run the best engine on `--seed 7000
  --games 64 --parallel 16` and write the run id and numbers into "Loop
  state". Not a TRY.
  Done 2026-10-18: `20261018-183938`, deepest 6.67, XL 5.00; melee 38, Mines 9, starving 6, no way on 3 and 1 blocked, praying 3, wand 3, invisible 1.
- [x] TRY **Dagger recovery, confirmed.** Iteration 96's code (walk to where a
  thrown dagger should lie): +0.31 on seed 6000, -0.30 on tuning. Keep only
  if tuning does not fall past its margin and seed 7000 rises past its own.
  Done 2026-10-18, buried (iteration 97): -0.30 tuning, -0.53 seed 7000.
- [x] TRY **Cloaks, confirmed.** Iteration 93's code (+0.20 seed 6000,
  -0.20 tuning), same test.
  Done 2026-10-18, buried (iteration 98): -0.20 tuning, +0.05 seed 7000.
- [x] TRY **Pet wait, confirmed.** Iteration 84's code (+0.25 seed 6000,
  -0.25 tuning), same test.
  Done 2026-10-18, buried (iteration 99): +0.05 tuning, +0.06 seed 7000, flat.
- [x] TRY **Careful Excalibur, confirmed.** Iteration 86's code (+0.16 seed
  6000, -0.17 tuning), same test.
  Done 2026-10-18, buried (iteration 100): +0.05 tuning, -0.12 seed 7000.
- [!] blocked TRY **#enhance** (iteration 80's code; waiting on Dave's answer).

### Round 2 (from 2026-10-18; held-out seed 6000)

- [x] **Held-out baseline for round 2.** Run the best engine on `--seed 6000
  --games 64 --parallel 16` and write the run id and numbers into "Loop
  state" as the held-out baseline. Not a TRY.
  Done 2026-10-18: `20261018-170335`, deepest 5.95, XL 4.91; melee 37, no way on 9 (+1 blocker), Mines 8, starving 6, praying 1, wand 1, brain loop 1.
- [x] TRY **Keep every dagger and dart.** The loot classes omit weapons, so a
  dagger lying alone is left (piles with a menu yield them). Add daggers,
  darts, knives and shuriken to floor loot; the dagger thrown before
  contact earned its turn (iteration 66). Cheap, no risk.
  Done 2026-10-18 without a candidate (not counted): r_loot already picks up lone daggers, darts, knives and shuriken. 42 of 128 pilots end with no throwing weapon (thrown and not recovered; 1,965 throw turns across the pair), 29 with ten or more. The lever would be recovery after a fight, not pickup; a Review item.
- [x] TRY **Retreat to the stairs before contact.** A fast monster above the
  pilot's level seen at distance 3 or more, with stairs up within 4 steps:
  go up now (only adjacent monsters follow; iteration 74 fled too late).
  Come back down after 50 turns or when HP is full.
  Done 2026-10-18, dropped (iteration 82): fired 3 times in 128 games, depth flat. The sighting with stairs at hand almost never happens.
- [x] TRY **Elbereth before contact.** The same sighting with no stairs near
  and the pilot standing on floor it can engrave: write Elbereth at full HP
  and hold it while the monster respects it (not the half-HP yield of 60 and
  77). Measure the two sighting tactics separately.
  Done 2026-10-18, dropped (iteration 83): -0.23 +/- 0.14 tuning, -0.14 held out; 80 engravings, XL down on both. Pre-contact tactics closed.
- [x] TRY **Keep the kitten.** Do not take the stairs down while the pet is
  within 6 squares and not adjacent (wait up to 10 turns); the pilot dies
  young on levels where a kitten still wins fights. Count pets kept past
  dlvl 3.
  Done 2026-10-18, dropped (iteration 84): -0.25 tuning, +0.25 held out, a wash; 307 waits.
- [x] TRY **Buy protection in Minetown.** A dwarf in the temple with gold of
  at least 400 times (XL plus one): #chat with the aligned priest, pay. AC
  without weight. Needs the chat prompt flow; drill a dwarf game that
  reached Minetown with gold.
  Done 2026-10-18 without a candidate (not counted): 13 of 128 games had a priest on a visited level and none held 400 times (XL plus one) gold at the time. Requeue if gold piles up (selling books would be the source).
- [x] TRY **Last-resort boulder push.** Only once a level is searched out:
  a boulder on the path to unexplored ground may be pushed toward blank map
  (iteration 71's pathing rule cost 0.83; this is the trap-reopen shape).
  Done 2026-10-18, dropped (iteration 85): -0.08 / +0.02, 11 levels reopened, no stall freed.
- [x] TRY **Mines' End: go back up.** Requeued from round 1 when the buckets
  show it; design is under the ticked task below.
  Done 2026-10-18 without a candidate (not counted): no stall on either baseline is at Mines' End (deepest stall dlvl 7, no undiggable floor). Seen instead: on seed 6000, five of 64 games stall on dlvl 1 or 2 (B17033502, 520, 528, 540, 542), two after 9,000+ turns; the shallow-stall drill is the next idea.
- [x] TRY **Excalibur, carefully.** One fountain per game, at most five dips,
  only at HP full and XL 5 or more, and flee a water nymph on sight.
  Iteration 81's version dipped 479 times and lost 0.45.
  Done 2026-10-18, dropped (iteration 86): -0.17 / +0.16, a wash; 157 dips in 49 games. Closed.
- [!] blocked TRY **#enhance** (waiting on Dave's answer in Questions for Dave; iteration 80 measured it): iteration 80's
  code, kept as the base for the readiness package.

### Round 1 tasks (done)

- [x] TRY **Elbereth under a third HP with a slow killer.** The ledger says
  melee under 1/3 HP ends in death within 20 turns 30% of the time and
  Elbereth 8.5%. Drill two melee deaths (buckets tool); if the pilot kept
  swinging below a third with Elbereth feasible and no ant or bee (they
  respect it but the pilot's turn is spent), make the fight standing order
  yield to Elbereth there. Mind iteration 36a: an XL 1 pilot resting on a
  smudged Elbereth died where fighting won; keep the yield to pilots that
  can take one more hit.
  Done 2026-10-18, dropped (iteration 60): cause found, the fight order outranks the ordered Elbereth so it never runs; yielding lost depth on both sets (-0.47 real, -0.30), under a quarter HP too (-0.16, -0.11), XL down. Needs a losing-fight signal, not an HP line. Reverted.
- [x] TRY **Ants and bees: fight in a corridor or on the stairs, not in the
  open.** Soldier ants, fire ants, giant ants and killer bees are 25 of 65
  melee deaths. Drill two. Likely cause: fighting a fast swarm in a room
  where several reach the pilot at once. Candidate: when a fast hostile
  (speed above the pilot's) is first seen at range and the pilot is in a
  room, step to a doorway or corridor square first, if one is within three
  steps, so one attacker at a time can reach it.
  Done 2026-10-18, dropped (iteration 61): the drill disproved the premise (25 of 31 ant and bee fights were one-on-one at near full HP; the pilot is 2+ levels behind). Tried the cause instead: wait on a cleared level while dlvl is K above XL; K=3 flat (-0.08, 0.00), K=2 worse (-0.30, -0.20) and XL did not rise. Reverted.
- [x] TRY **Pack under 600 in the Mines.** 18 games still hit "carrying too
  much to get through" after iteration 57. Drill one. Candidate: on
  entering the Mines, or on the message, drop the heaviest loot that is
  not worn, wielded, food or a known-useful tool until under 600 (weights
  from `objects.c`: iron ball, boulders, armor not worn, extra weapons).
  Done 2026-10-18 without a candidate (not counted): the squeeze now costs 11 turns in 128 games and the one stall that hit it was a trap cutting off the stairs (iteration 62 below). 24 of 128 packs end over 600 (median 421): worn body armor and 15 pick-axes.
- [x] TRY **Keep the tinning kit through the Mines.** Iteration 59's tinning
  fired in only 4 of 128 games because the kit is dropped on entering the
  Mines (57b). Once the pack rule above holds, keep the kit (100) when the
  pack stays under 600 with it. Target: starvation deaths (8).
  Done 2026-10-18, dropped (iteration 63): tinning tripled (50 corpses, 32 tins eaten) but starvation stayed at 9 and depth was flat (0.00, -0.08). Reverted. Starvation needs its own drill.
- [x] TRY **Trap crossing only to reach stairs in view.** Iteration 58 crossed
  traps to explore and lost depth (stalls became Mines deaths). The trace
  (B22492805) stands: a sleeping gas trap split a one-wide passage with the
  stairs known. Cross a known survivable trap only when the stairs down
  are in view and no other path exists, HP 60%+, nothing hostile in view.
  Done 2026-10-18, kept (iteration 62): traced from B13200240 (arrow trap in a one-wide passage, stairs drawn on its own map); stalls 16 -> 14, depth flat (-0.02, -0.05). Replay 20261008-132002/B13200240.
- [x] TRY **Remaining "stairs seen, no way on" stalls.** 16 stalls across the
  baselines, all "explored, searched the walls". Drill the three shallowest
  with the replay page's unseen overlay (it shows the hidden passage): sort
  them into hidden passage never searched, stairs known but unreachable,
  and plain unexplored; fix the biggest group's cause. Hidden passages were
  9 of 15 last time: check whether the search spots cover the dead end
  nearest the unexplored side.
  Done 2026-10-18, dropped (iteration 64): 8 hidden passages, 4 dark Mines levels declared explored, 2 Mines-exit cases. Fixed the exit (arrival stairs remembered): +0.02 / -0.23; with the exit rule off 0.00 / -0.12. Reverted; three TRY tasks below come from it.
- [x] TRY **Search the walls that face blank map.** B14131132 searched 13
  spots on the far side of the level while the one secret door sat in the
  west wall of the '<' room beside a wide blank. The spot score credits
  dead ends (+250) and blank squares within 5; add a term for how much
  blank lies beyond the wall in that direction (say, blank squares within
  12 on the far side), so a room wall with an unexplored half of the map
  behind it outranks a dead end facing a few blanks. 8 of 14 stalls.
  Done 2026-10-18, kept as a different fix (iteration 68): the drill showed 5 of 13 stalls were trap-split levels, not scoring; a searched-out level now reopens through its survivable traps, holes count as a way down. +0.02 / +0.28, stalls 13 -> 7. The scoring idea itself is untested; the Review can requeue it if hidden passages still lead the stalls.
- [x] TRY **Mines policy.** Non-dwarves leave the Mines by rule (XL < 8)
  but stayed by a memory bug, and staying was no worse for depth
  (iteration 64). Variants, each with the arrival stairs remembered:
  leave only below XL 5; leave only after Minetown; never leave. Judge by
  depth; Mines deaths will rise and that is allowed.
  Done 2026-10-18, dropped (iteration 69): leave below XL 5 is +0.03 / -0.08; with iteration 64's arms (below 8, never) three policies are flat. Closed.
- [x] TRY **Dark caves declared explored.** B14131162 (Mines, dlvl 3): the
  pilot searched walls with 472 passable squares never drawn and no
  secrets on the level. Drill why explore and probe_dark gave up: the
  frontier test needs a walkable square next to blank, and in a dark cave
  the floor is blank until stood on, so a frontier square may itself be
  undrawn. Fix the frontier for dark floor, then measure.
  Done 2026-10-18, kept (iteration 70): not the frontier; a trap with a coyote beyond it, then a square marked blocked by a peaceful gnome shut the pocket. Crossing now needs nothing adjacent; blocked squares are forgotten before a level is given up. +0.02 / +0.08, stalls 7 -> 5, none worse.
- [x] TRY **Dig down with a pick-axe.** 15 of 128 games end carrying a
  pick-axe (dwarves drop them) and the pilot never applies it. `#apply`,
  then `>` digs through the floor in a few turns: a way past every "no way
  on" and a faster descent when the level is cleared. Mind shops (never
  dig in one) and the Sokoban and Wizard's Tower floors (undiggable, the
  game says so). Drill a game that carried one into a stall first.
  Done 2026-10-18, kept (iteration 65): +0.23 / +0.08, no-way-on stalls 14 -> 13, 42 digs in 11 games. Replay 20261018-141311/B14131150.
- [x] TRY **Mines' End: go back up.** A pilot at the bottom of the Mines
  (dlvl 10 to 13, no '>', floor too hard to dig) ends "no way on". The way
  on is up: climb to the Mines branch level and take the main dungeon's
  '>'. Needs: recognise the bottom (the undiggable floor message, or the
  level fully explored with no '>' in the Mines), then a standing order
  that climbs '<' level by level until the dungeon is the Dungeons of Doom
  (memory per level number is shared between branches: wipe as
  _leave_mines does). Drill B14131150's replay (R14131150) first.
  Done 2026-10-18 without a candidate (not counted): no stall on the baselines is at Mines' End; four of five are hidden-passage searches at dlvl 2 to 5. Requeue when the buckets show it.
- [x] TRY **Search the walls that face blank map (scoring).** Requeued: four of the
  five remaining stalls search for hidden passages for 348 to 4,709 turns on
  levels whose '>' exists. Drill B15173847 (4,709 turns): where were the
  secrets, where did it search. Then the scoring term from the earlier task.
  Done 2026-10-18 without a candidate (not counted): three stalls, three different causes (Mines exit, molds in both exits, an unfindable secret under bad Luck); none is scoring. See the check log.
- [x] TRY **Throw only at monsters no faster than the pilot.** Throws at
  faster monsters were 1% effective in the ledger; the turn is better spent
  closing or escaping. Drill one game where throws preceded a melee death.
  Done 2026-10-18, dropped (iteration 66): -0.31 / +0.02; the thin premise (5 deaths within 20 turns of such a throw) did not hold, the damage lands before an unavoidable melee. Reverted.
- [x] TRY **Wand deaths: break line of sight.** 7 deaths to wands and bolts.
  Drill two. If a zapper is seen (a gnome lord with a wand, a `@` that
  zapped), step out of its line rather than approaching head-on.
  Done 2026-10-18, kept (iteration 67) as a different fix: 2 of 7 were kicked shop doors (the engraving was read at a --More-- the explore routine never saw); guard moved to every snapshot. +0.05 / +0.03, wand deaths 7 -> 6. Line-of-sight against zappers (4 of 7) is still open: add it as a TRY if wands stay in the top buckets.
- [x] TRY **Molds holding the only exits.** B15173825: a yellow mold and a
  green mold in a room's two exits, a boulder in the corridor beyond, 2,538
  turns of searching. Yellow and red molds hurt only on contact (1d4 stun,
  0d4 fire): at full HP, melee one that stands in a doorway or a corridor
  on the only path to unexplored ground; green and brown (4d6 acid, 6d4
  cold) stay on the throw-or-wait list. One game on the baselines.
  Done 2026-10-18, dropped (iteration 71): the molds were not the blocker (a boulder sealing a dark corridor was); clearing molds measured flat, pushing boulders toward blank map as a pathing rule -0.83. A last-resort boulder push (searched-out level only, on the path to unexplored ground) is a possible TRY.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: rest to 80% HP before the stairs down (arrivals under 80% died within 150 turns at 2 to 4 times the rate). Dropped (iteration 72): -0.33 / -0.14, the resting turns cost more than the healthier arrivals save.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: vault guards killed 4 of 128 pilots that neither answered, dropped the gold nor followed. Kept (iteration 73): guard deaths 4 -> 0, +0.02 / +0.08, none worse.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: after an HP prayer with a foe adjacent, flee up known stairs (30 of 101 deaths refought the monster that forced the prayer). Dropped (iteration 74): -0.22 / -0.19, the adjacent monster follows up the stairs.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: emergency zap of a carried wand (27 of 47 dying pilots had one) or quaff of an unknown potion when losing with the prayer gate shut. Dropped (iteration 75): -0.03 / +0.02, deaths delayed a few turns. Kept from it: text windows are closed with Escape (two games spun 600 s on an enlightenment window).
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: prayer gamble at 500 turns since the last prayer (88% odds, was 700 at 90%). Dropped (iteration 76): -0.03 / -0.02, 3 games changed per set; the critical window is skipped by fast hitters.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: Elbereth at half HP against a fast monster above the pilot's level (the one melee group lost one time in four). Dropped (iteration 77): -0.19 / +0.02. Fifth flat melee tactic; the Review should turn to readiness, not tactics.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: read-test unknown scrolls when safe (pilots die with 2 to 5 unread scrolls and know none). Dropped (iteration 78): -0.67 / -0.84 real; the bad scrolls cost more than unused good ones earn. Build the uses before the identification.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: body armor upgrades (chain mail lay on 47 level sets while 28 pilots fought in leather). Dropped (iteration 79): -0.36 real / -0.02; upgraded games lost 3 to 5 levels. Kept from it: a stuck routine passes a turn; the handless state (polymorph) stops doors and Elbereth.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: #enhance weapon skills when offered (75 of 128 games never claimed one). Dropped by the rule (iteration 80): depth 0.00 / -0.09, XL +0.19 / +0.23 real. Asked Dave.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: dip the long sword for Excalibur at XL 5+ (66 of 128 games had a fountain in reach). Dropped (iteration 81): -0.45 / -0.47 real; 27 Excaliburs against 151 curses, 100 water nymphs, 23 water demons.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: seed 6000's dlvl 1 and 2 stalls were stairs hidden under a statue and a box. Kept (iteration 87): read "There is a staircase here", stand on every object square before giving up; held out +0.22, stalls 10 -> 7, none worse.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: two stall mechanisms (a mold killed from a distance keeps its square barred; a floating eye 3 squares down the only corridor). Dropped (iteration 88): both replays unstuck, stalls 7 -> 5, but held out -0.16 past its margin. The kill-after-throw memory fix is sound and small; carry it with a later candidate.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: starving pilots ate 8 to 25 of 29 to 86 safe kills; eat corpses up to 20 steps away unless a hostile is within 8. Kept marginally (iteration 89): starvation 11 -> 9, depth -0.08 / -0.08 within noise.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: engrave-test unknown wands, zap a known digging wand down. Dropped (iteration 90): -0.11 / -0.19; lightning blinds, create monster summons, charges and turns.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: the sessile-kill memory fix alone. Dropped (iteration 91): tuning flat, held out -0.19 real (0 better, 5 worse). Twice measured, twice down on seed 6000; closed.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: buy food in shops (76 of 128 games pass one with food). Dropped (iteration 92): never fired, the pilots are poor when they pass shops. Needs a lower gold gate and a drop on "not enough", plus selling books; Review item.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: wear safe cloaks (smock, elven, the four magic ones). Dropped (iteration 93): -0.20 / +0.20, a wash; body armor unaffected.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: the small buckets drilled; praying deaths are the gamble's designed cost; the two brain loops were handless pilots. Kept as correctness (iteration 94): critical HP fights when handless; two stall labels became deaths, nothing else changed.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: a pilot pocketed by its own weight rule (shed unknown potions at a failed squeeze) and a door given up after six kicks (kick 20). Dropped (iteration 95): -0.41 / -0.25 together, -0.22 / -0.20 potions alone; both stalls freed, the rest of the games worse.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: no candidate (not counted). The "poisoned by a rotted glob" deaths (desperate meals) are not on the current baselines; excluding globs from desperate meals is a one-line tweak to bundle with a later candidate. Ideas with evidence are running out; the next pass takes one more or declares none worth a pass, so the Report and the round 3 Review can run.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
  2026-10-18: walk to where a thrown dagger should lie (42 of 128 end with no throwing weapon). Dropped (iteration 96): -0.30 / +0.31, a wash with 7,383 extra steps. No further idea worth a pass this round; the TRY list ends here so the Report and Review can run.
- [x] TRY **Re-drill after a new best.** After every kept TRY, rerun the
  buckets tool on the new baselines and, if the order of the buckets
  changed, reorder the TRY list above and say so. Add a fresh unchecked
  copy below it each time it is used.
  Done 2026-10-18 (round 2, not counted): on 20261018-181737 / 181827 the order is unchanged: melee 81 (63%), Mines 21, stalls 10 and 1 blocked, starving 9, praying 3, wand 3. No TRY task is left; the Report follows.

## 3. Finish

- [x] **Report.** When a stop condition in the spec's "Done" is met: write
  the end of the round in `docs/pilot-loop.md` under "Round 1" (which stop,
  baselines against best on both sets, what was kept and dropped, games to
  replay).
  Round 3 report done 2026-10-18: nothing confirmed; the loop ends after three rounds at 7.25 (seed 1000) / 6.67 (seed 7000), from 7.02 / (seed 5000) 6.81 at the start. See docs/pilot-loop.md "Round 3 report".
  Round 2 report done 2026-10-18: stopped on an empty TRY list; flat (-0.08 tuning, +0.14 seed 6000); three keeps (87, 89, 94), eleven drops. See docs/pilot-loop.md "Round 2 report".
  Done 2026-10-18: round 1 stopped on no gains after eight TRYs; best 7.33 / 7.31 (7.32 over 128) from 7.02 / 6.81 (6.91); six behaviour changes and four correctness fixes kept, sixteen candidates dropped. See docs/pilot-loop.md "Round 1 report".
- [x] **Review.** When Report is ticked and another round is allowed: do the
  spec's "Rounds" steps 1 to 4. Then add the next round's tasks, set Round
  to the next one with its held-out seed (6000, then 7000), put a task
  first in section 2 to score the best on the new held-out seed (the new
  held-out baseline), set "TRY passes in a row with no new best" to 0,
  untick Report, and leave a fresh unticked copy of this Review task under
  it.
  Done 2026-10-18: round 1 reviewed (docs/pilot-loop.md "Review, round 1"); round 2 planned on held-out seed 6000.
- [x] **Review.** When Report is ticked and another round is allowed: do the
  spec's "Rounds" steps 1 to 4. Then add the next round's tasks, set Round
  to the next one with its held-out seed (7000), put a task first in section
  2 to score the best on the new held-out seed, set "TRY passes in a row
  with no new best" to 0, untick Report, and leave a fresh unticked copy of
  this Review task under it.
  Done 2026-10-18: round 2 reviewed (docs/pilot-loop.md "Review, round 2"); round 3 is a short confirmation round on seed 7000. This is the last round allowed: after its Report the loop ends.

## Questions for Dave

(The Review adds questions here, each with its best guess and what the loop
did meanwhile. Locked items wait for Dave.)

- **Push kept fixes?** The standing order (2026-09-24) is to push
  `ai-player` to `elevate` after each kept fix; uboat's loop never pushes.
  Best guess: keep pushing, the branch is yours alone. The loop pushes.
- **Keep rule: fixed 0.25 or a paired test?** At 64 games the paired
  margin on average deepest is about 0.15 to 0.35, so a 0.25 gain is
  roughly one margin and luck gets through about one try in six. Uboat
  moved to two standard errors on the paired difference. Best guess: keep
  yours, it has worked; the held-out guard in the spec catches most luck.
  The loop uses yours.
- **Target depth.** The spec says average deepest 10 on both sets as the
  next waypoint. Your number if different.
- **Keep a stronger pilot at the same depth?** Iteration 80 (#enhance when
  offered) left depth flat (0.00 / -0.09) and raised XL by 0.19 and 0.23
  (real) on both sets: more kills, no more levels. The keep rule scores
  depth only, so it was reverted. Best guess: keep it, as a free permanent
  combat gain that any later readiness work builds on; locked, so the loop
  went on without it. Replay any game of 20261018-164912 to see it fire.
