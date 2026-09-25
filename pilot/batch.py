"""Play many games unattended and measure how the pilot does.

    python3 -m pilot.batch --games 8 --parallel 4 [--brain rules|haiku] [--max-turns 20000]

Each game runs this fork's NetHack in a hidden pseudo-terminal, driven over
its aipipe socket by the engine and a brain. Results come from NetHack's
own xlogfile (depth, deepest level, experience level, turns, cause of death);
games the pilot can't continue are recorded as stalled, with the reason.
A summary prints at the end and every game is written to
playground/batch/<run>.csv.
"""

from __future__ import annotations

import argparse
import collections
import concurrent.futures
import json
import csv
import fcntl
import os
import re
import struct
import subprocess
import sys
import termios
import threading
import time

from .brain import HaikuBrain, QwenBrain, ReplayBrain, RuleBrain
from .channel import Channel
from . import dashboard
from .engine import Engine

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYGROUND = os.path.join(HERE, "playground")
OPTIONS = "autopickup,pickup_types:$,time,showexp,dark_room,!legacy,!news,!autoquiver"
NOW = 1790000000  # The fixed clock for seeded games (a weekday, not a full or new moon).


def prepare_playground() -> None:
    """Many games at once: per-name locks with no player cap (MAXPLAYERS=0),
    and clear letter locks left by games that were killed."""
    path = os.path.join(PLAYGROUND, "sysconf")
    with open(path) as f:
        text = f.read()
    fixed = re.sub(r"(?m)^MAXPLAYERS=\d+", "MAXPLAYERS=0", text)
    if fixed != text:
        with open(path, "w") as f:
            f.write(fixed)
    for name in os.listdir(PLAYGROUND):
        if re.fullmatch(r"[a-z]lock\.\d+", name):
            os.unlink(os.path.join(PLAYGROUND, name))


def cleanup_game(name: str) -> None:
    """Remove a finished or killed game's lock and level files."""
    for f in os.listdir(PLAYGROUND):
        if name in f and not f.endswith((".csv", "xlogfile")):
            os.unlink(os.path.join(PLAYGROUND, f))


SCENARIOS = os.path.join(PLAYGROUND, "scenarios")


def keep_scenario(name: str, why: str, state: dict) -> None:
    """Move a stalled game's save file into playground/scenarios/."""
    save_dir = os.path.join(PLAYGROUND, "save")
    for f in os.listdir(save_dir) if os.path.isdir(save_dir) else []:
        if re.fullmatch(r"\d+" + re.escape(name) + r"\..*", f):  # <uid><name>.Z
            os.makedirs(SCENARIOS, exist_ok=True)
            os.replace(os.path.join(save_dir, f), os.path.join(SCENARIOS, f))
            st = state.get("status", {})
            with open(os.path.join(SCENARIOS, name + ".json"), "w") as out:
                json.dump({"name": name, "save": f, "why": why, "dlvl": st.get("dlvl"),
                           "turn": st.get("turn"), "hp": f"{st.get('hp')}/{st.get('hpmax')}",
                           "saved": time.strftime("%Y-%m-%d %H:%M")}, out)
            return


def xlog_entries() -> dict[str, dict]:
    """name -> last xlogfile record (fields are key=value, tab separated)."""
    out = {}
    try:
        with open(os.path.join(PLAYGROUND, "xlogfile")) as f:
            for line in f:
                rec = dict(kv.split("=", 1) for kv in line.rstrip("\n").split("\t") if "=" in kv)
                out[rec.get("name", "")] = rec
    except FileNotFoundError:
        pass
    return out


# What a checkpoint may start. Exploring and fighting are the engine's own
# default and standing orders; a brain ordering them only gets in the way.
CONSULT_ROUTINES = {"throw", "step_away", "elbereth", "go_down", "use", "pick_up"}


def bucket(r: dict) -> str:
    """One failure bucket per game, for comparing runs."""
    death, stall, during = r.get("death", ""), r.get("stall", ""), r.get("died_while", "")
    if death:
        if "praying" in during:
            return "died praying"
        if "starvation" in death or "fainted" in during:
            return "died fainted/starving"
        if str(r.get("deathdnum")) == "2":
            return "died in the Mines"
        if re.search(r"wand|bolt|magic missile|death ray|ray of", death):
            return "died to a wand or bolt"
        if "invisible" in death:
            return "died to an invisible monster"
        return "died in melee/other"
    if stall.startswith(("Weak", "Fainting", "Fainted")):
        return "stall: Weak, no food"
    if stall.startswith("no way on"):
        return "stall: no way on" + (" (blocker)" if "in the way" in stall else "")
    if stall.startswith("brain loop"):
        return "stall: brain loop"
    if stall.startswith(("turn limit", "time limit")):
        return "stall: limit"
    return "stall: other"


class Game:
    """One unattended game: engine + brain on the socket, NetHack in a pty."""

    def __init__(self, name: str, role: str, brain, max_turns: int, max_seconds: float,
                 save_on_stall: bool = True, out_dir: str = os.path.join(PLAYGROUND, "batch"),
                 seed: int | None = None) -> None:
        self.out_dir = out_dir
        self.seed = seed      # Set: the game is reproducible (fixed RNG seed and clock, no bones).
        self.keys: list = []  # (turn, keys) for every key the pilot sent
        self.answers: list = []  # the brain's raw answer to every call, for replays
        self.trace: list = []    # (turn, dlvl, xlvl, hp, hunger, known map squares, activity) every 50 turns
        self._next_trace = 0
        self.deepest = 0
        self.escalations: list = []  # (turn, events, order) for every brain call
        self.consult = isinstance(brain, HaikuBrain)  # strategic check-ins, not just escalations
        self.save_on_stall = save_on_stall
        self.saving = False
        self.name, self.role, self.brain = name, role, brain
        self.max_turns, self.max_seconds = max_turns, max_seconds
        self.sock = f"/tmp/nhb-{name}.sock"
        self.engine = Engine()
        self.channel = Channel(self.sock, self._on_state_safe)
        self.last: dict = {}
        self.brain_calls = 0
        self.brain_seconds = 0.0
        self.brain_failures = 0  # calls that fell back to rules (timeout, crash)
        self.stall: str | None = None
        self.proc: subprocess.Popen | None = None
        self.result: dict | None = None  # Set when the game is over.
        self.feed: collections.deque = collections.deque(maxlen=100)  # recent (turn, kind, text) for the live page
        self._last_note = ""

    def _on_state_safe(self, s: dict) -> None:
        """An engine error ends the game as a harness error at once; it used
        to kill the channel thread and leave the game hanging to its time limit."""
        try:
            self.on_state(s)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.stall = self.stall or f"harness error: {type(e).__name__}: {e}"[:160]
            self.saving = True  # Don't try to save through a broken engine; just stop.
            if self.proc and self.proc.poll() is None:
                self.proc.kill()

    def on_state(self, s: dict) -> None:
        if self.saving:  # Answer "Really save?" and any --More-- on the way out.
            self.channel.send("y" if s["context"]["kind"] == "yn" else "\r")
            return
        self.last = s
        turn = s.get("status", {}).get("turn", 0)
        self.deepest = max(self.deepest, s.get("status", {}).get("dlvl") or 0)
        if turn >= self._next_trace and s["context"]["kind"] == "command":
            # Progress trace every 50 turns: what the autopsy looks at for
            # effort without progress (turns passing, nothing changing).
            self._next_trace = turn - turn % 50 + 50
            st = s.get("status", {})
            known = sum(ch != " " for row in s.get("map", [])[1:22] for ch in row)
            self.trace.append((turn, st.get("dlvl"), st.get("xlvl"), st.get("hp"), st.get("hunger", ""),
                               known, self.engine._activity()))
        for msg in s.get("messages", []):
            self.feed.append((turn, "game", msg))
        if self.engine.note and self.engine.note != self._last_note and self.engine.note != "dismiss --More--":
            self.feed.append((turn, "pilot", self.engine.note))
            self._last_note = self.engine.note
        if s.get("status", {}).get("turn", 0) > self.max_turns:
            self.stall = f"turn limit {self.max_turns}"
            self._end()
            return
        if self.consult and self.engine.consults and s["context"]["kind"] == "command":
            events, self.engine.consults = self.engine.consults, []
            order = self._decide(events, s)
            if order.orders:
                self.engine.set_orders(order.orders)
            if order.routine in CONSULT_ROUTINES and self.engine.routine is None:  # Never cut across a routine.
                self.engine.order(order.routine, order.args)
            self.escalations.append((turn, "; ".join(events), order.routine))
            self.feed.append((turn, "brain", f"{'; '.join(events)} -> {order.routine or 'carry on'} "
                              f"{order.orders or ''} {order.say}"))
        for _ in range(4):
            keys, events = self.engine.step(s)
            if keys:
                self.keys.append((turn, keys))
                self.channel.send(keys)
                return
            order = self._decide(events, s)
            failed = next((e.split(" failed:")[0] for e in events if " failed:" in e), None)
            if order.routine and order.routine == failed:
                # The routine that just failed, ordered again: the rules pick something else
                # (13 of 32 Qwen games ended as brain loops this way).
                fb = RuleBrain().decide(self.engine.last_checks, events, s, self.engine.orders)
                order.routine, order.args, order.say = fb.routine, fb.args, f"(rules: {failed} just failed) {fb.say}"
            if s["context"]["kind"] != "command" and order.routine not in (None, "keys"):
                # Only keys answer a game prompt; a routine here re-fires the
                # same prompt until the game ends. The rules escape it.
                fb = RuleBrain().decide(self.engine.last_checks, events, s, self.engine.orders)
                order.routine, order.args, order.say = fb.routine, fb.args, f"(rules: a routine can't answer a prompt) {fb.say}"
            if order.routine is None and isinstance(self.brain, HaikuBrain):
                # Unattended: no human to wait for, so null ends the game. Try the rules first.
                fb = self.brain.fallback.decide(self.engine.last_checks, events, s, self.engine.orders)
                if fb.routine is not None:
                    order.routine, order.args, order.say = fb.routine, fb.args, f"(rules) {fb.say}"
            if order.orders:
                self.engine.set_orders(order.orders)
            self.escalations.append((turn, "; ".join(events), order.routine))
            self.feed.append((s.get("status", {}).get("turn", 0), "brain",
                              f"{'; '.join(events)} -> {order.routine or 'wait'} {order.args or ''}"))
            if order.routine is None:
                self.stall = "; ".join(events)
                self._end()
                return
            if not self.engine.order(order.routine, order.args, handles=events):
                # A hard rule refused it (a prayer with the gate closed): the rules answer instead.
                fb = RuleBrain().decide(self.engine.last_checks, events, s, self.engine.orders)
                if fb.routine is None or not self.engine.order(fb.routine, fb.args, handles=events):
                    self.stall = f"{'; '.join(events)} (the brain's {order.routine} was refused)"
                    self._end()
                    return
        self.stall = f"brain loop: {'; '.join(events)} (last order: {order.routine} {order.args})"
        self._end()

    def _decide(self, events: list[str], s: dict):
        """Ask the brain, timing it: slow or failing calls skew a batch."""
        started = time.time()
        self.brain_calls += 1
        order = self.brain.decide(self.engine.last_checks, events, s, self.engine.orders)
        self.brain_seconds += time.time() - started
        self.answers.append({"routine": order.routine, "args": order.args, "orders": order.orders,
                             "say": order.say})
        if order.say.startswith("(brain unavailable"):
            self.brain_failures += 1
        return order

    def _end(self) -> None:
        """Stop the game: save it as a scenario when it stalled (so it can
        be replayed), otherwise kill it."""
        if self.save_on_stall and self.stall and not self.saving and self.last.get("player"):
            self.saving = True
            self.channel.send("\x1b\x1bS")  # Close any open prompt first, then save.
            return
        if self.proc and self.proc.poll() is None:
            self.proc.kill()

    def play(self) -> dict:
        if os.path.exists(self.sock):
            os.unlink(self.sock)
        server = threading.Thread(target=self.channel.serve, daemon=True)
        server.start()
        while not os.path.exists(self.sock):
            time.sleep(0.01)
        master, slave = os.openpty()
        fcntl.ioctl(slave, termios.TIOCSWINSZ, struct.pack("HHHH", 24, 80, 0, 0))
        env = dict(os.environ, NETHACK_CONTROL=self.sock, NETHACKOPTIONS=OPTIONS, TERM="xterm-256color")
        if self.seed is not None:
            env.update(NETHACK_SEED=str(self.seed), NETHACK_NOW=str(NOW), NETHACKOPTIONS=OPTIONS + ",!bones")
        started = time.time()
        self.proc = subprocess.Popen(
            [os.path.join(PLAYGROUND, "nethack"), "-u", self.name, "-p", self.role],
            stdin=slave, stdout=slave, stderr=slave, env=env, cwd=HERE, start_new_session=True)
        os.close(slave)
        drain = threading.Thread(target=self._drain, args=(master,), daemon=True)
        drain.start()
        while self.proc.poll() is None:
            if time.time() - started > self.max_seconds:
                self.stall = self.stall or f"time limit {self.max_seconds:.0f}s"
                self._end()
            time.sleep(0.2)
        os.close(master)
        cleanup_game(self.name)
        if hasattr(self.brain, "close"):
            self.brain.close()  # Or its claude process outlives the game.
        if self.saving:
            keep_scenario(self.name, self.stall or "", self.last)
        if self.stall and self.last:  # Keep the final snapshot to see what went wrong.
            os.makedirs(self.out_dir, exist_ok=True)
            with open(os.path.join(self.out_dir, f"{self.name}.json"), "w") as f:
                json.dump({"stall": self.stall, "state": self.last}, f)
        st = self.last.get("status", {})
        return {
            "name": self.name, "seconds": round(time.time() - started, 1),
            "brain_calls": self.brain_calls, "brain_seconds": round(self.brain_seconds),
            "brain_failures": self.brain_failures, "stall": self.stall or "",
            "dlvl": st.get("dlvl"), "xlvl": st.get("xlvl"), "turn": st.get("turn"),
            "hp": f"{st.get('hp')}/{st.get('hpmax')}", "gold": st.get("gold"),
            "stats": dict(self.engine.memory.stats), "deepest": self.deepest,
            "race": st.get("race"), "prayers": self.engine.memory.prayer_log,
            "escalations": self.escalations, "feed": list(self.feed),
            "seed": self.seed, "keys": self.keys, "answers": self.answers, "brain": self.brain.name,
            "trace": self.trace,
            "role": self.role,
        }

    @staticmethod
    def _drain(fd: int) -> None:
        try:
            while os.read(fd, 65536):
                pass
        except OSError:
            pass


def _finish(g: Game, r: dict) -> None:
    """Fill in the outcome from NetHack's xlogfile as soon as a game ends."""
    rec = xlog_entries().get(g.name)
    if rec and not r["stall"]:
        r.update(death=rec.get("death", ""), maxlvl=rec.get("maxlvl", ""),
                 turn=rec.get("turns", r["turn"]), xlvl=rec.get("xplevel", r["xlvl"]),
                 points=rec.get("points", ""), died_while=rec.get("while", ""),
                 deathdnum=rec.get("deathdnum", ""))
    else:
        r.update(death="", maxlvl=r["deepest"] or r.get("dlvl", ""), points="")
    r["bucket"] = bucket(r)
    g.result = r


def _error_result(name: str, why: str) -> dict:
    return {"name": name, "stall": "harness error: " + why[:120], "death": "", "dlvl": None, "xlvl": None,
            "turn": 0, "maxlvl": "", "points": "", "stats": {}, "prayers": [], "escalations": [], "feed": [],
            "keys": [], "answers": [], "brain_calls": 0, "seconds": 0, "bucket": "harness error"}


def _write_live(g: Game, path: str) -> None:
    """What the main process's overview page needs from this game."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"  # Per thread: the refresher and the game share a pid.
    with open(tmp, "w") as f:
        json.dump({"last": g.last, "result": g.result, "stall": g.stall, "note": g.engine.note,
                   "routine": g.engine.routine, "stats": g.engine.memory.stats}, f)
    os.replace(tmp, path)


def _live_proxy(name: str, batch_dir: str):
    """A stand-in with the fields dashboard.write reads, from live-<name>.json."""
    from types import SimpleNamespace as NS
    try:
        with open(os.path.join(batch_dir, f"live-{name}.json")) as f:
            d = json.load(f)
    except (OSError, ValueError):
        d = {}
    return NS(name=name, last=d.get("last"), result=d.get("result"), stall=d.get("stall"), feed=[],
              engine=NS(note=d.get("note") or "", routine=d.get("routine"), memory=NS(stats=d.get("stats") or {})))


def _play_one(spec: dict) -> dict:
    """One game in its own process: engine, brain, and its live page."""
    batch_dir = os.path.join(PLAYGROUND, "batch")
    brain = (HaikuBrain(log_path=os.path.join(PLAYGROUND, "pilot-brain.log"), journal=spec["journal"])
             if spec["brain"] == "haiku" else QwenBrain(journal=spec["journal"]) if spec["brain"] == "qwen"
             else RuleBrain())
    if spec.get("model") and hasattr(brain, "model"):
        brain.model = spec["model"]
    g = Game(spec["name"], spec["role"], brain, spec["max_turns"], spec["max_seconds"], spec["save"],
             seed=spec["seed"])
    page, live = os.path.join(batch_dir, f"game-{g.name}.html"), os.path.join(batch_dir, f"live-{g.name}.json")
    stop = threading.Event()

    def refresh() -> None:  # Live page every second while playing.
        while not stop.wait(1):
            if g.last:
                dashboard.write_game(page, g, spec["run"])
                _write_live(g, live)
    threading.Thread(target=refresh, daemon=True).start()
    try:
        r = g.play()
        _finish(g, r)
    except Exception:  # A crashed game is recorded, not lost.
        import traceback
        err = traceback.format_exc()
        print(f"  {g.name}: harness error\n{err}", flush=True)
        r = _error_result(g.name, err.strip().splitlines()[-1])
        r["brain_calls"] = g.brain_calls
        g.result = r
    stop.set()
    if g.last:
        dashboard.write_game(page, g, spec["run"])
    _write_live(g, live)
    return r


def replay(which: str) -> None:
    """Rerun a recorded seeded game: same seed and clock, the brain's
    recorded answers, today's engine. Same keys means the game repeated
    exactly; otherwise print where it first went another way."""
    run, name = which.split("/")
    with open(os.path.join(PLAYGROUND, "batch", f"{run}.json")) as f:
        rec = next(g for g in json.load(f)["games"] if g["name"] == name)
    if rec.get("seed") is None:
        raise SystemExit(f"{name} wasn't seeded; only games from a --seed batch replay exactly")
    prepare_playground()
    brain = ReplayBrain(rec["answers"]) if rec.get("brain") == "haiku" else RuleBrain()
    g = Game(f"R{name[1:]}", rec.get("role", "Valkyrie"), brain, 10 ** 9, 3600, save_on_stall=False,
             out_dir=os.path.join(PLAYGROUND, "replays"), seed=rec["seed"])
    r = g.play()
    old, new = [tuple(k) for k in rec["keys"]], [tuple(k) for k in r["keys"]]
    same = next((i for i, (a, b) in enumerate(zip(old, new)) if a != b), min(len(old), len(new)))
    print(f"recorded: T{rec['turn']} {rec.get('death') or rec.get('stall')}")
    print(f"replayed: T{r['turn']} {r['stall'] or 'ended'}")
    if old == new:
        print(f"identical: all {len(old)} key sends match")
    elif new[:len(old)] == old:
        print(f"identical for all {len(old)} recorded key sends; the replay then kept going (no turn cap)")
    else:
        at = old[same] if same < len(old) else new[same]
        print(f"diverged at key send {same} of {len(old)} (turn {at[0]}): recorded "
              f"{old[same] if same < len(old) else '(end)'}, replayed {new[same] if same < len(new) else '(end)'}")


def main() -> None:
    p = argparse.ArgumentParser(description="Run unattended NetHack games with the pilot")
    p.add_argument("--games", type=int, default=8)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--brain", choices=("rules", "haiku", "qwen"), default="rules")
    p.add_argument("--model", help="model for the brain (haiku alias, or an Ollama tag such as qwen3.5:9b)")
    p.add_argument("--role", default="Valkyrie")
    p.add_argument("--max-turns", type=int, default=20000)
    p.add_argument("--max-seconds", type=float, default=600)
    p.add_argument("--no-save", action="store_true", help="kill stalled games instead of saving them")
    p.add_argument("--seed", type=int, help="reproducible games: game i gets seed SEED+i (same SEED = same dungeons)")
    p.add_argument("--no-journal", action="store_true", help="(default since 2026-09-25: conclusions cost depth) play without conclusions")
    p.add_argument("--with-conclusions", action="store_true", help="put memory/conclusions.md in the brain's prompt")
    p.add_argument("--conclusions", help="play with this conclusions file (a stratum); implies --with-conclusions")
    p.add_argument("--replay", metavar="RUN/NAME", help="rerun one recorded seeded game with its brain answers")
    args = p.parse_args()
    if (args.seed is not None or args.replay) and os.environ.get("PYTHONHASHSEED") != "0":
        # Set iteration order must not vary between runs either.
        os.execvpe(sys.executable, [sys.executable, "-m", "pilot.batch", *sys.argv[1:]],
                   dict(os.environ, PYTHONHASHSEED="0"))
    if args.replay:
        replay(args.replay)
        return
    # The learning curve (2026-09-25) showed conclusions in the prompt cost Haiku 0.3 to 0.7 levels:
    # off unless asked for, until a stratum beats the no-conclusions base on the test seeds.
    args.no_journal = not (args.with_conclusions or args.conclusions)

    prepare_playground()
    batch_dir = os.path.join(PLAYGROUND, "batch")
    os.makedirs(batch_dir, exist_ok=True)
    board = os.path.join(batch_dir, "dashboard.html")
    run = time.strftime("%Y%m%d-%H%M%S")
    while os.path.exists(os.path.join(batch_dir, f"{run}.json")):  # Two batches started in the same second
        time.sleep(1)                                                # once shared an id and overwrote each other.
        run = time.strftime("%Y%m%d-%H%M%S")
    with open(os.path.join(batch_dir, f"{run}.json"), "w") as f:  # Claim the id at once.
        json.dump({"run": run, "brain": args.brain, "games": []}, f)
    if not args.no_journal:
        # Pin the stratum: every game of this run reads the same snapshot, whatever
        # a reflection does to conclusions.md meanwhile (one Qwen arm mixed three).
        import shutil
        from .brain import JOURNAL
        snap = os.path.join(batch_dir, f"{run}.conclusions.md")
        shutil.copy(args.conclusions or JOURNAL, snap)
        args.conclusions = snap
        os.environ["PILOT_CONCLUSIONS"] = os.path.abspath(snap)  # inherited by the game processes
    specs = [{"name": f"B{run[-6:]}{i:02d}", "role": args.role, "brain": args.brain, "journal": not args.no_journal,
              "model": args.model,
              "max_turns": args.max_turns, "max_seconds": args.max_seconds, "save": not args.no_save,
              "seed": None if args.seed is None else args.seed + i, "run": run} for i in range(args.games)]
    results: list[dict] = []

    def save_json() -> None:
        with open(os.path.join(batch_dir, f"{run}.json"), "w") as f:  # Everything, per game.
            json.dump({"run": run, "brain": args.brain, "model": args.model, "journal": not args.no_journal,
                       "conclusions": args.conclusions, "seed": args.seed,
                       "games": sorted(results, key=lambda r: r["name"])}, f)

    def board_games() -> list:
        return [_live_proxy(sp["name"], batch_dir) for sp in specs]

    stop = threading.Event()

    def refresh() -> None:
        while not stop.wait(dashboard.REFRESH_S):
            dashboard.write(board, run, args.brain, board_games(), batch_dir)

    print(f"run {run}: {args.games} games, {args.parallel} at a time, {args.brain} brain", flush=True)
    print(f"live dashboard: open {board}", flush=True)
    dashboard.write(board, run, args.brain, board_games(), batch_dir)
    threading.Thread(target=refresh, daemon=True).start()
    # One process per game: the engines are Python, and as threads they
    # shared one core (16 at a time ran no faster than 4).
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.parallel) as pool:
        futures = {pool.submit(_play_one, sp): sp for sp in specs}
        for fut in concurrent.futures.as_completed(futures):
            try:
                r = fut.result()
            except Exception as e:  # The worker process itself died.
                r = _error_result(futures[fut]["name"], f"{type(e).__name__}: {e}")
            results.append(r)
            save_json()  # After every game, so a batch that dies early keeps its records.
            print(f"  {r['name']}: Dlvl {r['dlvl']} XL {r['xlvl']} T{r['turn']} "
                  f"{r['death'] or r['stall']}", flush=True)
    stop.set()
    games = board_games()
    for sp in specs:
        try:
            os.unlink(os.path.join(batch_dir, f"live-{sp['name']}.json"))
        except OSError:
            pass

    path = os.path.join(batch_dir, f"{run}.csv")
    cols = ["name", "bucket", "death", "stall", "maxlvl", "dlvl", "xlvl", "race", "turn", "points", "gold",
            "brain_calls", "brain_seconds", "brain_failures", "seconds"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(results, key=lambda r: r["name"]))
    dashboard.write(board, run, args.brain, games, batch_dir)

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    n = len(results) or 1
    print(f"\n{len(results)} games. avg deepest level {sum(num(r['maxlvl']) for r in results) / n:.1f}, "
          f"avg XL {sum(num(r['xlvl']) for r in results) / n:.1f}, "
          f"avg turns {sum(num(r['turn']) for r in results) / n:.0f}")
    totals = collections.Counter()
    for r in results:
        totals.update(r.get("stats", {}))
    turns = {k[7:]: v for k, v in totals.items() if k.startswith("turns: ")}
    spent = sum(turns.values()) or 1
    print("  turns by activity: " + ", ".join(f"{k} {100 * v / spent:.0f}%" for k, v in
                                               sorted(turns.items(), key=lambda kv: -kv[1])[:10]))
    print("  engine counters (all games): " + ", ".join(
        f"{k}={v}" for k, v in totals.most_common(30) if not k.startswith("turns: ")))
    ends = collections.Counter((r["death"] or ("stalled: " + r["stall"]))[:70] for r in results)
    for why, count in ends.most_common():
        print(f"  {count} x {why}")
    print("  by bucket: " + ", ".join(f"{k} {v}" for k, v in
                                     collections.Counter(r["bucket"] for r in results).most_common()))
    from .runs import summaries
    summaries()  # Write this run's small summary sidecar while its file is fresh.
    print(f"details: {path}")


if __name__ == "__main__":
    main()
