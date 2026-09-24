"""NetHack pilot: run this in one pane, ./nh in another.

    python3 -m pilot [--auto] [--speed 0.15] [--sock /tmp/nhpilot.sock]

Chat commands:
    /auto          hand the controls to the pilot
    /manual        take them back (typing in the game window also does this)
    /speed <sec>   delay between pilot keys (default 0.15)
    /why           the pilot's last decision and its reason
    /status        a one-line summary of the game
    /quit          stop the pilot (the game keeps running, stock)
Anything else is chat (the Haiku brain comes next; for now it's noted).
"""

from __future__ import annotations

import argparse
import json
import threading
import time

from .auto import Memory, decide
from .channel import Channel


class Pilot:
    def __init__(self, sock: str, auto: bool, speed: float) -> None:
        self.mode = "auto" if auto else "manual"
        self.speed = speed
        self.memory = Memory()
        self.state: dict | None = None
        self.last = ("", "no decision yet")
        self.channel = Channel(sock, self.on_state)
        self._lock = threading.Lock()

    def say(self, text: str) -> None:
        print(f"\r[pilot] {text}", flush=True)

    def on_state(self, s: dict) -> None:
        with self._lock:
            self.state = s
            with open("/tmp/nhpilot-last.json", "w") as f:  # For debugging: the latest snapshot.
                json.dump(s, f)
            for m in s.get("messages", []):
                print(f"\r  | {m}", flush=True)
            if self.mode == "auto" and s.get("last_input") == "terminal":
                self.mode = "manual"
                self.say("you took the controls (/auto to hand them back)")
            if self.mode == "auto":
                self.act()

    def act(self) -> None:
        s = self.state
        if s is None:
            return
        keys, reason = decide(s, self.memory)
        self.last = (keys or "", reason)
        if keys is None:
            self.say(f"waiting on you: {reason}")
            return
        if reason != "dismiss --More--":
            self.say(reason)
        time.sleep(self.speed)
        self.channel.send(keys)

    def status_line(self) -> str:
        s = self.state
        if not s or "status" not in s:
            return "no game state yet"
        st = s["status"]
        return (f"{st['role']} XL{st['xlvl']} HP {st['hp']}/{st['hpmax']} Pw {st['pw']}/{st['pwmax']} "
                f"AC {st['ac']} Dlvl {st['dlvl']} T{st['turn']} ${st['gold']} "
                f"{st['hunger']} {' '.join(st['conditions'])} [{self.mode}]").strip()

    def command(self, line: str) -> bool:
        """Handle one chat line. Returns False to quit."""
        cmd, _, arg = line.strip().partition(" ")
        if cmd == "/quit":
            return False
        if cmd == "/auto":
            with self._lock:
                self.mode = "auto"
                self.say("pilot has the controls")
                self.act()
        elif cmd == "/manual":
            self.mode = "manual"
            self.say("you have the controls")
        elif cmd == "/speed":
            try:
                self.speed = float(arg)
                self.say(f"speed {self.speed}s per key")
            except ValueError:
                self.say("usage: /speed 0.15")
        elif cmd == "/why":
            keys, reason = self.last
            self.say(f"last: {keys!r} because {reason}")
        elif cmd == "/status":
            self.say(self.status_line())
        elif line.strip():
            self.say("chat isn't wired to Haiku yet; noted: " + line.strip())
        return True


def main() -> None:
    p = argparse.ArgumentParser(description="NetHack pilot")
    p.add_argument("--sock", default="/tmp/nhpilot.sock")
    p.add_argument("--auto", action="store_true", help="start with the pilot driving")
    p.add_argument("--speed", type=float, default=0.15, help="seconds between pilot keys")
    args = p.parse_args()

    pilot = Pilot(args.sock, args.auto, args.speed)
    threading.Thread(target=pilot.channel.serve, daemon=True).start()
    pilot.say(f"listening on {args.sock}; start the game in another pane with ./nh")
    pilot.say(f"mode: {pilot.mode}. /auto, /manual, /speed, /why, /status, /quit")
    try:
        while pilot.command(input()):
            pass
    except (EOFError, KeyboardInterrupt):
        pass


if __name__ == "__main__":
    main()
