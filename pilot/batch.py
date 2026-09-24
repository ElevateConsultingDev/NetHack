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


class Game:
    """One unattended game: engine + brain on the socket, NetHack in a pty."""

    def __init__(self, name: str, role: str, brain, max_turns: int, max_seconds: float) -> None:
        self.name, self.role, self.brain = name, role, brain
        self.max_turns, self.max_seconds = max_turns, max_seconds
        self.sock = f"/tmp/nhb-{name}.sock"
        self.engine = Engine()
        self.channel = Channel(self.sock, self.on_state)
        self.last: dict = {}
        self.brain_calls = 0
        self.stall: str | None = None
        self.proc: subprocess.Popen | None = None
        self.result: dict | None = None  # Set when the game is over.

    def on_state(self, s: dict) -> None:
        self.last = s
        if s.get("status", {}).get("turn", 0) > self.max_turns:
            self.stall = f"turn limit {self.max_turns}"
            self._end()
            return
        for _ in range(4):
            keys, events = self.engine.step(s)
            if keys:
                self.channel.send(keys)
                return
            self.brain_calls += 1
            order = self.brain.decide(self.engine.last_checks, events, s, self.engine.orders)
            if order.orders:
                self.engine.set_orders(order.orders)
            if order.routine is None:
                self.stall = "; ".join(events)
                self._end()
                return
            self.engine.order(order.routine, order.args, handles=events)
        self.stall = f"brain loop: {'; '.join(events)} (last order: {order.routine} {order.args})"
        self._end()

    def _end(self) -> None:
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
        if self.stall and self.last:  # Keep the final snapshot to see what went wrong.
            with open(os.path.join(PLAYGROUND, "batch", f"{self.name}.json"), "w") as f:
                json.dump({"stall": self.stall, "state": self.last}, f)
        st = self.last.get("status", {})
        return {
            "name": self.name, "seconds": round(time.time() - started, 1),
            "brain_calls": self.brain_calls, "stall": self.stall or "",
            "dlvl": st.get("dlvl"), "xlvl": st.get("xlvl"), "turn": st.get("turn"),
            "hp": f"{st.get('hp')}/{st.get('hpmax')}", "gold": st.get("gold"),
            "stats": dict(self.engine.memory.stats),
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
    args = p.parse_args()

    prepare_playground()
    batch_dir = os.path.join(PLAYGROUND, "batch")
    os.makedirs(batch_dir, exist_ok=True)
    board = os.path.join(batch_dir, "dashboard.html")
    run = time.strftime("%Y%m%d-%H%M%S")
    games = [Game(f"B{run[-6:]}{i:02d}", args.role,
                  HaikuBrain(log_path=os.path.join(PLAYGROUND, "pilot-brain.log"))
                  if args.brain == "haiku" else RuleBrain(),
                  args.max_turns, args.max_seconds) for i in range(args.games)]
    results: list[dict] = []
    lock = threading.Lock()

    def finish(g: Game, r: dict) -> None:
        """Fill in the outcome from NetHack's xlogfile as soon as a game ends."""
        rec = xlog_entries().get(g.name)
        if rec and not r["stall"]:
            r.update(death=rec.get("death", ""), maxlvl=rec.get("maxlvl", ""),
                     turn=rec.get("turns", r["turn"]), xlvl=rec.get("xplevel", r["xlvl"]),
                     points=rec.get("points", ""))
        else:
            r.update(death="", maxlvl=r.get("dlvl", ""), points="")
        g.result = r

    def worker(queue: list[Game]) -> None:
        while True:
            with lock:
                if not queue:
                    return
                g = queue.pop(0)
            r = g.play()
            finish(g, r)
            with lock:
                results.append(r)
                print(f"  {g.name}: Dlvl {r['dlvl']} XL {r['xlvl']} T{r['turn']} "
                      f"{r['death'] or r['stall']}", flush=True)

    stop = threading.Event()

    def refresh() -> None:
        while not stop.wait(dashboard.REFRESH_S):
            dashboard.write(board, run, args.brain, games, batch_dir)

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
    cols = ["name", "death", "stall", "maxlvl", "dlvl", "xlvl", "turn", "points", "gold",
            "brain_calls", "seconds"]
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
    print(f"details: {path}")


if __name__ == "__main__":
    main()
