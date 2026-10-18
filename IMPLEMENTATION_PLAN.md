# Pilot loop plan

Read `specs/PILOT-SPEC.md` first. One task per pass, top unchecked first.
Tick a task `[x]` when done and add one line under it saying what happened.
Iterations continue the numbering in `docs/pilot-loop.md` (last: 59).

## Loop state

- Round: 1 of 3; held-out seed this round 5000
- Baselines (the only "before"): tuning `20261018-151649` (seed 1000, deepest 7.31, XL 5.09), held out `20261018-151738` (seed 5000, deepest 7.23, XL 5.38); over the 128 games 7.27
- Buckets on the baselines (`python3 -m pilot.buckets 20261018-151649 20261018-151738`): died in melee/other 70, died in the Mines 33, starving 8, wand or bolt 6, stall: no way on 5, praying 4, invisible monster 1, brain loop 1
- Current best: the engine at the iteration 70 commit (blocked squares forgotten, crossing with nothing adjacent)
- TRY passes in a row with no new best: 2 (the stop is 8, or no TRY left)
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
- [ ] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy of this task each time it is used.
- [ ] TRY **Re-drill after a new best.** After every kept TRY, rerun the
  buckets tool on the new baselines and, if the order of the buckets
  changed, reorder the TRY list above and say so. Add a fresh unchecked
  copy below it each time it is used.

## 3. Finish

- [ ] **Report.** When a stop condition in the spec's "Done" is met: write
  the end of the round in `docs/pilot-loop.md` under "Round 1" (which stop,
  baselines against best on both sets, what was kept and dropped, games to
  replay).
- [ ] **Review.** When Report is ticked and another round is allowed: do the
  spec's "Rounds" steps 1 to 4. Then add the next round's tasks, set Round
  to the next one with its held-out seed (6000, then 7000), put a task
  first in section 2 to score the best on the new held-out seed (the new
  held-out baseline), set "TRY passes in a row with no new best" to 0,
  untick Report, and leave a fresh unticked copy of this Review task under
  it.

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
