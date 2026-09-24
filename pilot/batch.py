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
        self.stall = "brain loop: routines kept finishing at once"
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
        st = self.last.get("status", {})
        return {
            "name": self.name, "seconds": round(time.time() - started, 1),
            "brain_calls": self.brain_calls, "stall": self.stall or "",
            "dlvl": st.get("dlvl"), "xlvl": st.get("xlvl"), "turn": st.get("turn"),
            "hp": f"{st.get('hp')}/{st.get('hpmax')}", "gold": st.get("gold"),
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
    run = time.strftime("%Y%m%d-%H%M%S")
    names = [f"B{run[-6:]}{i:02d}" for i in range(args.games)]
    results: list[dict] = []
    lock = threading.Lock()

    def worker(queue: list[str]) -> None:
        while True:
            with lock:
                if not queue:
                    return
                name = queue.pop(0)
            brain = (HaikuBrain(log_path=os.path.join(PLAYGROUND, "pilot-brain.log"))
                     if args.brain == "haiku" else RuleBrain())
            r = Game(name, args.role, brain, args.max_turns, args.max_seconds).play()
            with lock:
                results.append(r)
                print(f"  {name}: Dlvl {r['dlvl']} XL {r['xlvl']} T{r['turn']} "
                      f"{r['stall'] or ''}", flush=True)

    queue = list(names)
    threads = [threading.Thread(target=worker, args=(queue,)) for _ in range(args.parallel)]
    print(f"run {run}: {args.games} games, {args.parallel} at a time, {args.brain} brain", flush=True)
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    xlog = xlog_entries()
    for r in results:
        rec = xlog.get(r["name"])
        if rec and not r["stall"]:
            r["death"] = rec.get("death", "")
            r["maxlvl"] = rec.get("maxlvl", "")
            r["turn"] = rec.get("turns", r["turn"])
            r["xlvl"] = rec.get("xplevel", r["xlvl"])
            r["points"] = rec.get("points", "")
        else:
            r["death"], r["maxlvl"], r["points"] = "", r.get("dlvl", ""), ""

    os.makedirs(os.path.join(PLAYGROUND, "batch"), exist_ok=True)
    path = os.path.join(PLAYGROUND, "batch", f"{run}.csv")
    cols = ["name", "death", "stall", "maxlvl", "dlvl", "xlvl", "turn", "points", "gold",
            "brain_calls", "seconds"]
    with open(path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(sorted(results, key=lambda r: r["name"]))

    def num(v):
        try:
            return float(v)
        except (TypeError, ValueError):
            return 0.0
    n = len(results) or 1
    print(f"\n{len(results)} games. avg deepest level {sum(num(r['maxlvl']) for r in results) / n:.1f}, "
          f"avg XL {sum(num(r['xlvl']) for r in results) / n:.1f}, "
          f"avg turns {sum(num(r['turn']) for r in results) / n:.0f}")
    ends = collections.Counter((r["death"] or ("stalled: " + r["stall"]))[:70] for r in results)
    for why, count in ends.most_common():
        print(f"  {count} x {why}")
    print(f"details: {path}")


if __name__ == "__main__":
    main()
