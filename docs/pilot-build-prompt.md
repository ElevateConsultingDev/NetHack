# Build prompt: an engine/brain autopilot that aims to ascend NetHack

Hand this whole file to a coding agent. It describes what to build, how the pieces fit, what has already been learned the hard way, and how to measure progress. A working reference implementation exists at `ElevateConsultingDev/NetHack`, branch `ai-player` (this repo); you may read it, but the point is to build your own and try to beat it.

---

## 1. The goal

Build a program that plays NetHack 3.6.7 well enough to **ascend** (retrieve the Amulet of Yendor and offer it on the Astral Plane). Ascension is the only goal; every intermediate metric (deepest level, experience level, turns survived) is a proxy for progress toward it. Judge every change by whether it moves the character deeper while keeping it strong enough to survive there.

The character is a **Valkyrie** (the strongest early-game role). Race is chosen by the game unless you choose it; note that dwarves are at peace with the Gnomish Mines and humans are not (see lessons).

For scale: the NeurIPS 2021 NetHack challenge winner (AutoAscend, a hand-written bot) had a median score around 5,300 and reached Dlvl 10 in about 1 game in 20. In September 2026 a frontier LLM (GPT 6 Astra) ascended a dwarven Valkyrie in 37,140 turns, choosing nearly every move itself with helper scripts; its harness and journals are at github.com/kenforthewin/nethack_astra and worth reading. The reference pilot here reaches an average deepest level of about 4.4 on its fixed test seeds, with a best of Dlvl 9.

## 2. The architecture you must keep

**Engine and brain.** This is the owner's design and it is not up for debate:

- **The ENGINE is fully deterministic.** Given the same game state and memory it always sends the same keys. It computes checks (hunger, wound tier, prayer safety, adjacent and visible hostiles with difficulty, food, whether the level is explored, known stairs), answers mechanics (prompts with exactly one right answer), enforces standing orders, runs routines one key at a time, and falls back to a default activity. It never "decides" strategy.
- **The BRAIN decides.** It is a language model (Claude Haiku in the reference, via `claude -p`) with a rule-based fallback (`RuleBrain`) used whenever the model fails, times out, or is unavailable. The brain sets **standing orders** (policies the engine enforces without asking) and picks **routines** (named skills the engine carries out). It never sends raw movement keys.
- **Escalations.** The engine wakes the brain only for what the standing orders don't cover: a monster too tough to fight, a cockatrice adjacent, badly hurt in a fight, Weak with no food, critical HP with prayer unsafe, an unfamiliar prompt, a routine of the brain's that failed, no way on. An escalation the brain has answered stays quiet until its routine ends.
- **Checkpoints.** Separately, the brain is consulted for strategy at checkpoints: arriving on a new level, the first sight of each monster type, and every 500 turns. "Carry on" is always a valid answer and a checkpoint can never stall the game.
- **Hard safety lives in the engine, never only in a prompt.** Models state a rule and then break it (the "knowing-doing gap", BALROG, arXiv 2411.13543). If a brain order would violate a hard rule (pray with the gate closed, attack a peaceful, melee a floating eye), the engine refuses it and says so, and the caller answers again (the rule brain, or the human).

## 3. What to build, in order

### Phase 1: the channel (C, in the game)

Fork NetHack 3.6 and add a controller channel. With `NETHACK_CONTROL=/path.sock` the game connects to a Unix socket; each time it waits for a key it sends one newline-delimited JSON `state` line, and it reads keys back as `{"keys":"..."}`. Without the variable it is stock NetHack, and terminal keys always keep working (a human can take over at any time). The reference protocol is `doc/aipipe.md`; match it or improve it. The state must include:

- `context`: what is being asked (`command`, `yn` with prompt and choices, `getlin`, `menu` with items and how many may be picked, `extcmd`, `more`, `key`), plus a flag when a `--More--` is showing behind a pending prompt.
- `messages`: every message since the last state.
- `status`: HP, max HP, Pw, AC, XL, gold, Dlvl, dungeon branch name, turn, attributes, hunger, encumbrance, alignment, role, race, and conditions (Blind, Conf, Stun, Hallu, Sick, Slime, Stone, Strngl, Lev...).
- `map` (the screen rows), `player` position, and `cells`: every non-plain square named as the `;` command would name it (monsters with a `peaceful` flag and a difficulty, objects by appearance, traps, features such as doors and stairs).
- `inventory` lines exactly as the game prints them.
- Nothing the player could not know: no unidentified item identities, no RNG state.

Hook points in 3.6: `tty_nhgetch` (key reads), `xwaitforspace` (`--More--`), and `choose_windows` (install wrappers around the message, yn, getlin, menu and extended-command window procedures to capture context). macOS socket paths must be under 104 bytes, so put sockets in `/tmp`.

**Make games reproducible from the start.** Add `NETHACK_SEED` (seed both RNGs; 3.6 also reseeds from `/dev/urandom` every time it creates a level, in `reseed_random`, so turn that off when a seed is set) and `NETHACK_NOW` (a fixed clock: moon phase, night and Friday the 13th come from `getnow()`). Batches run with bones off. With these, the same seed plus the same keys replays a game exactly; prove it with a test.

### Phase 2: the engine (Python)

Structure it as: `View` (convenience over one snapshot: features, walkability, peaceful checks), `Memory` (what persists between snapshots), `checks()`, `mechanics()`, routines, standing orders, default activity, and `Engine.step(state) -> (keys, escalations)`.

- **Mechanics** (exactly one right answer): dismiss `--More--` (including one showing behind a pending prompt, or typed answers get eaten), pre-game screens, answer prayer confirmations the engine asked for, never attack a peaceful ("Really attack?" is always n), eat prompts, engrave prompts, pickup menus by wanted class, end-of-game prompts.
- **Routines** (one key per step, each returns keys or `done: ...` / `failed: ...`): explore, loot, go_down, go_to, fight, eat, rest, pray, elbereth (engrave then rest on it), throw, step_away, pick_up, pickup_gold, search_walls, search_dead_ends, probe_dark, use, keys (answering a prompt only).
- **Standing orders** (brain-set, engine-enforced): `fight_up_to` (difficulty; default XL+2), `avoid` (never melee these; paths route around them), `eat_at`, `eat_corpses`, `rest_below`, `retreat_below`, `pray_when_critical`, `pickup_gold`, `loot` (item classes), `ranged_kill` (throw at these when in line), `explore_fully`, `descend`.
- **Default activity** when nothing is ordered: loot wanted items, explore, then (only without known stairs) probe dark areas, search dead ends and walls, then go down.
- **A stuck guard:** the same keys five times with the turn and position unchanged means they do nothing; block that target and escalate.

### Phase 3: the brain

- A system prompt that explains the engine, lists routines and standing-order keys, and asks for exactly one line of JSON: `{"routine": ..., "args": {...}, "orders": {...}, "say": "..."}`. Give the model named facts (monsters and features with coordinates), not just raw map characters.
- One persistent model session per game (context accumulates within the game). **Turn extended thinking off for the per-call brain**: with thinking, real briefs took 22 to 52 seconds a call; without, 2 to 3 seconds and the same answers. At checkpoint frequency that difference decides whether a batch finishes.
- Keep the model's process isolated from the host's own agent configuration (no tools, no MCP servers, no user settings or hooks).
- Close each game's model process when the game ends (they leak otherwise).
- In unattended play a "no routine" answer to an escalation means "wait for a human" who isn't there; fall back to the rule brain instead of ending the game.

### Phase 4: the harness

- **Batch runner:** many games unattended in hidden pseudo-terminals, results from NetHack's own `xlogfile` (death, deepest level, XL, turns, the `while` field such as "fainted" or "praying"), stalls recorded with a reason. Classify every game into a **failure bucket** (Weak stall, no way on, no way on with a blocker, brain loop, died fainted/starving, died praying, died in the Mines, died to a wand or bolt, died to an invisible monster, melee). Write a per-run JSON with every game's stats, prayer log, escalations, last 100 feed lines, keys sent and raw brain answers, **after every game** so a crashed batch keeps its records.
- **Replay:** `--replay RUN/NAME` reruns a seeded game with the brain's recorded answers (no model calls) and reports whether every key matched or where it first diverged.
- **Compare:** game-by-game diff of two runs on the same seeds, with a SAME/diff marker from the key logs.
- **Dashboard:** a self-refreshing static HTML page (north-star stats, milestone ladder from xlogfile achievement bits, per-game live pages with the colored map, status, feed and inventory). The owner watches it from a phone.
- **Saved stalls** as replayable scenarios (the game's own save file, copied, since restoring deletes it).
- **Parallelism:** run each game in its own process, not a thread. With threads the engines share one interpreter lock and 16 at a time is no faster than 4. A model-backed game costs about 300 MB for the model CLI process, so plan concurrency around memory and rate limits, not cores alone.

### Phase 5: the self-improvement loops

- **Inner loop (the brain learns):** a versioned, human-editable `journal.md` the brain reads at the start of every game, with two sections: lessons for the brain, and suspected engine bugs. After each batch a reflection step (a stronger model, one call) rewrites it from the run records. Tell it that harness limits (turn or time caps) are not failures, to cite game names for every claim, and to keep human-written lessons unless the records contradict them. Review its output: it will over-learn from artifacts.
- **Outer loop (the engine improves):** one fix per iteration: take the largest failure bucket, pick the smallest fix, check it, measure it, keep or drop, record it, push. A coding agent runs this on a timer.
- **Measurement rules, learned by getting them wrong:**
  - Decide keep or drop on a **deterministic pair**: the rule brain plus fixed seeds, without and with the change. Every game that differs differs because of the change; identical key logs prove which games it never touched. Live LLM batches vary run to run: in one iteration Haiku showed melee deaths going 6 to 8 while every targeted game had improved, and the deterministic pair then showed the change was actually worse for a different reason.
  - **Lead with depth.** Keep a change if average deepest level rises by 0.25 or more without XL falling more than 0.25, or if its target bucket shrinks without losing depth. A bucket-only rule once dropped a change that took a game from Dlvl 3 to Dlvl 9.
  - **Hold out seeds.** Deciding every change on the same 16 dungeons overfits; check regularly on seeds the loop never decides on.
  - **Test the journal.** Periodically play the model brain with and without the journal on the same seeds (32+ games per arm); if the journal is not ahead, cut it back.
  - Fix harness problems in their own commits and re-baseline when they change play (turning thinking off changed the brain, so the old baseline no longer applied).

## 4. Lessons the reference pilot paid for

Each of these cost at least one batch to learn. Build them in from the start.

**Safety and the game's rules**
- `F`+direction attacks skip NetHack's "Really attack?" prompt, so the snapshot must carry the peaceful flag and the engine must check it. Remember peacefulness by the game's flag, not by square.
- Never fight shopkeepers, watchmen, priests or guards whatever the difficulty says. Most wand deaths were shopkeepers the pilot angered itself: a thrown dagger that missed its target flew on into the shopkeeper, and a popped gas spore caught one in the blast. Never throw along a line with any peaceful (pets included) on it out to about 10 squares; never pop or throw at a gas spore with a peaceful within 1 of it.
- Shops: never loot with a shopkeeper in view; never kick a "Closed for inventory" door.
- The prayer gate: first prayer from turn 300; then at least 1000 turns apart (the timeout after a prayer is rnz(350), which exceeds 1000 about 8% of the time). Parse the result from the messages: "You feel that <god> is well-pleased/pleased/satisfied" (or "You are surrounded by a shimmering light") is success; "displeased", "The voice of ...", "Thou ..." is failure, and in 3.6 a failed prayer raises god anger, so close the gate for good. "You murderer!", "You cannibal!", "That's bad luck!" and "You feel guilty" mean Luck fell; close the gate until it decays (one point per 600 turns). Major trouble (what prayer fixes) is exactly: HP at most 5 or at most max/7, Weak or worse hunger (only when there is no food), Stone, Slime, Strngl, Sick, lycanthropy. A prayer only restores nutrition if hunger was the trouble it fixed.
- Weak returns about 850 turns after a prayer, before the 1000-turn gate reopens; starvation takes about 300 more turns past Weak. Keep playing while the gate is within 300 turns of opening instead of stopping.
- Living on prayer alone eventually fails (one game lived 10,000 turns on 8 prayers; the 9th was refused).

**Food**
- Match food names as whole words: "tin" matches inside "floating", and a pilot died eating a rotted floating eye corpse that way. Handle plurals where the noun is not last ("lumps of royal jelly", "cloves of garlic").
- No eggs (an unknown egg can be a cockatrice egg). Tins announce their contents in a message ("It smells like newts.") and then ask a bare "Eat it?"; answer from the smell (never your own race, never while hallucinating). Eat tins last; they take turns to open.
- Only eat a corpse you killed recently (about 30 turns) of a safe, non-kin species; lichen and lizard never rot. Record kills made by thrown weapons too, or floating eyes (killed only by throwing) are never eaten, and their telepathy never gained.
- Hungry with no food and the stairs known: go down. A new level has new monsters and new food; finishing the current one only burns turns.

**Maps and movement**
- `dark_room` must be on or dark rooms erase themselves from the map. Solid rock stays blank forever: the exploration frontier is unvisited walkable squares next to blank.
- An item lying on the stairs hides the `>`; remember stairs in memory, not only on screen.
- Dark cave floor (Gnomish Mines) is not drawn, so stairs can be visible with no drawn path. NetHack's own travel command (`_`, then `>` to put the cursor on the stairs, then `.`) knows the way, but each command moves only one step and it can bounce forever: cap it per level. Plan item: remember floor you have walked.
- Memory keyed by level number collides between the Mines and the main dungeon (both have a "Dlvl 3"); key by branch too, or forget a level when leaving it.

**Monsters**
- The Gnomish Mines' gnomes and dwarves are peaceful only to dwarves and gnomes. Any other race under XL 8 should leave the Mines on arrival and mark that staircase; this cut Mines deaths from 5 to 1 in 16 games.
- Floating eyes: never melee (unless blind). Throw daggers, and **go fetch the dagger** even with the eye right next to you: it only hurts if hit, and paths never walk into monsters. Refusing to loot near it left the pilot standing beside the eye with its only dagger on the floor; fixing that cut blocker stalls from 4 to 1 and raised average depth by 0.6.
- Elbereth is subtle. Standing orders must not attack from the Elbereth square (that erases it), but resting on it while being hit is also fatal: a dust engraving wears off, and one test game rested on a failed one until dead. Both simple fixes were measured and dropped; the right one needs reading the engraving back and a list of monsters that ignore it (@ humans, minotaurs, shopkeepers, guards, the blind).
- Rest while being hit by something invisible kills you: "It bites!" with nothing visible means stop resting and fight the square.

**Harness**
- Prompts stack; cap every wait; don't let an unanswered prompt stall a game.
- Measure with batches, never single games; 8 games is noise, 16 is the minimum, and paired seeds beat bigger unpaired batches.
- The end-of-game prompts ("Do you want an account of creatures vanquished?") must be mechanics, or they wake the brain and crowd the feed that explains the death.

## 5. What is not done yet (good places to beat the reference)

From the reference's ranked plan (`docs/pilot-plan.md`) and its journal: telepathy (eat floating eyes, keep a blindfold, fight blind), Elbereth done right, a search overhaul (per-square counts, scored targets, escalating budgets), a stuck-ladder watchdog, corridor positioning in fights, staying off wand lines and killing wand users first, Excalibur (dip a long sword at XL 5 at a fountain, not in Minetown), nymph and leprechaun handling, altar BUC testing before wearing found gear, Sokoban, a Mines policy for dwarves, and the whole mid and late game (protection, reflection and magic resistance, the Quest, the Castle wand, Gehennom, the invocation, the Planes). The reference's two worst open problems today are melee deaths on Dlvl 3 to 6 and levels with no known way down.

## 6. Acceptance for your build

1. Same seed, same keys: a replayed game matches its recording key for key (test it).
2. A 16-game batch runs unattended to completion and writes per-game records and failure buckets.
3. A deterministic A/B tool shows, game by game, what a change did.
4. Hard safety rules are enforced in the engine and covered by a runnable self-check.
5. On the reference's fixed seeds (`--seed 1000`, games 1000 to 1015, rule brain), report average deepest level, average XL and the bucket counts, and compare with the reference's current numbers in its git log. Then show the same on held-out seeds.

Work in a git repo, commit each logical step with its measured before and after numbers, and write down what you tried and dropped as well as what you kept.
