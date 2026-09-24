# Research: GPT 6 Astra's NetHack ascension (kenforthewin/nethack_astra)

Date: 2026-09-23. Source repo: https://github.com/kenforthewin/nethack_astra (files fetched from `HEAD`).
Journal files are written newest-first, so the early game is at the bottom of each file.
Citations are `file:line` (approximate, from the fetched copies). Journal text is quoted as written: the
agent compressed its notes by dropping spaces, so quotes look like `DoNOTattackwhileonElbereth`.
Anything marked **(inferred)** is my reading, not something the source states.

**File naming correction.** The brief assumed `run-2.md` and `run-3.md` were the failed runs and
`live-run.md` the winner. It is the other way round:

| File | Run | Outcome |
|---|---|---|
| `memory/live-run.md` | Run 1 (2026-09-06) | Died, sliming, D51, T33302 |
| `memory/run-2.md` | Run 2 (2026-09-08) | Died, wand of death, Castle D25, T12271 |
| `memory/run-3.md` | Run 3 (2026-09-09 to 09-21) | **Ascended**, T37140 |

`docs/METHODOLOGY.md` confirms this: "Two campaign failures preceded the ascension: sliming on D51/T33302,
then a Castle death ray on D25/T12271. Run 3 began September 9 and ascended September 21". All three
characters were lawful dwarven Valkyries (`run-2.md:2888`, `run-3.md:10767`, `memory/session.md`).

## 1. What they built and how the agent played

A coding agent (GPT 6 Astra) played remotely on Hardfought over SSH inside tmux. It read rendered
144x36 curses terminal text and sent keystrokes through a Python harness that it wrote and changed
during the campaign (`docs/METHODOLOGY.md`). It had no game API, so there was no hidden state and no RNG
access. Nearly all judgement came from the LLM. It chose every combat action, and it was told that
"Every combat action is individually reviewed; safe movement batches use guards" (`run-3.md:10781`).
It read the NetHack wiki and the 3.6.7 source freely, and it kept its memory in Markdown journals plus
a compact JSON "emergency" reference. The helper scripts are thin:

- `scripts/session.py` sends every input through an audited tmux session. It refuses a multi-key macro
  unless a map prompt is recognized (`command_preflight`), and it has a few checked macros: `wait-pets`,
  `stash-gold` and `wrest-wish`.
- `scripts/guard.py` walks 1 to 24 movement digits one step at a time. Before each step it refuses when
  any status in `DANGERS` is shown (Slime, Stone, Ill, FoodPois, TermIll, Stun, Conf, Blind, Hallu,
  Weak, Faint, **Hungry**, Strngl, Held), when HP is under 2/3, when any letter or `@&12345;:'` glyph
  is within 2 squares (pets excluded by their highlight), or when the next tile is not known floor or an
  item (so unknown squares, doors, water and traps all stop the walk). After each step it stops on
  damage, a new "a rock falls on your head" message, a level change, a position that does not match the
  plan, more than 2 turns passing, or a new condition. The docstring calls it "Conservative movement
  batching over visible terminal state, not a game oracle".
- `scripts/route.py` is a read-only BFS over the remembered screen. It excludes traps unless
  its allow-traps flag is given, refuses diagonals through doorways, and only proposes keys ("Proposal only:
  excludes known traps, water, boulders, and occupied tiles; does not predict monster movement").
- `scripts/sokoban.py` is a push planner that checks each step when run with its execute flag.

Summary: the LLM did the strategy, the combat and the identification. Scripts only made walking and
Sokoban pushing safe and cheap. That is close to the opposite of our split, where a deterministic
engine does almost everything and the brain is consulted rarely.

## 2. How the two failed runs died, and the rule each death produced

### Run 1: sliming on D51, T33302 (`live-run.md`)

The run had already completed the invocation. `live-run.md:14-29`: "sliming began during an unsafe
24-key movement batch near known slime. At33297 Slime status recognized; attempted zh. but h was EMPTY,
and the spare period spent time. Then removing robe/GDSM consumed the remaining turns." The agent had
also wrongly believed that magic resistance blocks self-polymorph: "CRITICAL CORRECTION verified zap.c
lines2249-2255: SELF-ZAPPING POLYMORPH IGNORES MAGIC RESISTANCE. Could have used zY. immediately".

Rules it produced:
- `live-run.md:26-28`: "no blind movement batches near dangerous monsters; stop on fresh messages/status
  changes; VERIFY usable fire charges before Gehennom; maintain uncursing reserve".
- `run-2-emergency.json` `lessons`: "Movement batches use guarded incremental input; no raw movement
  batches near monsters." "Stop immediately on Slime or Stone; never spend remaining turns on an
  unverified remedy."
- A harness change: `run-2.md:2881`, "Harness: guarded incremental digit movement, no repeated
  combat batches". That is `guard.py`, whose `DANGERS` list includes Slime and Stone.

### Run 2: wand of death in the Castle, D25, T12271 (`run-2.md`)

`run-2.md:5-12`: "Killed instantly at full HP100/100 by a sergeant's wand of death in the Castle
central hallway ... The guarded eastward batch sent three steps, then stopped at the death prompt. A
visible-state movement guard cannot guarantee protection from a one-hit kill. The strategic error was
advancing through the Castle without known magic resistance or reflection." A sergeant had already hit
it with a lightning wand 60 turns earlier (`run-2.md:55-58`), and the note then read "DO NOTrealignrow21
ordiagonal casually".

Rules it produced:
- `run-3-emergency.json` `rules`: "Do not attempt Castle without known magic resistance or reflection;
  prefer both." "Unknown wand charges are not guaranteed available."
- `run-3.md:10778-10780` (run 3's opening strategy): "Healing and a high HP total do not protect from
  instant death. Avoid lining up with unknown wand users."

**Relevance to us.** Both deaths happened in the late game, far past anything our pilot reaches. The
general lessons still apply to us. First, stop a multi-step action on any new message, status or nearby
monster. Our engine already sends one key per snapshot. Second, stay off the firing lines of wand
users, which is plan item 19.

## 3. Early-game strategy for a dwarven Valkyrie, from the journals

### Opening goals
- Run 3 set its goals when it started: "Strategy: secure early armor and food, keep the pet alive,
  identify escape resources, and complete Sokoban" (`run-3.md:10777`).
- In run 1 on D2, it wrote "aim to gain XP/armor before going far deeper" (`live-run.md:3556`).

### Food and corpses
- It ate permanent food only at Hungry, one item at a time. "FIRSTFOOD hSLIMEMOLD EATEN738 forHungry737"
  (`run-3.md:10589`). "d startingFOODRATION eaten986..991 forHungry984" (`run-3.md:10528`).
- It hoarded rations and picked up every ration it saw. By T720 it had "lTHREE FOODRATIONS ... plus dUNCone
  = FOURTOTAL" (`run-3.md:10614`). It carried "l3rations jtin p2lichen foodreserve" at T1243
  (`run-3.md:10500`).
- It bought food in shops: "## T10759 bought three rations and cookie for189" (`run-3.md:7460`).
  At T8299 it also noted "fire resistance, food bought" (`run-3.md:8196`).
- It ate fresh corpses for intrinsics. Floating eye: "TELEPATHY acquired2118 fromFIRSThero-eatencorpse
  FRESHfloatingeye" (`run-3.md:10255`). Snake: "POISONRES confirmed2940 ... poisoncost13HP and4STR"
  (`run-3.md:10000-10002`). Elf: "SLEEP RESISTANCE" (`run-3.md:7784`).
- It refused bad corpses. "Corpse28,24LEFT poisonous" (kobold, `run-3.md:10693`). "DoNOTeat mold"
  (`run-3.md:10664`). "spidercorpse23,16LEFT nowOLDdoNOTeat" (`run-3.md:10021`). "Wererat ... corpse25,17
  NEVER EAT" (`run-2.md:2776`).
- Run 1 was the food-poor run, and it starved into prayer three times: "FIRST PRAYER T4324 relieved Weak"
  (`live-run.md:3397`), "SECOND PRAYER T5161 relievedWeak" (`live-run.md:3369`), "THIRD PRAYER T6010
  relievedWeak" (`live-run.md:3335`). The cause was turns burned searching D6 for a hidden Sokoban
  entrance, which it named twice: "Avoidrepeatinglongsearch!" (`live-run.md:3376`) and
  "Don'tburnmorefoodsearch" (`live-run.md:3393`).

### Prayer
- Run 3 did not pray at all until T11568: "FIRSTPRAYER11568..71 SUCCESS" (`run-3.md:7297`). Every early
  checkpoint says "No prayers used" (for example `run-3.md:10003`, `10501`, `10744`). Run 2's first prayer
  was at T6465, and it was made on a co-aligned temple altar to make holy water (`run-2.md:1879`).
- Prayer served as the emergency backup. In run 3, rations and corpses did the feeding.
- Run 1 prayed successfully at gaps of 837 and 849 turns (T4324 to T5161 to T6010). This was luck
  within the rnz(350) timeout, so it does not argue against our 1000-turn gate **(inferred)**.
- "Prayer off altar at Luck0 fixes major troubles only: do NOT equip cursed pick hoping hunger prayer
  uncurses it" (`live-run.md:3353-3354`).

### Elbereth
- A dust engraving can come out misspelled, so it read every engraving back. "DUSTElbereth2724MISSPELLED
  "Elberet}"verifiedcolon2724" (`run-3.md:10044`). "firstdust2945misspelledplbereth, replaced2946correct"
  (`run-3.md:10005`).
- It never attacked from the square. "DO NOTattackwhileonElbereth(erasespenalizes);
  recoveringin30searchturnintervals" (`run-3.md:10034`).
- Once it had a magic marker, it switched to semi-permanent Elbereth: "MARKERy2725 wroteElbereth
  spiderFLED noHPdamage" (`run-3.md:10045`).
- It used Elbereth early against a rabid rat: "retreated thenElbereth 2050at23,21 causedflee"
  (`run-3.md:10291-10292`).

### Branch order and descent pace (run 3, the winner)
The timeline comes from the section headers at `run-3.md:10342-10736`:

| Turn | Where | XL |
|---|---|---|
| T203 | D2 | 1 |
| T496 | D3 | 2 |
| T631 | Mines 1 (Dlvl4), entered from the D3 branch | 3 |
| T1243 | Minetown (Dlvl6) | 4 |
| T1670 | back up to main D4 | 5 |
| T2128 | D6 | 5 |
| T2563 | D7 | 5 |
| T3409 | D8 | 6 or 7 |
| T3916 | D9 Oracle | 7 |
| T4403 | D10 | 7 |
| T4532 | Excalibur | 7 |
| T4710 to about T6000 | Sokoban | 7 to 8 |

- As a dwarf, it found the Mines mostly peaceful and checked each gnome with farlook. "Allgnomes examined
  peaceful ... GNOMELORD38,18 verified716" (`run-3.md:10620-10622`). "Dwarf54,21 peaceful verified922"
  (`run-3.md:10549`).
- It stopped at Minetown and went back up. "NextSELLtringmail in generalstore, consider67goldmarkerhardware,
  returnUP13,16 andmainD4towardSokoban. Do not descenddeeperMinesunderprepared" (`run-3.md:10405-10406`).
  It came back for the lower Mines and Mines' End only around T9000 to T10000, at XL10 or higher
  (`run-3.md:7643-8055`).
- Run 2 took the other order: Sokoban first (from T1497), then Excalibur on D4 at T5904, then the Mines
  from T6163 (`run-2.md` headers 1954-2682).
- Sokoban's entrance is the second up staircase on the level below the Oracle, and it can be hidden.
  In run 2 it was behind a hidden door that took searching to find ("W HIDDENdoor17,17 found1481",
  `run-2.md:2713`). In run 1 it could not be found by searching and was dug to at T11313
  (`live-run.md:3097-3125`).

### Minetown
- "No known traps on Minetown; doNOTkickdoors/dig/tamperfountains/watch" (`run-3.md:10452`).
- It used the Minetown altar to BUC-test everything before wearing it. "wUNC+0BANDEDMAIL nowWORN1456
  (altar1445 confirmedUNC1446)" and "Bulkaltar1457 ... ALLUNC" (`run-3.md:10388-10395`).
- It sold loot for gold and bought armor and tools. "nSHININGBOOK SOLD1323 150gold", "wBANDEDMAIL
  paid120gold1326", "yMAGICMARKER paid67" (`run-3.md:10436-10439`, `10367`).
- Run 2 bought protection from the Minetown priest: "Firstprotectiondonation3200 at6471 SUCCESS
  AC-1→-3" (`run-2.md:1882`). At XL8 the price is 400 times XL.

### Excalibur timing
- Run 1 got it on the sixth dip at the D5 Oracle, T6349, XL6 (`live-run.md:3333`).
- Run 2: "Twelveattemptstotal acrossD9(8),D5(3),D4(1)", T5904, XL8 (`run-2.md:1995-2002`).
- Run 3 needed 27 dips. The four Oracle fountains dried up after 18 dips ("EXCALIBURATTEMPT18DIPSFAILED",
  "ALLFOURFOUNTAINS NOWDRY", `run-3.md:9719-9733`), and the ninth dip on D10 finally worked
  (`run-3.md:9530-9533`).
- The side effects were water moccasins, a fully rusted sword, new pools and lost gold (`run-3.md:9719-9733`).
  It dipped from beside a marker Elbereth square: "Hero9,26 ON MARKER ELBERETH ... Snakes repeatedly
  fled" (`run-3.md:9540-9545`). It also found that you cannot engrave on the fountain square itself
  ("ERROR Ey onfountain4518: cannotwriteONfountain", `run-3.md:9546`).
- 27 dips at a 1/6 chance each is unusually unlucky (the odds of 26 failures are under 1%), so run 3 was
  an outlier **(inferred)**.

### Shops
- Throwing inside a shop sells the thrown item: "rthrowWEST3803 ... MISSedcub4,25, automatically
  SOLDdagger2gold!" (`run-3.md:9811`).
- It price-identified by dropping items at shops (`run-2.md:2748`). Price-check drops also lost a
  scroll of scare monster, and it recorded the lesson: "Neverbulkdropandrepickscarescroll"
  (`run-2.md:1884`, `run-3.md:9799-9800`).
- It kept no unpaid goods: "No unpaidgoods" (`run-3.md:10371`).

### Dangerous monsters and how they were handled
- Floating eye: never meleed while able to see. It threw daggers and darts ("b2100MISS r2101HIT g2102HIT,
  5darts ... ALLMISS"), then put on a blindfold and meleed: "Putonqblindfold2110, step62,24T2111 thenF2
  2112KILL" (`run-3.md:10256-10258`). A floating eye paralysed the dog (`run-3.md:10520`).
- Gas spore: "Gas spore farlook1161 at59,21, leftalive ... toavoidblastneardog" (`run-3.md:10496`). Run 1
  mistook a gas spore for a floating eye and threw at it from the next square: "explosion hit17 damage to7HP
  ... ALWAYS far-look ambiguous monsters" (`live-run.md:3522-3526`).
- Werejackal: "Mistake1110: assumed d63,24 wasdog, actually WEREJACKAL" (`run-3.md:10493`).
- Spotted jelly: "DO NOTMELEE" (`run-3.md:8335`). Yellow mold was killed with thrown daggers and the corpse
  left alone (`run-3.md:10663-10664`).
- Soldier ants killed a pet pony while the hero rested: "NEWpony killed by soldier ant poisoned sting
  during rest7830..7842" (`run-3.md:8352`).
- Leprechaun: "LEPRECHAUNALIVE stole130gold1838" (`run-3.md:10283`). Run 1 avoided a "huge LEPRECHAUNHALL
  (45leprechauns)" (`live-run.md:3389`).
- Poisonous biters: "doNOTfightpoisonmonstersunprepared" (`run-3.md:10048`), written before it had poison
  resistance.
- Its usual attack was a thrown volley of 3 daggers plus darts, then the long sword, then picking the
  ammunition back up ("allweapons and14darts recovered434", `run-3.md:10693`). Dagger skill reached Skilled
  (`run-3.md:8130`).

### Other habits worth noting
- Pet curse test: "i +1ORCISHHELM ... WORN125 ... isolated pet crossed21,26 at121 withoutreluctance
  (noncursed test, formalBUCunknown)" (`run-3.md:10742-10743`). "dog STEPPED RELUCTANTLY2316
  confirmedCURSED, leftNEVERWORN" (`run-3.md:10184`). In run 1, a pick-axe was "**CURSED** proven by
  kitten stepping reluctantly over it" (`live-run.md:3494-3495`).
- Unidentified rings were never put on (the "NEVERWORN" tags at `run-3.md:8901`, `9284`, `9373`, `9567`).
- It identified wands by engraving and learned this lesson: "Never testunidentifiedwandonpets.
  COMPLETEengravingtextbeforeclassifying" (`run-3.md:10082`). The mistake behind it was zapping an unknown
  wand toward the dog (`run-3.md:10077-10080`).
- Native movement: "Native '_' travel target ... works! It even found unchartedshortcut butavoidedpit;
  valuable forbacktracking" (`live-run.md:3328-3330`). "G<direction> runs and auto-turns corridors ...
  much more efficient than digit batches" (`live-run.md:3528-3530`).
- Kicking locked doors outside towns was routine: "East24,21 wasLOCKED kickedOPEN539" (`run-3.md:10654`),
  and in run 1 "Downstairs hidden behind a locked door, kicked open" (`live-run.md:3558`).
- It searched dead ends in bounded bursts: "DEADEND ten searches523..533 nosecret" (`run-3.md:10654`),
  "DEADEND ten searches169..179 nosecret" (`run-3.md:10758`).

## 4. Mapping to our plan (`docs/pilot-plan.md`)

| Item | Verdict | Why |
|---|---|---|
| 1 Prayer gate | Supports, refines | The gate is fine, and run 1's 837 and 849 turn gaps worked (`live-run.md:3335-3397`). The winner barely needed prayer because it kept food stocked: no prayer until T11568 (`run-3.md:7297`). Prayer is the backup; food supply is the main fix. |
| 2 Complete SAFE_FOOD, tins | Supports | It ate slime mold, rations and tins at Hungry and kept lichen as reserve (`run-3.md:10589`, `10528`, `10500`). Addition: buy food rations in shops when gold allows (`run-3.md:7460`). |
| 3 Messages across More prompts | Supports (indirect) | guard.py counts new trap messages by comparing visible message counts, because HP alone can hide the damage (guard.py `changed()`). Our engine needs the same fresh-message signal. |
| 4 Elbereth ordering and read-back | Strongly supports | Dust Elbereth was misspelled twice and caught by reading it back (`run-3.md:10005`, `10044`). It never attacked from the square and rested in 30-turn search bursts (`run-3.md:10034`). |
| 5 Door kicking rules | Supports, refines | Minetown means no kicks, digging or fountains (`run-3.md:10452`). But it kicked locked doors in the main dungeon routinely (`run-3.md:10654`, `live-run.md:3558`), once to reach the downstairs. The "gold under 500 means never kick" clause would block legitimate progress. Gate kicks on shop or town evidence, not on gold. |
| 6 No shoplifting | Supports, adds | Add "never throw or fire inside a shop" because the item is sold (`run-3.md:9811`). It also sold loot for gold (`run-3.md:10439`), which funds food and door debts. |
| 7 Status conditions | Supports | guard.py's DANGERS list stops all movement on Blind, Conf, Stun, Hallu, Slime, Stone, Ill and more. After a magic trap blinded it, it waited in place until sight returned ("waited953..961 sight returned961", `run-3.md:10531`). |
| 8 Never fight shopkeepers or the Watch | Supports | It farlooked every @, G and h before contact and never attacked peacefuls (`run-3.md:10620-10622`, `10451`). |
| 9 Passive blockers | Supports, refines | Floating eye: throw daggers, or blindfold and melee (`run-3.md:10256-10258`). Eat the corpse for telepathy, as all three runs did (`run-3.md:10255`, `live-run.md:3471`, `run-2.md:2685`). Leave gas spores alone when a pet is near (`run-3.md:10496`). Add "blindfold then melee" as an option when a blindfold is carried. |
| 10 Remembered dark floor | Refines (inferred) | Its fix for dark Mines backtracking was NetHack's own `_` travel command, which "found unchartedshortcut butavoidedpit" (`live-run.md:3328-3330`). Travel paths over the game's own map memory, so it may be a cheaper fix than our own remembered-floor set **(inferred; needs a test on a saved Mines scenario)**. |
| 11 Corpse diet | Supports | It ate fresh kills and refused poisonous, old and were corpses (`run-3.md:10693`, `10021`, `run-2.md:2776`). A poisonous corpse eaten without resistance cost it "13HP and4STR" (`run-3.md:10002`), so keep poisonous corpses on the blacklist until poison resistance is known. |
| 12 Harness diagnostics | Neutral | They kept a hash-linked audit ledger (`scripts/audit.py`), which is for provenance, not the same need. |
| 13 Elbereth respect and emergency ladder | Supports | Werejackal misidentified (`run-3.md:10493`). Their emergency ladder was Elbereth, then rest, then stop; potions were saved for later. |
| 14 Search overhaul | Refines | Budgets need a food cap. Run 1 spent thousands of turns searching D6 walls in 25 to 55 search bursts (`live-run.md:3393-3420`), went Weak, and wrote "Don'tburnmorefoodsearch". Its normal burst was 10 searches per dead end (`run-3.md:10654`). |
| 15 Stuck ladder | Supports | Leave and come back, use trapdoors and holes (a hidden trapdoor took it to D13, `run-3.md:7341`), and dig when a route stays hidden (`live-run.md:3112`). |
| 16 RuleBrain fallbacks | Neutral | No direct evidence. |
| 17 Mines policy | **Contradicts for a dwarf, supports for a human** | The winner entered the Mines at XL3 (T631) and reached Minetown at XL4 without trouble, because gnomes, dwarves and gnome lords are peaceful to a dwarf (`run-3.md:10620-10622`, `10549`). It still refused to go below Minetown underprepared (`run-3.md:10406`). Our pilot does not pick a race (`nh` and `batch.py` pass only `-p Valkyrie`, and `engine.py:327` lets the game choose), so each game is randomly human or dwarf. Item 17 is written for a human. |
| 18 Fight from corridors | Weak support | Only indirect evidence: soldier ants killed a pet during rest (`run-3.md:8352`). |
| 19 Wand lines | Strongly supports | Run 2 died to a wand of death at full HP (`run-2.md:5-12`), and "Avoid lining up with unknown wand users" was a standing rule (`run-3.md:10780`). |
| 20 Throw safety | Supports | The dog crossed the firing line ("Dog crossed firing line1656 swapped1657", `run-3.md:10359`), and an unknown wand zapped toward the dog hit it (`run-3.md:10077-10080`). |
| 21 Descent pace | Refines | The winner ran at roughly depth XL+2 to XL+3 (D10 at XL7, D3 at XL2). XL+1 is more conservative than what won. XL+2 in the main dungeon looks defensible **(inferred; they reviewed every fight, we do not)**. |
| 22 Excalibur | Supports, refines | It worked in all three runs at XL6 to 8, T4532 to T6349. Dips needed: 6, 12 and 27, so the routine must move on to other fountains when one dries up ("ALLFOURFOUNTAINS NOWDRY", `run-3.md:9733`). It must also expect water moccasins, new pools and rust, and dip from next to an Elbereth square, not on the fountain (`run-3.md:9540-9546`). |
| 23 Nymph and leprechaun | Supports | A leprechaun took 130 gold (`run-3.md:10283`). A nymph zapped a digging wand and escaped down the hole (`run-3.md:10372-10374`). |
| 24 Altar BUC testing | Supports, refines | It BUC-tested everything on the Minetown altar (`run-3.md:10388-10395`). The cheaper, earlier test is pet reluctance: drop the item in a corridor square and watch the pet cross it (`run-3.md:10742`, `10184`, `live-run.md:3495`). It never wore untested rings. |
| 25 Safety in the engine | Supports | Their guard is the same idea: hard stops in code, and judgement only after a stop. "A visible-state movement guard cannot guarantee protection from a one-hit kill" (`run-2.md:10`) is the limit. |

### Lessons not in our plan, ranked by likely impact on our failure modes

1. **Play a dwarf: add `-r dwarf` to `nh` and `batch.py`.** All three of their runs were dwarves. In the
   Mines, gnomes, dwarves and gnome lords are peaceful to a dwarf (`run-3.md:10620-10622`). Our data puts
   12 of 44 deaths in the Mines (plan item 17). This change also makes item 8 matter more, because more
   peacefuls are around, and the engine already refuses to attack peacefuls. Dwarves also have
   infravision **(inferred benefit; not discussed in the journals)**. It targets melee deaths and Mines
   stalls. Effort: one flag.
2. **Food as an economy, not just a whitelist.** Pick up every ration, eat at Hungry, keep 2 to 4 rations
   in stock, sell loot and buy food in shops, and let prayer be the backup (`run-3.md:10614`, `7460`,
   `7297`). Buying food is not in the plan. It targets starvation stalls.
3. **A food-aware cap on searching.** Run 1's worst stretch was hundreds of search turns on one level while
   food ran out ("Avoidrepeatinglongsearch!", `live-run.md:3376`). Items 14 and 15 should stop searching
   when carried nutrition is low and take any other way on (stairs, trapdoor, back up) first. It targets
   the combination of starvation and no-way-on stalls.
4. **Use NetHack's travel (`_`) and run (`G`) commands for known targets.** They use the game's own map
   memory and trap knowledge (`live-run.md:3328-3330`, `3525-3527`). This could close the "stairs visible
   but no path" Mines stalls without a new remembered-floor model **(inferred; test before relying on
   it)**. It targets no-way-on stalls.
5. **Never throw inside a shop** (`run-3.md:9811`). This is a one-line guard. It targets shopkeeper
   deaths.
6. **Dig past hidden routes when a digging tool is known.** Run 1 reached Sokoban only by digging
   (`live-run.md:3112`), and trapdoors and holes were used as down routes (`run-3.md:7341`, `7727`). Use
   the `autodig` option when wielding a pick-axe. But never wield a cursed pick; the pet test caught one
   (`live-run.md:3494-3495`). It targets no-way-on stalls.
7. **The pet as curse detector and helper.** Keep the pet with you at stairs (their `wait-pets` helper
   stops when the pet is adjacent), and use pet reluctance before wearing armor. This is small but it
   enables earlier AC gains. It targets melee deaths.
8. **Blindfold for floating eyes and a lizard for stoning.** They carried both
   (`run-3.md:10256-10258`, `9434`). Small, and it targets blocker stalls.
9. **Engrave-ID wands and never point unknown wands at the pet** (`run-3.md:10082`). Knowing that a wand
   is sleep or striking gives the pilot a ranged answer to blockers and wand users. Medium effort; it
   targets wand deaths and blockers.
10. **Minetown protection purchase** (400 times XL gold; `run-2.md:1882`). This is only reachable once the
    pilot keeps gold, so it is low priority.

## 5. nethackrc options worth considering

Their file (`config/nethackrc`) is mostly display options for curses and streaming. Our pilot reads
state through aipipe, so most of it does not apply. Our current options are
`autopickup,pickup_types:$,time,showexp,dark_room,!legacy,!news,!autoquiver` (`pilot/batch.py:35`, `nh`).

| Option | Theirs | Consider? |
|---|---|---|
| `!implicit_uncursed` | set | **Yes.** Inventory names then always say "uncursed". Our item 24 BUC tracking, and any "wear only non-cursed" rule, can parse BUC from item names without the implicit case. |
| `autodig` | set | **Yes**, once a pick-axe routine exists (lesson 6). Moving into rock while wielding a pick digs. |
| `dark_room` | set | Already set. It must stay on (our pilot.md lesson). |
| `lit_corridor` | set | Maybe. It is a display distinction only; the aipipe map may not need it **(inferred)**. |
| `!autopickup` | set | No. Our `autopickup` with `pickup_types:$` is right for gold. Note that `pickup_thrown` defaults to on in 3.6 and works whenever autopickup is on, so walking over thrown daggers picks them up again. That helps item 9's retrieve step **(inferred from 3.6 defaults; confirm in `options.c`)**. |
| `number_pad:1` | set | No. It changes our key mapping and has no gameplay benefit. |
| `boulder:0`, `menucolors`, `hilite_pet`, `statushilites`, `perm_invent`, `msghistory:60`, `windowtype:curses` | set | No. They are display only, and aipipe already carries pet and peaceful flags and messages. |
| `fruit:slime mold` | set | Irrelevant. |

Not in their file but related: race selection (`-r dwarf`, see lesson 1) is a command-line choice, not an
nethackrc option, and it is the highest-value "configuration" change the evidence points to.
