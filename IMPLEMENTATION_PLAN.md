# Pilot loop plan: campaign 2

Read `specs/PILOT-SPEC.md` first, including its "Campaign 2" section, which
overrides the older sections where they differ. One task per pass, top
unchecked first. Tick a task `[x]` when done and add one line under it saying
what happened. Iterations continue the numbering in `docs/pilot-loop.md`
(last: 100). Campaign 1's plan is archived in `docs/PLAN-campaign-1.md`;
its three round reports are in `docs/pilot-loop.md`.

## Loop state

- Campaign 2, round 3 of 3; held-out seed this round 10000 (128 games per set)
- Baselines (the only "before"): tuning `20261019-003024` (seed 1000, 128 games, deepest 7.88, XL 5.67); held out `20261019-085932` (seed 10000, 128 games, deepest 7.20, XL 5.62)
- Current best: the engine at the iteration 94 commit plus #enhance plus heavy body armor (iteration 109) plus the hunger prayer gamble at 500 turns (iteration 110) plus Excalibur (iteration 111) plus refused diagonals remembered as steps (iteration 116) plus dwarves out of the Mines below XL 8 (iteration 117)
- TRY passes in a row with no new best: 4 (the stop is 6, or no TRY left)
  (TRY, SWEEP and the final pass of a BUILD count; a new best resets it to 0)

## What campaign 1 taught (the reasons for this plan)

- About 60% of deaths are fights started at full HP against a fast monster
  above the pilot's level, with the pilot two or more levels below where its
  XL belongs. Eight in-fight rules never moved depth. The pilot loses because
  it arrives weak and ignorant: Basic skill, AC 5 or 6, no item known.
- Small fixes to rare stalls free their games and cost depth elsewhere.
- 64 games per set cannot see 0.15 levels; four "gains" were noise.
- Nothing in the engine has ever been tuned as a number (retreat_below,
  fight_up_to, rest_below were set by hand in September).

So: a better instrument first, then readiness through multi-pass builds.

## 1. Setup and tools (not TRYs)

- [x] **1.1 Adopt #enhance and re-score the baselines.** Re-apply iteration
  80's code (in git history: `git log --oneline --grep "enhance"` and the
  check-log row; "You feel more confident in your" sets a flag, #enhance at
  the next command prompt, the skill menu answered with its first item).
  Then run the rules pilot on `--seed 1000 --games 128` and on `--seed 8000
  --games 128` and write both run ids, deepest and XL into Loop state as the
  baselines. Commit and push.
  Done 2026-10-18: #enhance re-applied (177 skill advances across the pair); seed 1000 x128 `20261018-202858` 6.98 / XL 5.27 (melee 74, Mines 24, starving 12, no way on 11, wand 4, praying 3); seed 8000 x128 `20261018-203302` 7.37 / XL 5.57 (melee 83, Mines 24, starving 10, no way on 6, invisible 3, praying 1, wand 1). Load was 100 to 126 (the uboat loop); no time-limit game, longest 104 s.
- [x] **1.2 Pooled comparison.** `python3 -m pilot.compare --pool A1 B1 A2 B2`
  pairs A1 with B1 and A2 with B2 by game, pools the per-game depth and XL
  differences, prints each set's mean and SE, the pooled mean and SE, and the
  verdict under the campaign 2 keep rule. A self-check with made-up runs.
  Done 2026-10-18: `python3 -m pilot.compare --pool A1 B1 A2 B2` prints each set and the pooled mean and SE with a keep / flat / drop verdict; `--check` tests it. Found and fixed on the way: games were matched by the last two characters of their names, which collide in a 128-game run (games 0 to 27 against 100 to 127); they are now matched by index. Old 64-game comparisons are unchanged (iteration 62 still reads -0.02 +/- 0.04).
- [x] **1.3 Sweep tool.** `python3 -m pilot.sweep '<json list>' --seed 1000
  --games 128 --name NAME`: each list item is a dict of standing-order
  overrides and/or `PILOT_*` environment flags; runs one batch per variant
  (each batch already runs its games 16 at a time), compares each with the
  baseline (paired), and prints a table sorted by depth gain with XL and the
  bucket counts. Needs `pilot.batch --orders '<json>'` (apply with
  `engine.set_orders` at game start) and `--env '<json>'`. A self-check.
  Done 2026-10-18: `pilot.batch --orders '<json>' --env '<json>'` (orders applied with set_orders at game start, unknown names rejected; env set before the worker pool so every game inherits it; both recorded in the run file); `python3 -m pilot.sweep '<json list>' --base RUN` runs one batch per variant, pairs each with the baseline by game index, prints a table by depth gain with XL, buckets and any time-limit games, and writes sweep-NAME.json. `--check` passes; a 2-game smoke run recorded its orders and env.
- [x] **1.4 Danger table.** `python3 -m pilot.danger <runs...>` reads the
  tactic outcomes (`pilot.ledger.rows`) and writes `pilot/danger.json`:
  for each monster name and each gap band (difficulty minus XL: <=0, 1-2,
  3+), tries, melee deaths within 20 turns, and the rate with a lower
  confidence bound. Build it from every rules run of seeds 1000 and 5000 on
  disk. Prints the 20 worst rows.
  Done 2026-10-18: `python3 -m pilot.danger` reads 112 plain rules runs of seeds 1000 and 5000 (never 6000+), merges per-turn melee decisions into fights (same monster, same game, under 20 turns apart), and writes pilot/danger.json: 303,414 fights in 339 (monster, gap) rows with a Wilson lower bound. Worst by lower bound: werewolf at gap 1-2 (88% of 74 fights end in death within 20 turns), fire ant and soldier ant at 1-2 (79%), black unicorn, dwarf lord, white unicorn; soldier ants kill 74% even at gap 0 or less (449 fights), fire ants 46%. The monster matters more than the gap.

## 2c. Round 3 (held-out seed 10000)

- [x] **Held-out baseline for round 3.** The best on `--seed 10000 --games 128`;
  write the run id and numbers into Loop state. Not a TRY.
  Done 2026-10-19: `20261019-085932`, deepest 7.20, XL 5.62; melee 93, no way on 9 and 5 blocked, Mines 7, wand 6, starving 6, invisible 2. Load 6; no time-limit game, longest 111 s.
- [x] TRY **Walk away from slow monsters.** Adjacent and above the fight limit,
  a monster slower than the pilot (speed under 12: mimics 3, zombies 6 to 8,
  molds 0) is stepped away from, not fought. B003753104 (XL 1, 8 HP) traded
  blows with a small mimic until it died.
  2026-10-19 cause: the standing orders escalate any adjacent monster above the fight limit, and the rules brain answers "fight"; spoiler() already marks the ones slower than the pilot (outrun). Step away from those first.
  Dropped (iteration 124): pooled +0.02 +/- 0.05; melee 104 -> 102 and 93 -> 94.
- [x] TRY **The early heavy pack.** B00375397 is refused a squeeze at turn 913,
  XL 2: find what it picked up that weighs that much (replay its inventory)
  and stop picking that up.
  2026-10-19 cause: at the refusal B00375397 carries about 465 known (banded mail 250, sword, shield, three potions) plus a bag of unknown contents, never opened; over 600 refuses a squeeze. Treat bags as dead weight (dropped first when a squeeze is refused, not picked up in the Mines).
  Dropped (iteration 125): pooled +0.09 +/- 0.09; no way on 10 -> 9 and 14 -> 14. B00375397 freed (dlvl 3 -> 8).
- [x] TRY **The early give-up.** B00375353 stalls on dlvl 3 at turn 1120 after
  a few hundred turns of searching: find why the search ended (probe it) and
  fix that.
  2026-10-19 cause: a teleport trap put B00375353 in a dark corridor whose only way on is east past a boulder; step_ok plans a boulder push only into known floor, and dark corridor beyond is blank, so the push is never tried and the level reads explored. Allow pushes into unknown squares.
  Dropped (iteration 126): pooled -0.14 +/- 0.26 (-0.65 and +0.36); the drilled game was not freed. A narrower form (only once the level reads explored with no stairs known) is untried.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: iteration 126's drill (B00375353, a boulder in a dark corridor between the pilot and the stairs); pushes into dark squares everywhere rerouted every game, so allow them only once a level is searched out with no way on, like the trap reopen.
  Dropped (iteration 127): pooled -0.01 +/- 0.01; 19 levels reopened, none to the stairs.
- [ ] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
- [ ] BUILD **Sokoban, level 1 (stretch).** As described in round 1's list.

## 2b. Round 2 (held-out seed 9000)

- [x] **Held-out baseline for round 2.** The base on `--seed 9000 --games 128`;
  write the run id and numbers into Loop state. Not a TRY.
  Done 2026-10-18: `20261018-224138`, deepest 6.85, XL 5.38; melee 62, Mines 30, starving 18, no way on 7 and 3 blocked, wand 7, invisible 1.
- [x] SWEEP **Dive with a depth cap.** Iteration 106's dive (take known stairs
  down before looting or exploring, HP 70%+, not hungry, nothing hostile in
  view; the code is described in its check-log row) with a new flag
  `PILOT_DIVE_MAXDLVL`: dive only while dlvl is at most 3, 5, 7. Early levels
  give little experience and cost turns and food. Best two to the pair; the
  XL guard judges.
  Done 2026-10-18, nothing kept (iteration 107): caps 3 / 5 / 7 gave +0.10 / +0.24 / +0.41 depth and -0.44 / -0.33 / -0.67 XL on tuning; cap 5 pooled +0.23 +/- 0.19, XL -0.44 real. About 1.5 XL per level at every cap.
- [x] TRY **Dive plus patrol.** The best dive cap with iteration 103's patrol
  (commit 3e13bbdf5, `PILOT_PATROL_TURNS` 300 / 800 at K 2): patrol gave
  +0.2 to +0.3 XL, dive spent 0.8; together they may keep the depth and pass
  the guard.
  Done 2026-10-18, dropped (iteration 108): N 800 -0.48 depth / -0.42 XL, N 300 -0.21 / -0.30; worse than either alone.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-18 cause: melee deaths at AC 6 to 3 while heavy body armor lies on the floor; SAFE_ARMOR stops at chain mail's weight, so banded, splint and plate mail (always identified, well within a Valkyrie's capacity) are never picked up (seen in the replays about 40 times in 128 games).
  KEPT (iteration 109): pooled +0.22 +/- 0.09, XL +0.14 +/- 0.05; seed 1000 7.23 (+0.26), seed 9000 7.04 (+0.19); body armor worn 76 -> 89 and 71 -> 94. Replay B23070591 (4 -> 12). Follow up: swapping worn armor for a better piece (a leather jacket kept over plate mail) is untried.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-18 cause: starvation (13 and 20 games): every one was Weak again 400 to 900 turns after the prayer that fed it, with the 1000-turn gate shut and nothing safe to eat. (Armor upgrades were drilled first: only 8 of 128 games stepped on better body armor, too few.)
  KEPT (iteration 110, bucket clause): pray when Weak 500+ turns after the last prayer; starving 13 -> 7 and 20 -> 10, pooled +0.09 +/- 0.05. Replay B23254489.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-18 cause: melee (79 and 63) is lost on damage, and the Valkyrie's standard answer was never used: dipping the long sword into a fountain at XL 5+ (102 of 128 games reach it) for Excalibur. (Mines deaths drilled first: spread over a dozen killers, no single cause.)
  KEPT (iteration 111): pooled +0.41 +/- 0.12, XL +0.12; 56 Excaliburs in 256 games, those games +2.5 levels; 9 games lost to water demons or moccasins. Follow up: retreat from a water demon or moccasins instead of fighting them. Replay B23321394 (9 -> 22).
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-18 cause: 31 of 256 games end "no way on", 9 with the '>' on the pilot's own map; B23345327 is walled into a Minetown shop doorway by two squares in memory.blocked, and peaceful blocks never expire.
  Dropped (iteration 112): expiring peaceful blocks after 100 turns, pooled +0.02 +/- 0.07; the drilled game stayed stuck, so the blocks there came from elsewhere (likely the stuck guard). Follow up: log which code adds each blocked square in the 9 games before changing anything.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-18 cause: B23345327's walls came from the stuck guard, not a peaceful: a corpse lay on an open door, the map showed no door, the pilot tried to step off it diagonally (NetHack forbids that), nothing happened, and both diagonal squares were blocked for good. "There is an open door here." was never recorded.
  Dropped, near miss (iteration 113): recording the door, pooled +0.16 +/- 0.10 (both sets up, 1.6 SE), no way on 11 -> 11 and 16 -> 10. Re-pool with the next movement change.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: only 56 of 256 games got Excalibur; 27 lawful XL 5 games had a fountain in view on the level where they reached XL 5 and never dipped: a sessile mold in view blocks the dip (it checks every visible hostile), e.g. B23321390 with a red mold in sight for 168 of 400 turns.
  Dropped (iteration 114): mobile hostiles only, pooled +0.03 +/- 0.06, Excaliburs 28 -> 31 and 28 -> 27. The dip runs only between routines; next try it from the standing orders.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: the dip is checked only in the default activity, between routines; in B23321390 loot and explore routines filled almost every turn after XL 5 with a fountain on the level. Try it as a standing order (ahead of routines), mobile hostiles only.
  Dropped (iteration 115): pooled +0.02 +/- 0.08; dips barely moved (160 -> 172, 192 -> 175). Excalibur is limited by fountains, not scheduling.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: the stuck guard reads a refused diagonal step as a wall and blocks the target square for good (B23345327, iteration 113's drill); remember the refused step instead, together with iteration 113's door line (its near miss, re-pooled as its row asked).
  KEPT (iteration 116, bucket clause): no way on 14 -> 13 and 17 -> 10, pooled +0.12 +/- 0.16; B23345327 freed (dlvl 5 -> 9).
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: the Mines bucket (19 and 33) is almost all dwarves (49 of 55): _leave_mines exempts dwarves, and 46 of their Mines deaths came under XL 8. Send dwarves out below XL 8 too (variant: below XL 5).
  KEPT (iteration 117, bucket clause): Mines 19 -> 4 and 36 -> 4, pooled +0.12 +/- 0.11, XL +0.16 +/- 0.06 real. XL 5 variant -0.11 on tuning. Replay B00375374 (8 -> 19).
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: the water demon and water moccasins from fountain dips kill 10 of 256 games (as many as soldier ants); the pilot dips at any "fine" HP (B003024110 at 43 of 62) with or without a prayer left. Dip only at full HP with the prayer gate open (variant: full HP only).
  Dropped (iteration 118): full HP and prayer -0.34 on tuning; full HP only pooled -0.15 +/- 0.14. Delaying the dip costs more than the dip deaths.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: 9 of 25 "no way on" stalls had been refused a tight diagonal ("carrying too much to get through", over 600 weight); with no junk to drop the engine routes around tight corners for good, and B00302416 (scale mail worn) is boxed into a Mines pocket. Take off and leave the body armor instead.
  Dropped (iteration 119): armor shedding plus a wider junk list pooled -0.13 +/- 0.14 (no way on 10 -> 8, 15 -> 13; armor shed 94 times); junk list only pooled -0.01 +/- 0.09.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: in B00375395 (a hidden-stairs stall) one corridor square blocked for good by a peaceful at turn 1910 cuts the level in half; every secret door is on the far side. Re-test iteration 112's 100-turn expiry for peaceful blocks now that iteration 116 removed the stuck guard's walls.
  Dropped (iteration 120): pooled +0.05 +/- 0.10, no way on 10 -> 13 and 15 -> 12; flat twice, retired.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: melee (101 and 87) and the pilot never wears a cloak, though every cloak is safe in 3.6 (the random four are protection, invisibility, magic resistance, displacement) and MC blocks some poison stings (soldier ants, the top killer); 31 of 128 tuning games saw one, mummy wrappings 182 times. Wear cloaks over body armor.
  Dropped (iteration 121): pooled +0.05 +/- 0.15; 120 cloaks worn, mostly mummy wrappings.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: diving gained depth (+0.49) but cost XL in weak pilots (iteration 106); an Excalibur pilot is not weak, yet it still clears every level. Dive only with Excalibur wielded (variant: only while dlvl - XL <= 2).
  Dropped (iteration 122): pooled +0.04 +/- 0.14, XL -0.17 +/- 0.06 real; the gap-2 variant -0.05 on tuning.
- [x] TRY **Your own idea** (fresh copy): from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  2026-10-19 cause: 18 of 190 melee deaths came 500 to 700 turns after the last prayer, where the critical-HP gamble (700) still waits; the hunger gamble at 500 was kept (iteration 110). Gamble at 500 (variant 400).
  Dropped (iteration 123): pooled -0.01 +/- 0.05; 400 -0.02 on tuning. Sixth TRY with no new best: round 2 stops here.
- [ ] BUILD **Sokoban, level 1 (stretch).** As described in round 1's list.

## 2. Round 1 (held-out seed 8000)

- [x] SWEEP **Standing orders.** Never tuned. One variant at a time, on top of
  the base: retreat_below 0.25 / 0.45; rest_below 0.35 / 0.65 / 0.8;
  fight_up_to as XL+1 / XL+3 (add an order `fight_margin` if needed); eat_at
  "Weak"; explore_fully false; eat_corpses "hungry". Then combine the two
  best. Best two go to the full pair.
  Done 2026-10-18, nothing kept (iteration 101): ten variants, best eat_at Weak +0.23 and explore_fully false +0.16 on tuning; on the pair +0.13 and +0.11 pooled, flat; together +0.04, flat. fight_margin 1 is the only clear loss (-0.11 +/- 0.05). The defaults are near optimal.
- [x] TRY **Learned avoidance.** Replace the fixed difficulty limit for a
  fight with the danger table: an adjacent monster whose (name, gap band)
  death rate's lower bound is over a threshold is treated like the avoid
  list (no melee; back off, Elbereth if it respects it, stairs if near).
  Sweep the threshold (0.15, 0.25, 0.35) through the sweep tool first.
  Done 2026-10-18, dropped (iteration 102): threshold 0.25 -0.15 +/- 0.08, 0.45 -0.05 +/- 0.03 on tuning; more avoidance, more loss. 0.15 not run (the trend is monotone). The fast killers come back.
- [x] BUILD **Active leveling.** Campaign 1's XL gate waited in place and
  met one weak monster per 70 turns. Instead, when dlvl minus XL is 2 or
  more and the level is explored: patrol (walk to the farthest explored
  squares in turn, then back up a level and patrol there) for up to N turns
  per level, fighting what comes. Pass 1: the patrol routine behind
  `PILOT_PATROL=0`. Pass 2: sweep N (300, 800) and K (2, 3).
  Done 2026-10-18, dropped (iteration 103): the patrol raised XL by 0.2 to 0.3 at K 2 and lost 0.15 to 0.20 depth; at K 3 flat (-0.02, -0.03). Reverted.
- [x] BUILD **Altar knowledge.** Remember altars. When an altar is reachable
  and nothing hostile is in view, drop every unknown item on it (one `D`
  with all classes), read the flashes ("black flash" cursed, "amber" blessed),
  pick them back up, and keep the B/U/C in memory by inventory text. Uses
  in the final pass: wear unknown-curse armor only when known uncursed; read
  uncursed scrolls at full HP in a safe room (campaign 1's blind reading lost
  0.7: cursed and bad scrolls were the cost); drop known-cursed junk.
  Built and dropped 2026-10-18 (iteration 104, with the two below): altar testing worked (139 of 256 games see an altar; 436 items tested in 128 games) but nothing used the knowledge. Reverted.
- [x] BUILD **Price identification.** In a shop with the keeper in view, pick
  up each unknown scroll, potion and wand once, read the offered price from
  "For you, ... N zorkmids", drop it again. Map the base price (after the
  Cha and dunce-cap adjustments, and the 1-in-3 surcharge: take the lower of
  two quotes or both candidates) to its price class; a class with a single
  member identifies the item (scroll classes: 20 identify; 50 light; 60
  enchant weapon; 80 enchant armor or remove curse; 100 confuse monster,
  destroy armor, fire, food detection, gold detection, magic mapping, scare
  monster, teleportation; 200 amnesia, create monster, earth, taming; 300
  charging, genocide, punishment, stinking cloud). Record in memory; a
  `#name` call is optional. Pass 1: read the quote and store the class.
  Pass 2: use the classes (below).
  Built and dropped 2026-10-18 (iteration 104): shop quotes read on stepping onto items and inverted exactly (pilot/prices.py, kept as a tool with its check); 66 quotes and 4 identifications in 128 games. Reverted from the engine.
- [x] BUILD **Use what is known.** Act on identified or price-classed items:
  read enchant armor (class 80 after the altar says uncursed: either result
  helps), enchant weapon, remove curse; read magic mapping on arrival when
  the stairs are not seen; quaff known healing potions at critical HP with
  prayer shut; read a known teleportation scroll when losing a fight with
  prayer shut (campaign 1 found 47 of 101 deaths there); zap known attack
  wands then. Final pass measures the three knowledge builds together.
  Done 2026-10-18, dropped (iteration 104): the three together on seed 1000 x128 -0.16 +/- 0.21 (26 better, 38 worse); uses fired 6 times in 128 games (1 good scroll, 2 teleport escapes, 3 wand zaps). Items are almost never identified by name in this engine, so the knowledge had nothing to act on. Reverted.
- [x] BUILD **Gold economy.** Sell spellbooks and gems in shops (drop the
  item, answer "Sell it?" with y), then buy food when carrying little (lower
  the gold gate to 60, drop the item on "You don't have enough"), then pay a
  temple priest for protection when gold reaches 400 times (XL plus one)
  (#chat, answer the donation prompt). Each part behind its own flag.
  Done 2026-10-18, dropped (iteration 105): protection unaffordable (median gold 76); selling books and buying food work but fire about once per 128 games; pooled +0.01 +/- 0.03, flat. Reverted.
- [x] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy each time it is used.
  2026-10-18: dive (take known stairs down before exploring; the score is the deepest level and the death is coming anyway). Not kept (iteration 106): pooled depth +0.49 +/- 0.23 real, XL -0.83 +/- 0.14 real, fails the XL guard. Asked Dave.
- [ ] BUILD **Sokoban, level 1 (stretch).** Up from the Oracle's level's
  stairs. A boulder-puzzle solver (BFS over boulder positions, the known
  fixed maps of the two level-1 variants), never squeezing past boulders,
  never reading scrolls of earth there. The prize is the experience and the
  food on the level, and in later passes the levels above. Last on the list
  because it is the largest; skip if the rounds run out.

## 3. Finish

- [ ] **Report.** When a stop condition in the spec's "Done" is met: write
  the end of the round in `docs/pilot-loop.md` under "Campaign 2, round N
  report" (which stop, baselines against best on both sets, what was kept
  and dropped, games to replay).
  Round 1 report done 2026-10-18: stopped on no gains after six TRYs; nothing kept beyond #enhance and the tools; diving is the one real depth gain and fails the XL guard. See docs/pilot-loop.md "Campaign 2, round 1 report".
  Round 2 report done 2026-10-19: stopped on no gains after six TRYs; five changes kept (109, 110, 111, 116, 117), pooled +0.97 +/- 0.21 levels and XL +0.48 over the round. See docs/pilot-loop.md "Campaign 2, round 2 report".
- [x] **Review.** When Report is ticked and another round is allowed: do the
  spec's "Rounds" steps 1 to 4. Then add the next round's tasks, set Round to
  the next one with its held-out seed (9000, then 10000), put a task first
  in section 2 to score the best on the new held-out seed at 128 games, set
  "TRY passes in a row with no new best" to 0, untick Report, and leave a
  fresh unticked copy of this Review task under it.
  Done 2026-10-18: round 1 reviewed (docs/pilot-loop.md "Review, campaign 2 round 1"); round 2 planned on seed 9000.
- [x] **Review.** When Report is ticked and another round is allowed: do the
  spec's "Rounds" steps 1 to 4. Then add the next round's tasks, set Round to
  the next one with its held-out seed (10000), put a task first
  in section 2 to score the best on the new held-out seed at 128 games, set
  "TRY passes in a row with no new best" to 0, untick Report, and leave a
  fresh unticked copy of this Review task under it.
  Done 2026-10-19: round 2 reviewed (docs/pilot-loop.md "Review, campaign 2 round 2"); round 3 planned on seed 10000 (section 2c). Round 3 is the last: after its Report the loop ends.
- [ ] **Review.** (Round 3 is the last round; after its Report the loop ends, so this copy is not expected to run.)

## Questions for Dave

(The Review adds questions here, each with its best guess and what the loop
did meanwhile. Locked items wait for Dave.)

- Answered 2026-10-18 ("I trust you", campaign 2): #enhance adopted; keep
  rule is now the pooled paired test in the spec; 128 games per set; target
  stays 10; pushing continues.
- **Dive for depth?** Iteration 106: taking known stairs down before exploring
  gains +0.49 +/- 0.23 levels pooled over 256 games (real) and costs 0.83 XL
  (real); games are a quarter shorter. The XL guard refuses it, since depth
  bought by arriving weaker is not progress toward ascension. Best guess:
  keep refusing it as the default; it is worth knowing that the score can
  be bought this way. If you want the depth number, say so and the loop
  adopts it. Locked; the loop went on without it.
