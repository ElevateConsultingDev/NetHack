"""NetHack pilot: run this in one pane, ./nh in another.

    python3 -m pilot [--brain haiku|rules] [--auto] [--speed 0.05]

The engine runs every snapshot; the brain (Haiku, or fixed rules) is asked
only when the engine reports something to decide.

Chat commands:
    /auto          hand the controls to the pilot
    /manual        take them back (typing in the game window also does this)
    /speed <sec>   delay between pilot keys
    /why           the current routine and the engine's last step
    /status        a one-line summary of the game
    /quit          stop the pilot (the game keeps running, stock)
Anything else goes to the brain; it answers, and may change what it's doing.
"""

from __future__ import annotations

import argparse
import json
import os
import threading
import time

from .brain import HaikuBrain, Order, RuleBrain
from .channel import Channel
from .engine import Engine, View, checks

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RUNTIME = os.path.join(HERE, "playground")  # gitignored; runtime files live here


class Pilot:
    def __init__(self, sock: str, brain, auto: bool, speed: float) -> None:
        self.mode = "auto" if auto else "manual"
        self.speed = speed
        self.brain = brain
        self.engine = Engine()
        self.state: dict | None = None
        self.channel = Channel(sock, self.on_state)
        self._lock = threading.Lock()
        self._said = ""
        self._last_msg = ""

    def say(self, who: str, text: str) -> None:
        if text and text != self._said:
            print(f"\r[{who}] {text}", flush=True)
            self._said = text

    # --- game loop ---

    def on_state(self, s: dict) -> None:
        with self._lock:
            self.state = s
            with open(os.path.join(RUNTIME, "pilot-last.json"), "w") as f:
                json.dump(s, f)  # The latest snapshot, for debugging.
            for m in s.get("messages", []):
                if m != self._last_msg:  # Collapse repeats.
                    print(f"\r  | {m}", flush=True)
                self._last_msg = m
            if self.mode == "auto" and s.get("last_input") == "terminal":
                self.mode = "manual"
                self.say("pilot", "you took the controls (/auto to hand them back)")
            self.act()

    def act(self) -> None:
        s = self.state
        if s is None:
            return
        for _ in range(4):  # A few brain rounds per snapshot at most.
            keys, events = self.engine.step(s)
            if self.mode != "auto":
                return  # Manual: the engine keeps its checks current, nothing is sent.
            if keys:
                if self.engine.note != "dismiss --More--":
                    self.say("engine", f"{self.engine.routine or 'mechanics'}: {self.engine.note}")
                time.sleep(self.speed)
                self.channel.send(keys)
                return
            order = self.brain.decide(self.engine.last_checks or self._checks(s), events, s)
            self.say(self.brain.name, (order.say + " " if order.say else "")
                     + (f"-> {order.routine} {order.args or ''}" if order.routine else "-> waiting on you"))
            if order.routine is None:
                return
            self.engine.order(order.routine, order.args)
        self.say("pilot", "the brain keeps picking routines that finish at once; waiting on you")

    def _checks(self, s: dict) -> dict:
        return checks(View(s, self.engine.memory), self.engine.memory) if "player" in s else {}

    # --- chat ---

    def status_line(self) -> str:
        s = self.state
        if not s or "status" not in s:
            return "no game state yet"
        st = s["status"]
        return (f"{st['role']} XL{st['xlvl']} HP {st['hp']}/{st['hpmax']} Pw {st['pw']}/{st['pwmax']} "
                f"AC {st['ac']} Dlvl {st['dlvl']} T{st['turn']} ${st['gold']} {st['hunger']} "
                f"{' '.join(st['conditions'])} [{self.mode}, {self.brain.name} brain, "
                f"routine: {self.engine.routine or 'none'}]").strip()

    def command(self, line: str) -> bool:
        """Handle one chat line. Returns False to quit."""
        cmd, _, arg = line.strip().partition(" ")
        if cmd == "/quit":
            return False
        if cmd == "/auto":
            with self._lock:
                self.mode = "auto"
                self.say("pilot", "the pilot has the controls")
                self.act()
        elif cmd == "/manual":
            self.mode = "manual"
            self.say("pilot", "you have the controls")
        elif cmd == "/speed":
            try:
                self.speed = float(arg)
                self.say("pilot", f"{self.speed}s between keys")
            except ValueError:
                self.say("pilot", "usage: /speed 0.05")
        elif cmd == "/why":
            self.say("pilot", f"routine {self.engine.routine or 'none'} {self.engine.args or ''}: "
                              f"{self.engine.note or '(nothing yet)'}")
        elif cmd == "/status":
            self.say("pilot", self.status_line())
        elif line.strip():
            with self._lock:
                s = self.state or {}
                order = self.brain.chat(line.strip(), self._checks(s) if s else {}, s)
                self.say(self.brain.name, order.say or "(no reply)")
                if order.routine:
                    self.engine.order(order.routine, order.args)
                    self.say("pilot", f"-> {order.routine} {order.args or ''}")
                    if self.mode == "auto":
                        self.act()
        return True


def main() -> None:
    p = argparse.ArgumentParser(description="NetHack pilot")
    p.add_argument("--sock", default="/tmp/nhpilot.sock")
    p.add_argument("--brain", choices=("haiku", "rules"), default="haiku")
    p.add_argument("--model", default="haiku", help="Claude model for the haiku brain")
    p.add_argument("--auto", action="store_true", help="start with the pilot driving")
    p.add_argument("--speed", type=float, default=0.05, help="seconds between pilot keys")
    args = p.parse_args()

    os.makedirs(RUNTIME, exist_ok=True)
    brain = (HaikuBrain(args.model, log_path=os.path.join(RUNTIME, "pilot-brain.log"))
             if args.brain == "haiku" else RuleBrain())
    pilot = Pilot(args.sock, brain, args.auto, args.speed)
    threading.Thread(target=pilot.channel.serve, daemon=True).start()
    pilot.say("pilot", f"listening on {args.sock}; start the game in another pane with ./nh")
    pilot.say("pilot", f"{pilot.mode} mode, {brain.name} brain. /auto /manual /speed /why /status /quit")
    try:
        while pilot.command(input()):
            pass
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
