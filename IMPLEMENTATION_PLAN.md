# Pilot loop plan: campaign 2

Read `specs/PILOT-SPEC.md` first, including its "Campaign 2" section, which
overrides the older sections where they differ. One task per pass, top
unchecked first. Tick a task `[x]` when done and add one line under it saying
what happened. Iterations continue the numbering in `docs/pilot-loop.md`
(last: 100). Campaign 1's plan is archived in `docs/PLAN-campaign-1.md`;
its three round reports are in `docs/pilot-loop.md`.

## Loop state

- Campaign 2, round 1 of 3; held-out seed this round 8000 (128 games per set)
- Baselines (the only "before"): tuning `20261018-202858` (seed 1000, 128 games, deepest 6.98, XL 5.27); held out `20261018-203302` (seed 8000, 128 games, deepest 7.37, XL 5.57)
- Current best: the engine at the iteration 94 commit plus #enhance
- TRY passes in a row with no new best: 1 (the stop is 6, or no TRY left)
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

## 2. Round 1 (held-out seed 8000)

- [x] SWEEP **Standing orders.** Never tuned. One variant at a time, on top of
  the base: retreat_below 0.25 / 0.45; rest_below 0.35 / 0.65 / 0.8;
  fight_up_to as XL+1 / XL+3 (add an order `fight_margin` if needed); eat_at
  "Weak"; explore_fully false; eat_corpses "hungry". Then combine the two
  best. Best two go to the full pair.
  Done 2026-10-18, nothing kept (iteration 101): ten variants, best eat_at Weak +0.23 and explore_fully false +0.16 on tuning; on the pair +0.13 and +0.11 pooled, flat; together +0.04, flat. fight_margin 1 is the only clear loss (-0.11 +/- 0.05). The defaults are near optimal.
- [ ] TRY **Learned avoidance.** Replace the fixed difficulty limit for a
  fight with the danger table: an adjacent monster whose (name, gap band)
  death rate's lower bound is over a threshold is treated like the avoid
  list (no melee; back off, Elbereth if it respects it, stairs if near).
  Sweep the threshold (0.15, 0.25, 0.35) through the sweep tool first.
- [ ] BUILD **Active leveling.** Campaign 1's XL gate waited in place and
  met one weak monster per 70 turns. Instead, when dlvl minus XL is 2 or
  more and the level is explored: patrol (walk to the farthest explored
  squares in turn, then back up a level and patrol there) for up to N turns
  per level, fighting what comes. Pass 1: the patrol routine behind
  `PILOT_PATROL=0`. Pass 2: sweep N (300, 800) and K (2, 3).
- [ ] BUILD **Altar knowledge.** Remember altars. When an altar is reachable
  and nothing hostile is in view, drop every unknown item on it (one `D`
  with all classes), read the flashes ("black flash" cursed, "amber" blessed),
  pick them back up, and keep the B/U/C in memory by inventory text. Uses
  in the final pass: wear unknown-curse armor only when known uncursed; read
  uncursed scrolls at full HP in a safe room (campaign 1's blind reading lost
  0.7: cursed and bad scrolls were the cost); drop known-cursed junk.
- [ ] BUILD **Price identification.** In a shop with the keeper in view, pick
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
- [ ] BUILD **Use what is known.** Act on identified or price-classed items:
  read enchant armor (class 80 after the altar says uncursed: either result
  helps), enchant weapon, remove curse; read magic mapping on arrival when
  the stairs are not seen; quaff known healing potions at critical HP with
  prayer shut; read a known teleportation scroll when losing a fight with
  prayer shut (campaign 1 found 47 of 101 deaths there); zap known attack
  wands then. Final pass measures the three knowledge builds together.
- [ ] BUILD **Gold economy.** Sell spellbooks and gems in shops (drop the
  item, answer "Sell it?" with y), then buy food when carrying little (lower
  the gold gate to 60, drop the item on "You don't have enough"), then pay a
  temple priest for protection when gold reaches 400 times (XL plus one)
  (#chat, answer the donation prompt). Each part behind its own flag.
- [ ] TRY **Your own idea**: from the biggest bucket's drill, the likeliest
  cause not covered above; describe it in one line here before trying it.
  Add a fresh copy each time it is used.
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
- [ ] **Review.** When Report is ticked and another round is allowed: do the
  spec's "Rounds" steps 1 to 4. Then add the next round's tasks, set Round to
  the next one with its held-out seed (9000, then 10000), put a task first
  in section 2 to score the best on the new held-out seed at 128 games, set
  "TRY passes in a row with no new best" to 0, untick Report, and leave a
  fresh unticked copy of this Review task under it.

## Questions for Dave

(The Review adds questions here, each with its best guess and what the loop
did meanwhile. Locked items wait for Dave.)

- Answered 2026-10-18 ("I trust you", campaign 2): #enhance adopted; keep
  rule is now the pooled paired test in the spec; 128 games per set; target
  stays 10; pushing continues.
