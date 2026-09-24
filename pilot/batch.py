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
import json
import csv
import fcntl
import os
import re
import struct
import subprocess
import termios
import threading
import time

from .brain import HaikuBrain, RuleBrain
from .channel import Channel
from . import dashboard
from .engine import Engine

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PLAYGROUND = os.path.join(HERE, "playground")
OPTIONS = "autopickup,pickup_types:$,time,showexp,dark_room,!legacy,!news,!autoquiver"


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
                 save_on_stall: bool = True, out_dir: str = os.path.join(PLAYGROUND, "batch")) -> None:
        self.out_dir = out_dir
        self.deepest = 0
        self.escalations: list = []  # (turn, events, order) for every brain call
        self.consult = isinstance(brain, HaikuBrain)  # strategic check-ins, not just escalations
        self.save_on_stall = save_on_stall
        self.saving = False
        self.name, self.role, self.brain = name, role, brain
        self.max_turns, self.max_seconds = max_turns, max_seconds
        self.sock = f"/tmp/nhb-{name}.sock"
        self.engine = Engine()
        self.channel = Channel(self.sock, self.on_state)
        self.last: dict = {}
        self.brain_calls = 0
        self.brain_seconds = 0.0
        self.brain_failures = 0  # calls that fell back to rules (timeout, crash)
        self.stall: str | None = None
        self.proc: subprocess.Popen | None = None
        self.result: dict | None = None  # Set when the game is over.
        self.feed: collections.deque = collections.deque(maxlen=40)  # recent (turn, kind, text) for the live page
        self._last_note = ""

    def on_state(self, s: dict) -> None:
        if self.saving:  # Answer "Really save?" and any --More-- on the way out.
            self.channel.send("y" if s["context"]["kind"] == "yn" else "\r")
            return
        self.last = s
        turn = s.get("status", {}).get("turn", 0)
        self.deepest = max(self.deepest, s.get("status", {}).get("dlvl") or 0)
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
                self.channel.send(keys)
                return
            order = self._decide(events, s)
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
            self.engine.order(order.routine, order.args, handles=events)
        self.stall = f"brain loop: {'; '.join(events)} (last order: {order.routine} {order.args})"
        self._end()

    def _decide(self, events: list[str], s: dict):
        """Ask the brain, timing it: slow or failing calls skew a batch."""
        started = time.time()
        self.brain_calls += 1
        order = self.brain.decide(self.engine.last_checks, events, s, self.engine.orders)
        self.brain_seconds += time.time() - started
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
        }

    @staticmethod
    def _drain(fd: int) -> None:
        try:
            while os.read(fd, 65536):
                pass
        except OSError:
            pass


def main() -> None:
    p = argparse.ArgumentParser(description="Run unattended NetHack games with the pilot")
    p.add_argument("--games", type=int, default=8)
    p.add_argument("--parallel", type=int, default=4)
    p.add_argument("--brain", choices=("rules", "haiku"), default="rules")
    p.add_argument("--role", default="Valkyrie")
    p.add_argument("--max-turns", type=int, default=20000)
    p.add_argument("--max-seconds", type=float, default=600)
    p.add_argument("--no-save", action="store_true", help="kill stalled games instead of saving them")
    args = p.parse_args()

    prepare_playground()
    batch_dir = os.path.join(PLAYGROUND, "batch")
    os.makedirs(batch_dir, exist_ok=True)
    board = os.path.join(batch_dir, "dashboard.html")
    run = time.strftime("%Y%m%d-%H%M%S")
    games = [Game(f"B{run[-6:]}{i:02d}", args.role,
                  HaikuBrain(log_path=os.path.join(PLAYGROUND, "pilot-brain.log"))
                  if args.brain == "haiku" else RuleBrain(),
                  args.max_turns, args.max_seconds, not args.no_save) for i in range(args.games)]
    results: list[dict] = []
    lock = threading.Lock()

    def finish(g: Game, r: dict) -> None:
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

    def worker(queue: list[Game]) -> None:
        while True:
            with lock:
                if not queue:
                    return
                g = queue.pop(0)
            r = g.play()
            finish(g, r)
            dashboard.write_game(os.path.join(batch_dir, f"game-{g.name}.html"), g, run)
            with lock:
                results.append(r)
                save_json()  # After every game, so a batch that dies early keeps its records.
                print(f"  {g.name}: Dlvl {r['dlvl']} XL {r['xlvl']} T{r['turn']} "
                      f"{r['death'] or r['stall']}", flush=True)

    def save_json() -> None:
        with open(os.path.join(batch_dir, f"{run}.json"), "w") as f:  # Everything, per game.
            json.dump({"run": run, "brain": args.brain, "games": sorted(results, key=lambda r: r["name"])}, f)

    stop = threading.Event()

    def refresh() -> None:
        tick = 0
        while not stop.wait(1):
            for g in games:  # Live per-game pages: every second while playing.
                if g.last and g.result is None:
                    dashboard.write_game(os.path.join(batch_dir, f"game-{g.name}.html"), g, run)
            if tick % dashboard.REFRESH_S == 0:
                dashboard.write(board, run, args.brain, games, batch_dir)
            tick += 1

    queue = list(games)
    threads = [threading.Thread(target=worker, args=(queue,)) for _ in range(args.parallel)]
    print(f"run {run}: {args.games} games, {args.parallel} at a time, {args.brain} brain", flush=True)
    print(f"live dashboard: open {board}", flush=True)
    dashboard.write(board, run, args.brain, games, batch_dir)
    threading.Thread(target=refresh, daemon=True).start()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    stop.set()

    path = os.path.join(batch_dir, f"{run}.csv")
    cols = ["name", "bucket", "death", "stall", "maxlvl", "dlvl", "xlvl", "race", "turn", "points", "gold",
            "brain_calls", "brain_seconds", "brain_failures", "seconds"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(results, key=lambda r: r["name"]))
    dashboard.write(board, run, args.brain, games, batch_dir)
    for g in games:
        if g.last:
            dashboard.write_game(os.path.join(batch_dir, f"game-{g.name}.html"), g, run)

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
    print(f"details: {path}")


if __name__ == "__main__":
    main()
