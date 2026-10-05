# Design: goals, a Jev router, and three experts

Status: proposal, 2026-10-04. Nothing in sections 4 to 6 is built except where marked "exists".
Owner: Dave. Branch: `ai-player`.

## 1. Summary

The pilot today is a rule engine that explores each level and takes the stairs down. It has no idea
whether it is ready for the next level, and when a fight goes wrong it has few answers. Two things
are proposed:

1. **Goals per dungeon level, derived from our own games.** For each level, what state the pilot
   should be in on arrival (experience level first, by the evidence below), and what it should do
   when it is not.
2. **Jev as the top-level decider.** At each decision point Jev answers a few narrow yes/no
   questions. Code reads the answers and routes the turn to one of three experts: the rule engine,
   a focused Jev question set, or a Claude consult for the rare moments the first two have no
   answer for.

The rule engine stays the pilot that counts. Every new piece must beat it on the same fixed
dungeons or it does not ship.

## 2. What we know (the evidence this design rests on)

All numbers are from the 128 fixed games (seeds 1000 and 5000, 64 each) unless stated.

**The rules pilot.** Average deepest level 6.67 (runs 20261004-192558 and 20261004-192645). Most
games end in a melee death.

**Jev picking the move ("Job A").** Tested in three rounds on 2026-10-02. It reached parity with the
rules on four dungeons and never passed them. Its probabilities went flat on the hard calls.

**Jev judging a fight ("Job B", `pilot/jevb.py`, exists).** The rules play; in a fight that is costing
HP, Jev answers "will I die", "will Elbereth work", "will I reach the stairs". Eight runs, four
settings. Depth is level with the rules on every setting (between -0.22 and +0.27 levels, all inside
the noise).

**Jev's warning is real.** Its "I will die" answer against whether the pilot was dead within 20
turns, first two runs combined:

| "Will die" probability | Asks | Dead within 20 turns |
|---|---|---|
| 0.0 to 0.2 | 953 | 5% |
| 0.2 to 0.4 | 611 | 9% |
| 0.4 to 0.6 | 218 | 14% |
| 0.6 to 0.8 | 228 | 21% |
| 0.8 to 1.0 | 148 | 54% |

The number is not a calibrated death rate (0.7 means about one in five), but the ordering holds on
both seed sets.

**The escapes are the weak part.** With "will die" at 0.6 or higher: after writing Elbereth the pilot
was dead within 20 turns in 17% to 22% of cases; when no escape rated as likely and it fought on,
44% to 61%. Stairs and corridor retreats were rare and mostly failed. Surviving the next 20 turns
more often did not turn into depth.

**An LLM at escalations.** Haiku answering the engine's rule-fired escalations equalled the rules
(-0.03 levels, 2026-09-26). Those escalations fired on blunt triggers such as HP under a third.

**An outside check.** statico/jev-nethack (Jev picks every move, NetHack 5.0) ran a no-model control
that always takes the first option. It reached the same deepest level as their best Jev game. Their
danger question also sits at 0.6 to 0.87 before deaths. Same finding, reached independently: the
option list does the work, and the model can see danger but not escape it.

**First cut of the level data (new, section 4).** Experience level relative to dungeon level predicts
dying on a level. Armor class at arrival, in this cut, does not.

## 3. Shape of the design

```
            every command prompt
                     |
            hard safety rules (engine)        never delegated
                     |
          is this a decision point?  -- no --> rule engine
                     | yes
              Jev router (Nouls)
          /          |            \
   rule engine   Jev judge     Claude consult
   (default)     (known        (losing, no escape
                 escapes)       rated likely)
                     |
              engine routines carry out the choice
```

Above the per-turn loop sits a slower layer: **goals**. Goals decide what the default activity is
aiming for (descend, or get ready first). The router decides who handles the moment.

Three principles, taken from TypeSafe's documentation and from our own results:

- Code owns control flow, arithmetic and safety. Models supply judgment only.
- Jev gets narrow questions over a small state written in words, with numbers already bucketed.
- A slower model is called only where it can add an option the rules do not have.

## 4. Goals per dungeon level

### 4.1 What a goal is

A goal is a readiness test for a dungeon level plus an activity for when the test fails:

```
level 7:  ready when  experience_level >= 5
          if not ready:  <activity>   (see 4.4)
          give up waiting when:  hungry with no food, or N turns without progress
```

Goals are data, not code: a table in `pilot/goals.py` that the analysis script regenerates.

### 4.2 Where goals come from

From the recorded frames. Every game since 2026-10-03 stores turn, level, HP, experience level and
armor class on every turn (`replay-<game>.html`). For each level a pilot arrived on, we know its
state on arrival and whether it died there. Comparing the pilots that survived a level with the ones
that died on it gives the test.

### 4.3 First cut (rules runs 20261004-192558 and 20261004-192645, 838 level arrivals)

Chance of dying on a level, by level:

| Level | Arrivals | Died there | Median XL on arrival |
|---|---|---|---|
| 1 to 4 | 491 | 12 (2%) | 1 to 3 |
| 5 | 104 | 14 (13%) | 3 |
| 6 | 87 | 20 (23%) | 4 |
| 7 | 63 | 21 (33%) | 5 |
| 8 | 45 | 17 (38%) | 5 |
| 9 | 28 | 15 (54%) | 6 |
| 10 | 13 | 9 (69%) | 6 |

On levels 5 and deeper, by how far experience level trails the dungeon level:

| On arrival | Died on that level |
|---|---|
| XL at or above the level number | 5 of 22 (23%) |
| XL one below | 14 of 70 (20%) |
| XL two below | 34 of 137 (25%) |
| XL three or more below | 47 of 118 (40%) |

On levels 5 and deeper, by armor class on arrival:

| On arrival | Died on that level |
|---|---|
| AC 3 or better | 46 of 154 (30%) |
| AC 4 to 5 | 29 of 114 (25%) |
| AC 6 or worse | 25 of 79 (32%) |

What this says:

- The pilot falls behind. By level 6 the typical pilot is two levels of experience short, by level
  9 three short, and the death rate per level climbs from 13% to over 50%.
- Being three or more behind is the clear risk step (40% against 20% to 25%).
- Armor class does not separate survivors from deaths in this cut. That contradicts the armor-first
  recommendation made earlier on 2026-10-04, which was based on what the dead pilots were wearing
  without comparing them to the survivors. Armor may still matter (better-armored pilots may simply
  go deeper and meet harder monsters), but this data does not show it, so the first goal is about
  experience level.

Limits of this cut: one snapshot of the engine, 128 games, deaths only (stalls are not counted as
failing a level), and no control for what the level contained. It is a starting table, not a law.

### 4.4 The hard part: what to do when not ready

Holding at the top of the stairs earns nothing. The level is already explored, new monsters arrive
about once every 70 turns, and food runs down. Iteration 31 showed that reordering the default
activities costs over a level of depth. So the "not ready" activity must be something that pays.
Candidates, to be tested one at a time:

| Candidate | Why it might pay | Risk |
|---|---|---|
| Explore every level fully before descending, including levels reached by falling | Experience and items the pilot now skips | Small; mostly true already |
| Fight from the stairs on arrival, and leave by them when losing | Turns the stairs into an escape that is zero steps away | Followers come along |
| Dwarves: go down the Gnomish Mines to Minetown | Peaceful Mines, a temple, shops; statico's plan does this first | Non-dwarves die there (measured) |
| Sokoban | Safe experience and a guaranteed prize | Large build; statico needed a solver |
| Hold and wait | None found | Starvation; measured as harmful |

The design does not assume any of these works. Each is one iteration under the usual keep-or-drop
rule. If none pays, the goal table still earns its place as the router's sense of "behind or on
track" (section 5.2).

### 4.5 Keeping goals current

`python3 -m pilot.goals <run> [<run> ...]` (to build) reads the runs' replay data, prints the tables
above, and rewrites the goal table. It runs after any kept engine change, because a stronger pilot
shifts the thresholds. The table and the runs it came from are committed together.

## 5. The Jev router

### 5.1 When it is asked

Not every turn. Decision points only:

| Decision point | Trigger (computed in code) |
|---|---|
| Fight going badly | Hostile adjacent, HP falling, and HP under two thirds or four turns from zero at the current rate (exists in `jevb.py`) |
| About to descend | Standing on the stairs down with the level explored |
| Stuck | Level explored, no stairs down known, search not finished |
| Starving | Weak or worse with no safe food |

Outside these, the rule engine plays and no call is made. In the eight judge runs this meant about
ten asks per game at 0.125 seconds each.

### 5.2 What it is sent

A small JSON object for that decision point only. Numbers become words; spoiler facts are stated
directly; nothing unrelated to the decision is included. The fight state exists (`fight_state` in
`jevb.py`). The descend state would add the goal table's verdict in words:

```json
{
  "me": {"health": "most of it left", "experience_vs_this_depth": "three levels behind",
         "armor": "poor", "food": "two meals"},
  "next_level": {"number": 8, "pilots_like_me_died_there": "about four in ten"},
  "this_level": {"explored": true, "unfinished": "none"}
}
```

### 5.3 What it is asked

Several Nouls in one request. They run in parallel and cannot see each other. Each is one judgment
with a clear yes and no.

| Decision point | Questions |
|---|---|
| Fight | I will die if I keep fighting. Elbereth will stop these enemies. I will reach the stairs alive. Backing into the corridor will let me survive. (all exist) |
| Fight, new | Something I am carrying could save me here. |
| Descend | I am ready for the next level. |
| Stuck | There is more of this level to find. |

### 5.4 How code routes on the answers

One function per decision point, with named thresholds, in the style of `decide()` in `jevb.py`:

```
fight:
  will_die < 0.6                      -> rules
  will_die >= 0.6, an escape >= 0.5   -> Jev judge: take the best-rated escape
  will_die >= 0.6, no escape >= 0.5   -> Claude consult (section 6.3)
descend:
  ready >= 0.5                        -> rules (go down)
  ready <  0.5                        -> the goal's not-ready activity, if one is kept; else rules
api failure or timeout                -> rules
```

Thresholds are starting values. They are tuned on seed 1000 and confirmed on seed 5000.

### 5.5 Why Jev and not rules for the routing

For the fight, the rules could compute "rounds to live against rounds to kill" directly, and
iteration 54 tried a version of that with no gain. Jev's answer folds in the monster's nature, the
recent messages and the escapes, and it has measured better than the HP threshold at ranking
danger. For "ready to descend" there is no evidence yet either way; the goal table alone may be
enough, in which case that question is dropped. The no-router control in section 8 settles it.

## 6. The three experts

### 6.1 Rule engine (exists)

`pilot/engine.py`. The default for every turn and the fallback for every failure. Unchanged by this
design except for the goal check before descending.

### 6.2 Jev judge (exists)

`pilot/jevb.py`. Picks among the escapes the engine already knows how to carry out: stairs,
Elbereth, corridor. Known weakness: the escapes themselves. One open item is why surviving on
Elbereth does not become depth (suspected: the pilot heals, steps off, and loses the rematch).

### 6.3 Claude consult (to build)

Called only when Jev says the fight is lost and no known escape is likely. In the six arm runs that
was 50 to 130 asks per 64 games, and the pilot died within 20 turns in about half of them.

- **Why a reasoning model here.** These moments need improvisation over the whole pack: zap the
  unknown wand, read the scroll, quaff, throw everything, use the tool. That is multi-step reasoning
  over a varied inventory, which Jev's documentation says it cannot do and the rules have no
  branches for.
- **What it is sent.** The full picture, unlike Jev: the fight state, the complete inventory, the
  visible map, the last messages, and the list of engine routines it may call.
- **What it returns.** One routine and its arguments from the existing `ROUTINES` table (`use`,
  `throw`, `go_to`, `elbereth`, `pray`, and so on), through the existing brain interface
  (`pilot/brain.py`, `HaikuBrain`). No free-form keys.
- **Model.** Haiku first, since it is already wired and fast. A stronger Claude model is a one-line
  change if Haiku shows promise.
- **Cost.** About one or two calls per game.

### 6.4 What stays out of every expert's hands

Hard safety rules stay in the engine and are checked after any expert answers: no prayer while the
gate is closed, no melee on the never-melee list, no attacking peacefuls, no shop theft, no kicking
doors near the watch, no wielded weapon thrown. An expert can ask; the engine can refuse and fall
back to the rules.

## 7. Operating constraints

- Work only on `ai-player`; push only `ai-player` to `elevate`.
- Jev and Claude batches are started by Dave. The session's safety classifier blocks Claude Code
  from making the Jev call itself, and that is not to be worked around.
- The TypeSafe key stays in the macOS Keychain (`typesafe/jev`, account `elevate`).
- No Qwen arms.
- Every game records each ask, its state, the answers and the route taken in its replay page.

## 8. How each piece is measured

Same method as every engine change: the fixed 128 games, paired against the current rules baseline,
tuned on seed 1000 and confirmed on seed 5000. A piece is kept only if average deepest level rises
by 0.25 or more with experience level not falling by more than 0.25.

Added controls, each answering one question:

| Control | Question it answers |
|---|---|
| Rules only | The baseline. |
| Router with every route sent to rules | Does asking change anything by itself? (It should not.) |
| Goals without Jev (table decides "ready") | Does Jev add anything to the descend decision? |
| Router with Claude consult replaced by rules | Does the consult add anything beyond the judge? |
| Calibration table per question | Does each Noul predict what it claims to? |

The calibration table is required for every new question before it is allowed to steer.

## 9. Build order

Each phase stands alone and is measured before the next starts.

| Phase | Build | Needs Dave to run | Done when |
|---|---|---|---|
| 1 | `pilot/goals.py`: the analysis and the goal table from recorded runs | No | Tables reproduce section 4.3 from the run ids |
| 2 | One not-ready activity at a time (4.4), rules only | No | One is kept under the keep rule, or all are dropped and logged |
| 3 | Router skeleton: decision points, state builders, routing functions, all routes to rules | Yes | Runs match the rules baseline game for game |
| 4 | Claude consult for lost fights with no escape | Yes | Paired result against the judge-only run on both sets |
| 5 | Descend question, with the goals-without-Jev control | Yes | Calibration table, then paired result |
| 6 | "Something I am carrying could save me" and the stuck question | Yes | Calibration tables |

Phases 1 and 2 need no API and can start now. Phase 4 is the first real test of the router idea.

## 10. Risks and open questions

- **The not-ready problem may have no good answer.** If nothing in 4.4 pays, goals inform the router
  but do not change descent. The design still stands, with less to gain.
- **The level data is thin and from one engine version.** Thresholds will move. Mitigation:
  regenerate after each kept change; never hard-code a number from this document.
- **Armor.** The first cut shows no effect. Before dropping armor work entirely, redo the cut
  controlling for depth and for what killed the pilot.
- **Claude may not improvise better than rules.** Haiku equalled rules at blunt escalations. This
  design gives it better-chosen moments and a fuller picture, which is a hypothesis, not a result.
- **Latency.** Jev adds about an eighth of a second per ask; Haiku a second or more. Both are rare
  enough per game to ignore for batch runs.
- **NetHack version.** statico plays 5.0, this fork is 3.6.7. Their plan is a source of ideas, not
  of numbers.
- **Engine size.** `pilot/engine.py` is over 1,600 lines. New code goes in its own modules
  (`goals.py`, `router.py`), as `jevb.py` did.

## 11. References

- `docs/pilot-loop.md`: every iteration and its measurements, including the Jev judge runs.
- `docs/pilot-plan.md`: the engine change list; item 21 is the earlier, unbuilt pacing idea.
- `pilot/jevb.py`, `pilot/jev.py`, `pilot/brain.py`, `pilot/spoilers.py`, `pilot/frames.py`.
- TypeSafe documentation: docs.typesafe.ai (state, primitives, building guide, Jev 1.13 limitations).
- statico/jev-nethack: README, AGENTS.md, `jev/plan.py`, `jev/bot.py`, JOURNAL.md (read 2026-10-04).
