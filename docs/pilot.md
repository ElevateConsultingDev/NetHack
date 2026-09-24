# Pilot: an engine/brain autopilot for NetHack 3.6

Goal: play NetHack well enough to ascend. This fork (branch `ai-player`, based
on `NetHack-3.6`) adds a structured control channel to the game and a Python
pilot that plays through it.

## Pieces

| Where | What |
|---|---|
| `src/aipipe.c`, `include/aipipe.h`, `doc/aipipe.md` | The channel. With `NETHACK_CONTROL=/path.sock` the game connects to a Unix socket and, every time it waits for a key, sends a JSON snapshot (what's being asked, messages, status, map, named cells with peaceful/difficulty/class, inventory). It reads keys back as `{"keys":"..."}`. Terminal keys still work. Without the variable it's stock 3.6.7. Hooks: `tty_nhgetch` (key reads), `xwaitforspace` (--More--), `choose_windows` (installs window-proc wrappers). |
| `pilot/engine.py` | ENGINE, fully deterministic. Checks, mechanics, standing orders, routines, default activity. |
| `pilot/brain.py` | BRAIN. `RuleBrain` (code) or `HaikuBrain` (Claude Haiku over a persistent `claude -p` stream-json session with `--tools ""`, `--strict-mcp-config`, `--setting-sources=` so the user's CLAUDE.md/hooks stay out). Falls back to rules on any failure. |
| `pilot/__main__.py` | Interactive pilot with chat: `python3 -m pilot [--brain haiku\|rules] [--auto]`, game in another pane via `./nh [name] [role]`. `/auto` `/manual` `/speed` `/why` `/orders k=v` `/status` `/quit`; plain text chats with the brain. Typing in the game pane takes over. |
| `pilot/batch.py` | Unattended games in hidden ptys: `python3 -m pilot.batch --games 16 --parallel 4 [--brain haiku]`. Outcomes from `playground/xlogfile`; CSV per run in `playground/batch/`. Stalled games are saved as scenarios. |
| `pilot/scenario.py` | `python3 -m pilot.scenario list \| run <name> \| restore <name>`: replay saved stalls against the current engine (NetHack deletes a restored save; the copy in `playground/scenarios/` is kept). |
| `pilot/dashboard.py` | `playground/batch/dashboard.html` (open it in a browser; self-refreshing, no server): all-time north-star stats and milestone ladder (from xlogfile achieve bits up to ASCENDED), current run, turns by activity, a card per game linking to a live 1s page (colored map, status, feed pinned to the newest line, inventory). |
| `nh` | Launch this build connected to the pilot socket (`/tmp/nhpilot.sock`). |

Build: `sh sys/unix/setup.sh sys/unix/hints/macosx10.14 && make WANT_SOURCE_INSTALL=1 all` (installs into `playground/`, gitignored; batch sets `MAXPLAYERS=0` in `playground/sysconf`). macOS socket paths must be under 104 bytes, so sockets live in `/tmp`.

## The design (Dave's engine vs brain)

- **Engine = deterministic, runs every snapshot.**
  - Checks: hunger, wound tier (fine/hurt/badly hurt/critical), prayer safety, adjacent/visible/dangerous hostiles with difficulty, food, level explored, stairs.
  - Mechanics (one right answer): --More-- (also when one is showing behind a pending prompt), pre-game, never attack a peaceful, prayer confirm, eat prompts, engrave prompts, pickup menus by class, end-of-game prompts.
  - Routines, one key at a time until done/failed/stuck: explore, loot, go_down, go_to, fight, eat, rest, pray, elbereth (engrave then rest on it), throw, step_away, pick_up, pickup_gold, search_walls, search_dead_ends, probe_dark, use, keys.
  - Default activity when nothing is ordered: loot wanted items, explore, then (only without known stairs) probe dark caves, search dead ends and walls, then go down.
- **Standing orders** (the brain sets them; the engine enforces without asking): `fight_up_to`, `avoid` (never melee; paths route around), `eat_at`, `eat_corpses`, `rest_below`, `retreat_below`, `pray_when_critical`, `pickup_gold`, `loot`, `ranged_kill`, `explore_fully`, `descend`.
- **Escalations**: the brain is woken only for what the orders don't cover (too-tough monster, cockatrice adjacent, badly hurt in a fight, Weak with no food, critical with prayer unsafe, unfamiliar prompt, failed brain routine, no way on) or when the human chats. Answered escalations stay quiet until the routine ends. Raw walking keys from the brain are rejected.

## Lessons (each cost a run to learn)

- Hard safety belongs in the engine: `F` attacks skip NetHack's "Really attack?", so the snapshot carries a peaceful flag.
- Give the LLM named facts (NOTABLE cells with coordinates), not raw map characters.
- Solid rock stays blank forever: frontier = unvisited walkable squares next to blank.
- `dark_room` must be on or dark rooms erase themselves from the map.
- Prompts stack: a --More-- can show while a getlin/yn is already pending; dismiss it first.
- Remember "peaceful" by the game's flag, not by square; cap every wait.
- Shops: never loot with a shopkeeper in view; never kick a "Closed for inventory" door.
- Measure with batches (and replay scenarios), never single games; 8 games is noisy, use 16+.

## Numbers so far

Rule brain, recent 16-game runs: avg deepest level ~3-3.6, avg XL ~4, ~4000-4800 turns, best ever Dlvl 8 / XL 8, one game to the 20000-turn cap. First Haiku batch (4 games): Dlvl 7 / XL 6 (killed by a Minetown watchman), Dlvl 5 / XL 6 at T6692, one floating-eye stall. See the dashboard's past-runs table for the trend.

## Next: the ranked plan

`docs/pilot-plan.md` holds a 25-item plan from a research workflow (web
strategy from strong players and prior bots, plus an analysis of every batch
game and saved stall; raw inputs with sources in `docs/research/`). Headline:
81% of 217 games end in a stall, 19% in death; hunger alone ends 42%, and a
quarter of those were carrying food the engine didn't recognize. Items 1-8 are
small engine/brain fixes aimed at ~60% of current endings: a trustworthy
prayer gate (1000-turn gap, parse the result, Luck), a complete food list and
tins, keeping messages across --More-- snapshots, standing orders not
pre-empting a danger routine (Elbereth), shop and Watch safety.

Work it top-down, one item at a time: implement, replay the relevant saved
scenarios (`python3 -m pilot.scenario list`), run a 16-game batch, compare on
the dashboard, commit. Yardstick from the research: AutoAscend (2021 NeurIPS
winner) had a median score of ~5300; 1 in 20 of its Valkyries reached Dlvl 10.

Also seen in the first Haiku batch: Haiku is consulted only 2-4 times a game
and made two poor calls when badly hurt (ate next to a watchman; stepped away
from a rothe). Plan item 25 covers keeping safety in the engine and giving the
brain better events.
