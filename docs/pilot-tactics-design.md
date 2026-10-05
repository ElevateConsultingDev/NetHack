# Design: the jev-doom workflow applied to the NetHack pilot

Status: proposal, 2026-10-04. Owner: Dave. Branch: `ai-player`.
Source studied: `~/git/github/games/jev-doom` (olivier-motium/jev-doom, commit 13589d2):
`README.md`, `index.html`, `harness.py`, `tactics.py`.
Companion: `docs/pilot-router-design.md` (goals per level and the router). Section 9 says how the
two fit together.

## 1. Summary

jev-doom is not "Jev plays Doom". It is a measurement harness built around one loop:

1. Code observes the game and builds a short **menu of complete, feasible tactics**.
2. Every tactic carries a **prediction**: a specific, checkable claim about what will be true when
   it finishes.
3. Jev ranks the same menu under several **rubrics** in one request (progress, exposure, evidence)
   and makes a final pick.
4. A deterministic **motor** carries the tactic out for a bounded **lease**.
5. Code **measures** the prediction against the next observation and records met, not met or
   unknown.
6. The last few **outcomes go back into the state**, so the next decision sees what just failed.
7. A **fixed selector** can replace Jev on the same menu, as a built-in control.
8. Between runs, an **investigation** step names competing explanations for a failure and picks the
   local test that tells them apart.

Our pilot has pieces 1, 4 and 7 already. It lacks 2, 5, 6 and 8, and those are the parts that turn
play into evidence. This document designs them for NetHack. The largest single gain expected is not
from Jev choosing better: it is from the pilot finally knowing, with counts, which of its own
tactics work against what.

## 2. What jev-doom does

### 2.1 The page

The dashboard (`index.html`) is the workflow drawn as panels. In reading order:

| Panel | What it shows |
|---|---|
| Connect, check provider, start | Nothing is billed until the operator checks a provider. Runs default to 90 seconds. |
| Controller selector | "Jev, separate channels", "Jev, coherent tactics", "Fixed tactics, timing calls". |
| What Jev is deciding | The request in flight and the committed objective. |
| Standing orders | Free text, applied to the next request. Example: "Do not fire, simply dodge". |
| Raw choice probabilities | Every option with the probability Jev gave it. |
| Tactic and measured outcome | "Each chosen tactic carries a prediction. The next observation measures what happened." |
| Feasible menu and omitted candidates | The options offered, and the ones withheld with the reason for each. |
| Between-run investigation | "Jev chooses a test that can distinguish competing explanations. The unpaid test supplies the evidence." |
| Map, Composition, Inspect calls, Situation, Real progress | Tabs. Composition is a graph: orange nodes are Jev choices, the rest are deterministic. |
| Latency and cost | Per-call latency, reported cost, and a spend cap that persists across restarts. |

The footer is careful about claims: one map, one seed, "a terminal episode alone is not proof of
level completion".

### 2.2 The tactic menu (`tactics.py`, `build_menu`)

Each option is a full plan, not a keypress:

```
id            clear_Zombieman_3
label         Clear the nearest visible threat before crossing
kind          combat | retreat | health | armor | weapon | ammo | advance | exit | guard | observe
subject       the thing it is about, with a position
controls      face, move, dodge, trigger, weapon, use (what the motor will do, all at once)
route_units   path length from the planner
exposed_to    visible enemies with line of sight to the route
feasibility   what was checked and what was not ("dynamic danger is estimated, not guaranteed safe")
prediction    kind, target, expected amount, plain-text statement
priority      a number, lower is more urgent (used by the fixed selector and the cap)
expiry        how long the tactic may run before it must be re-decided
completion    what ends it
```

Rules the builder follows:

- **Feasible only.** No path to the subject, or a route that crosses a visible hostile, and the
  option is not offered.
- **Omitted with a reason.** Every withheld candidate is listed with why. The model's state still
  says it exists.
- **At most seven**, sorted by priority then route length. The rest are omitted as "menu limit".
- **One per kind.** The best health item, the best armor, the nearest threat, one frontier, and so
  on. Not every item on the map.
- **Labels carry the numbers that matter**, in the option text: "+25 health to at most 100, now
  40/100", "route 320 units, about 1.1 s of running".
- **An observe option appears only when needed**: nothing feasible, damage with no visible source,
  or the last prediction was contradicted. It is withheld after two empty observations in a row.

### 2.3 The questions (`tactic_questions`)

One request, four Choice questions over the same criteria, plus independent side questions:

| Question | Asks |
|---|---|
| `progress` | Which tactic offers the most useful progress toward the exit alive? |
| `exposure` | Which tactic best avoids immediate lethal exposure? |
| `evidence` | Which tactic is best supported by fresh observations and measured previous outcomes? |
| `tactic` | Choose one. Avoid observed lethal exposure first; otherwise make progress on reliable evidence. |
| `dodge` (only when a projectile is closing) | An independent choice the motor layers over whichever tactic wins. |

Each instruction says the questions cannot see each other. The final `tactic` instruction also
carries a few hard game facts, added one at a time after probes ("hitscan cannot be dodged", "armor
absorbs a third of every hit"), each tagged in a code comment with the version and the probe file
that justified it.

The harness acts on `tactic`. The three rubric picks are stored with the decision so a later reader
can see whether the final pick agreed with the survival pick.

### 2.4 Lease, measurement, feedback (`measure`, `end_tactic`)

- The chosen tactic runs until its prediction is met, its target becomes invalid, its route is
  newly blocked, or its window (about one game second) ends.
- If the same option is chosen again inside its window, it continues against the original
  before-state. One prediction, not a new one per call.
- When it ends, `measure` compares before and after:

| Prediction kind | Met when |
|---|---|
| `route_progress` | Remaining route shrank by the expected amount, or the player arrived |
| `target_gone` | The faced enemy left view (explicitly "not a confirmed kill") |
| `separation` | Distance to the locked threat grew by the expected amount |
| `door`, `door_through`, `lift`, `exit` | The door is passable, the line was crossed, the floor moved, the level ended |
| `observation` | A new entity or route candidate appeared |
| `switch` | Never: recorded as unknown, because no effect is observable |

- Four statuses: `met`, `not_met`, `unknown` (evidence unavailable), `window_ended_early`.
- The last five outcomes are placed in the next state as `recent_tactic_outcomes`.
- A contradicted route or door prediction makes the observe option available.

### 2.5 Honesty devices

- **Evaluator fields are withheld.** Kill, hit and damage counters are used for scoring and never
  shown to the model or the option builder.
- **Modes are labelled.** "Observable" uses only what the player has seen; "assisted" uses the full
  map and is tagged in run metadata so the two are never compared as equals.
- **A fixed controller.** `fixed_select` picks the lowest-priority-number option with no model. In
  that mode the paid call is still made so timing matches.
- **An assumptions block** in every state says what is exact, what is remembered and what is unknown.

### 2.6 Between-run investigation (`investigation_questions`)

After a run, a **failure capsule** is assembled: the result, the last five outcomes, a list of
competing hypotheses, and a list of local tests with which hypotheses each one separates and what
its possible outcomes are. Defaults:

- Hypotheses: the facts went stale before execution; the route was blocked; the facts and route were
  fine and the tactic was wrong.
- Tests: compare the request snapshot with what happened next; reconstruct the route; replay the
  motor in an isolated fixture.

Jev picks the test that best separates the hypotheses. A person or script runs it, and the findings
are saved against the investigation. The rule stated in the prompt: "A death or success alone is not
causal proof."

## 3. What transfers and what does not

| jev-doom | NetHack pilot | Note |
|---|---|---|
| Real time, 35 Hz, world runs during calls | Turn based, world waits | No stale-evidence problem. Leases become turn budgets. |
| Controls: face, move, dodge, trigger, weapon, use | Routines: fight, throw, elbereth, go_to, explore, loot, pray, use | We already have the motor layer (`ROUTINES` in `pilot/engine.py`). |
| Dodge side question | No equivalent | Dropped. The side question slot is used for "will I die". |
| Geometry planner | `bfs` over the remembered map | Exists. |
| Hard game facts in the prompt | The spoiler table (`pilot/spoilers.py`) | Ours is larger and comes from the game's source. |
| One map, one seed, 90 seconds | 128 fixed dungeons, paired runs, held-out set | Ours measures better. Theirs explains each decision better. |
| Checkpoint and restore | Deterministic replay by seed | Ours is stronger for investigations: any game can be replayed to the turn. |
| Evaluator counters withheld | Nothing withheld today | We should name what is scoring-only (deepest level, death cause). |

One caution carried over from our own results and from statico/jev-nethack, which copied this
structure for NetHack: letting Jev make the final pick over a rule-built menu has equalled the rules
three times and never beaten them. So this design adopts the workflow for what it measures and
keeps the fixed selector as the default controller until a paired run says otherwise.

## 4. The design

### 4.1 The loop

```
observe (snapshot, remembered map, checks, spoiler facts)
   |
build menu: up to seven complete tactics, each with a prediction;
            omitted candidates listed with reasons
   |
select: fixed selector (default)  or  Jev rubrics (one request)
   |
hard safety rules check the pick; a refusal falls back to the fixed selector
   |
motor: the existing routine runs for the tactic's turn budget
   |
measure: prediction met / not met / unknown / ended early
   |
record: outcome into the game's log, the next state, and the tactic ledger
```

The loop runs at **decision points**, not every keypress: when a tactic ends, when a hostile comes
into view, when HP drops, when hunger changes, on arriving on a level. Between decision points the
motor keeps running the committed tactic.

### 4.2 State

One JSON object per decision, built for that decision only. Following the Jev documentation and the
`fight_state` builder already in `pilot/jevb.py`: numbers become words, spoiler facts are stated
directly, nothing unrelated is included.

Sections:

- `me`: health in words, rounds I can survive at the current rate, armor in words, hunger, what I
  am wielding.
- `enemies`: per visible hostile, its name, distance in words, whether it is faster than me, whether
  it respects Elbereth, its dangers.
- `level`: explored or not, stairs known or not, how far behind the level's readiness goal I am
  (from the goals table in the companion design).
- `recent_outcomes`: the last five tactic results, each as "tactic, prediction, status".
- `track_record`: for each tactic on the menu, its ledger line in words (section 4.6).
- `assumptions`: what is exact (my status, adjacent monsters), what is remembered (map, last seen
  monsters), what is unknown (monster health, unidentified items).
- `standing_order`: free text from the operator.

**Scoring-only fields**, never placed in state or used by the menu builder: deepest level reached
this game, the eventual cause of death, the game's seed.

### 4.3 The tactic menu

Schema, one per option (a Python dict, as in jev-doom):

```
id           flee_up
label        Climb the stairs up, three steps away; the soldier ant follows and is faster
kind         fight | escape | supply | explore | descend | wait
subject      {"what": "staircase up", "x": 41, "y": 9}
routine      go_to / "<"          (the existing routine and its arguments)
route_steps  3
exposed_to   ["soldier ant"]
feasibility  Path exists on remembered floor; the ant gets about three rounds on the way
prediction   {"kind": "left_level", "within_turns": 6, "text": "I am on the level above"}
priority     2
budget       8 turns
ends_when    prediction met, path blocked, HP critical, or the budget runs out
```

Catalog, by situation. Each is offered only when its feasibility test passes.

| Kind | Tactic | Feasible when | Prediction |
|---|---|---|---|
| fight | Melee the adjacent monster | Adjacent, not on the never-melee list, armed | `target_dead` within N turns, and HP stays above a third |
| fight | Throw at a monster in line | Throwable in pack, clear line with no peaceful | `target_hit` or `target_dead` within 3 turns |
| fight | Fight from the corridor mouth | Two or more hostiles, chokepoint within 8 steps | `adjacent_count` is at most 1 after arriving |
| escape | Engrave Elbereth and rest | Every adjacent monster respects it, not failed here before | `no_damage` for the next 5 turns |
| escape | Stairs up or down | Stairs known and reachable | `left_level` within route steps plus 2 |
| escape | Pray | Prayer gate open and real trouble present | `trouble_fixed` next turn |
| escape | Step away from a slower monster | Monster slower than me, open square behind | `separation` grew by 2 within 3 turns |
| supply | Eat safe food or a fresh safe corpse | Hungry or worse, food available | `hunger_better` within 10 turns |
| supply | Walk to and pick up a wanted item | In view, not shop stock, slot empty for armor | `item_in_pack` within route steps plus 2 |
| supply | Wear, wield | Item in pack for an empty slot or empty hand | `ac_better` or `armed` within 5 turns |
| explore | Explore toward the nearest frontier | Frontier reachable | `map_grew` within 20 turns |
| explore | Probe dark squares, search a wall spot | Level explored, stairs unknown | `map_grew` within the search budget |
| descend | Take the stairs down | Stairs known, level explored or starving | `left_level` |
| wait | Rest to recover | No mobile hostile in view, not starving | `hp_better` by a set amount within 20 turns |

Builder rules, taken from jev-doom:

- At most seven options. One per kind where several candidates exist (the best item, the nearest
  frontier).
- Every withheld candidate goes in an `omitted` list with its reason: "no path", "route passes a
  hostile", "monster ignores Elbereth", "prayer gate closed", "menu limit".
- The label carries the numbers that decide it, already in words.
- Priority numbers reproduce today's standing-order ordering, so the fixed selector on this menu
  plays the same game as the current rules pilot. That equivalence is the first acceptance test.

### 4.4 Predictions and measurement

Prediction kinds for NetHack and how each is checked from the next snapshots:

| Kind | Met when | Unknown when |
|---|---|---|
| `target_dead` | "You kill" or "You destroy" for the target inside the budget | The target left view |
| `target_hit` | A hit message for the target | Blind or the target is unseen |
| `no_damage` | HP did not fall during the window | Never |
| `separation` | Distance to the named monster grew by the stated amount | The monster left view |
| `adjacent_count` | Count of adjacent hostiles is at or below the stated number | Never |
| `left_level` | The level number changed in the stated direction | Never |
| `trouble_fixed` | The named trouble is gone from the status line | Never |
| `hunger_better`, `hp_better`, `ac_better`, `armed` | The status changed as stated | Never |
| `item_in_pack` | The inventory gained the item | Never |
| `map_grew` | Explored squares increased, or new stairs or doors appeared | Never |

Statuses are jev-doom's four: `met`, `not_met`, `unknown`, `ended_early` (replaced before its budget
with no decisive evidence). Every outcome also records HP change, turns used and what ended it.

Turn-based play makes measurement exact where jev-doom has to hedge: there is no stale snapshot and
the message log names what died.

### 4.5 Selection

**Fixed selector (default).** Lowest priority number, then shortest route. No call. This is the
pilot that counts.

**Jev rubrics (optional controller).** One request over the menu:

| Question | Type | Asks |
|---|---|---|
| `progress` | Choice | Which tactic most helps me get deeper alive? |
| `exposure` | Choice | Ignoring progress, which tactic leaves me most likely to be alive in 20 turns? |
| `evidence` | Choice | Which tactic is best supported by `recent_outcomes` and `track_record`? |
| `tactic` | Choice | Choose one: avoid observed lethal exposure first, otherwise make progress on reliable evidence. |
| `will_die` | Noul | I will die in this fight if I keep attacking in melee. (kept from `jevb.py`, where it is measured) |

Composition in code, as a named function with thresholds:

```
will_die >= 0.6  ->  take the exposure pick
otherwise        ->  take the tactic pick
pick refused by a safety rule, or the call failed  ->  fixed selector
```

The `will_die` override is the one piece of Jev judgment we have measured as informative (54% dead
within 20 turns at 0.8 and above, against 5% below 0.2). statico uses the same override at the same
threshold with their own danger question. All rubric picks are stored with the decision whether or
not they were used, so agreement between them can be studied later.

Jev's first-option bias is documented, so the menu order sent to Jev is shuffled per call and the
priority number is not shown.

### 4.6 Outcome memory

Two levels.

**Within a game.** The last five outcomes go into the next state, as jev-doom does. A tactic whose
prediction failed twice running at the same place is withheld for a cooldown and listed in `omitted`
with that reason. This replaces several case-by-case loop guards in the engine with one rule.

**Across games: the tactic ledger.** A table regenerated from recorded runs:

```
tactic      against                 tried   met   not met   unknown
elbereth    fast insects (a)          212    131      74        7
elbereth    canines (d)               160    118      40        2
melee       soldier ant                88     41      47        0
flee_up     any, 4 or more steps       31      6      25        0
```

Uses:

1. **In the menu.** Each option's `track_record` line in words ("worked about six times in ten
   against this kind of monster"). This gives the `evidence` rubric something real to judge.
2. **In the fixed selector.** Priorities can be set from measured success instead of from my
   reading of individual deaths. This is where the rules pilot itself is expected to improve.
3. **In analysis.** It answers the open question from the Jev judge runs directly: Elbereth looked
   better at 20 turns and did not add depth. The ledger records what happened after each one.

The ledger is the post-analysis product this project has been missing. It is to tactics what the
goals table in the companion design is to levels.

### 4.7 Controllers and controls

Three controllers on the same menu, selected by `--brain`:

| Controller | Selection | Purpose |
|---|---|---|
| `tactics-fixed` | Fixed selector | The pilot that counts, and the control |
| `tactics-jev` | Jev rubrics with the composition above | The experiment |
| `rules` | Today's engine | Kept until `tactics-fixed` matches it game for game |

Standing controls for any model arm: the fixed selector on identical seeds, and for a new question,
its calibration table before it is allowed to steer.

### 4.8 Between-run investigation

After a batch, for each death or stall (or the ten worst by lost depth), a failure capsule is built
from the game's own record:

- the last five tactic outcomes and their predictions,
- the state and menu at the last three decisions, including what was omitted and why,
- competing hypotheses, chosen from a fixed list:
  - **facts wrong**: the state misdescribed the situation (a monster's nature, a stale map),
  - **menu wrong**: the tactic that would have worked was omitted or does not exist,
  - **selection wrong**: the right tactic was on the menu and another was chosen,
  - **motor wrong**: the right tactic was chosen and the routine did not carry it out,
  - **no good move**: every available tactic was already losing, so the mistake was earlier,
- local tests that separate them, all free because replay is deterministic:
  - replay to the decision and force each menu option in turn (separates selection from no good move),
  - replay with the omitted candidate forced on (separates menu from selection),
  - compare the state's claims with the game's own data for that turn (facts),
  - compare the routine's keys with the tactic's intent (motor).

The first test is the powerful one and jev-doom cannot do it: **forcing each option from the same
turn and seeing which survive is a direct measurement of whether a good move existed.** If none
survives, the death is charged to an earlier decision (descending unready, not resting), which is
exactly the question the goals table needs answered.

Jev's role here is the one it has already done well for us (`pilot/jevphase.py`): classify the
failure and pick the most discriminating test. The forced replays themselves need no model and can
run for every death in a batch.

### 4.9 The page

Our replay page (`pilot/replay_template.html`) and dashboard gain jev-doom's panels:

| Panel | Content |
|---|---|
| Menu and omitted | For the selected frame: each option with its label, prediction and track record; each omitted candidate with its reason |
| Rubrics | The picks for progress, exposure, evidence and tactic, with probabilities, and which one was acted on |
| Tactic and measured outcome | The prediction, the status, HP change and turns used |
| Composition | The decision graph for that turn: which nodes were code, which were Jev |
| Investigation | For a finished game: the capsule, the forced-replay results, the classification |
| Ledger | The batch's tactic table, sortable |
| Cost | Calls, latency, estimated spend for the run |

### 4.10 Spend

A cap in the style of jev-doom: a persistent ledger file, a per-run and cumulative limit, and the
run stops making calls and falls back to the fixed selector when the cap is reached. Calls are
counted today (`brain_calls`, `brain_seconds`); cost is not.

## 5. Mapping to what exists

| Piece | Exists | To build |
|---|---|---|
| Observation, remembered map, checks | `pilot/engine.py` (`View`, `checks`, `Memory`) | Nothing |
| Motors | `ROUTINES` in `pilot/engine.py` | A turn budget and an end reason per run of a routine |
| Spoiler facts | `pilot/spoilers.py` | Nothing |
| Fight state in words | `pilot/jevb.py` (`fight_state`) | Generalize to the state in 4.2 |
| Menu of tactics with predictions | Standing orders decide inline, no menu | `pilot/tactics.py`: `build_menu`, `fixed_select`, `measure` |
| Jev call | `pilot/jev.py` (`ask`) | Rubric questions; shuffled order |
| Safety rules | In the engine's routines and standing orders | A single `allowed(tactic)` check used after any selection |
| Outcome record | Counters in `memory.stats` | Outcome list per game; `pilot/ledger.py` to aggregate |
| Deterministic replay | `--replay`, seeds | Forced-option replay from a given decision |
| Failure classification by Jev | `pilot/jevphase.py` | Capsule with hypotheses and tests; forced-replay results |
| Replay page and dashboard | `pilot/frames.py`, `pilot/replay_template.html`, `pilot/dashboard.py` | The panels in 4.9 |
| Spend cap | None | Ledger file and cap |

`pilot/engine.py` is over 1,600 lines. The menu builder is the natural place to move the standing
orders to, which shrinks the engine instead of growing it.

## 6. Measurement

The standing method applies unchanged: the 128 fixed games, paired against the current baseline,
tuned on seed 1000 and confirmed on seed 5000; keep at +0.25 average deepest level with experience
level not falling by more than 0.25.

Acceptance tests specific to this design:

| Test | Passes when |
|---|---|
| Menu equivalence | `tactics-fixed` reproduces the `rules` runs game for game, or every difference is explained |
| Prediction sanity | For each prediction kind, a hand-checked sample of outcomes is labelled correctly |
| Ledger stability | Ledger rates from seed 1000 and seed 5000 agree within their error for the common rows |
| Forced replay | Replaying a decision with the option that was actually taken reproduces the original game |
| Jev arm | Paired result against `tactics-fixed` on both seed sets, with rubric agreement and calibration tables |

## 7. Build order

| Phase | Build | Needs Dave to run | Done when |
|---|---|---|---|
| 1 | `pilot/tactics.py`: menu, predictions, fixed selector, measurement, for the fight and escape tactics only; outcomes written to each game's record | No | Menu equivalence holds for fights; prediction sanity passes |
| 2 | `pilot/ledger.py` and the ledger panel | No | Ledger printed for the 128 games; stability test passes |
| 3 | Forced-option replay and the investigation capsule, run for every melee death in a batch | No | A table: deaths where some option survived 20 turns, and deaths where none did |
| 4 | Use the ledger to reorder the fixed selector's priorities, one change per iteration | No | Kept or dropped under the keep rule |
| 5 | Extend the menu to supply, explore and descend; retire the matching standing orders | No | Menu equivalence for whole games |
| 6 | `tactics-jev`: rubric questions, the `will_die` override, shuffled order, spend cap | Yes | Paired result on both sets |
| 7 | Page panels (4.9) | No | Panels render for a recorded game |

Phases 1 to 5 need no API calls. Phase 3 is the one that answers the question both Jev experiments
left open: when the pilot is losing, is there a move that saves it, or was the mistake made earlier?

## 8. Risks and open questions

- **Jev's final pick may again equal the fixed selector.** Three prior results point that way. The
  design does not depend on it: phases 1 to 5 improve the rules pilot's evidence without it.
- **Menu equivalence may be hard.** The standing orders have accumulated ordering subtleties over 55
  iterations. Mitigation: move one situation at a time, fights first, and keep the old path until
  each matches.
- **Predictions can be gamed by their own definition.** "No damage for five turns" is met by a
  monster that wandered off. Mitigation: record what ended the window, and read samples by hand.
- **The ledger's categories are a choice.** Grouping by monster letter may hide what matters (speed,
  number of attacks). Start with the spoiler table's fields and let the stability test judge.
- **Forced replay changes the random stream.** A different action draws different random numbers, so
  a forced branch is a fair sample of what could have happened, not a replay of fate. Run each
  forced option several times with different continuation seeds and report a rate.
- **Cost of the extra calls.** Decision points are fewer than turns, but more than the ten asks per
  game of the judge mode. The spend cap bounds it.

## 9. How this fits the companion design

`docs/pilot-router-design.md` proposes goals per dungeon level and a Jev router choosing among the
rules, a Jev question set and a Claude consult. The two designs are layers of one system:

- **Goals** (companion, section 4) say whether the pilot is ready for the next level. Here they set
  the feasibility and priority of the `descend` tactic and supply the "how far behind" line in state.
- **The tactic loop** (this document) replaces the companion's "Jev judge" expert and the routing
  table for fights: the menu, the fixed selector and the `will_die` override do that job with
  measurement attached.
- **The Claude consult** (companion, section 6.3) becomes a menu extender. When every option on the
  menu has a poor track record and `will_die` is high, Claude is asked to propose one more tactic
  from the full inventory. Its proposal is added to the menu with its own prediction, checked by the
  same safety rules and measured like any other. That gives the consult a testable contract, which
  the companion design lacked.
- **Forced replay** (4.8) feeds the goals table: a death with no surviving option is evidence about
  readiness, not about tactics.

Recommended order across both documents: this document's phases 1 to 3, then the companion's goals
table, then the rest.

## 10. References

- `~/git/github/games/jev-doom`: `tactics.py` (`build_menu`, `tactic_questions`, `fixed_select`,
  `measure`, `investigation_questions`), `harness.py` (`state_for_model`, `questions`,
  `request_investigation`, `accept_reply`), `index.html`, `README.md`.
- statico/jev-nethack (read 2026-10-04): the same structure applied to NetHack 5.0, its `danger`
  and `safest` questions, and its no-model control.
- TypeSafe documentation: docs.typesafe.ai (state, Choice, Noul, building guide, Jev 1.13 limitations).
- This repo: `docs/pilot-router-design.md`, `docs/pilot-loop.md`, `pilot/jevb.py`, `pilot/jev.py`,
  `pilot/jevphase.py`, `pilot/engine.py`, `pilot/spoilers.py`, `pilot/frames.py`.
