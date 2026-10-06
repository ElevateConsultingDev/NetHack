"""The game log: every message the game shows, stamped with turn and level, plus
events (level changes, warnings, checkpoints, loads, helper questions). One file
per character in logs/; each checkpoint keeps a copy of the log as of that moment
(<checkpoint>.log), and loading a checkpoint brings that copy back.
"""
import os
import shutil
import time


class GameLog:
    def __init__(self, logs_dir):
        self.dir = logs_dir
        self.path = None
        self.turn = self.dlvl = None
        self.pending = []  # lines before the character's name is known

    def write(self, line):
        line = line.rstrip("\n")
        if not self.path:
            self.pending.append(line)
            return
        with open(self.path, "a") as f:
            f.write(line + "\n")

    def where(self):
        return f"T{self.turn} D{self.dlvl}" if self.turn is not None else "start"

    def event(self, text):
        self.write(f"{self.where()}  * {text}")

    def bind(self, name):
        """Write to this character's log (logs/<name>.log)."""
        path = os.path.join(self.dir, f"{name}.log")
        if path == self.path:
            return
        os.makedirs(self.dir, exist_ok=True)
        self.path = path
        if not os.path.exists(path):
            self.write(f"=== {name}: log started {time.strftime('%Y-%m-%d %H:%M')} ===")
        for line in self.pending:
            self.write(line)
        self.pending = []

    def on_state(self, state, quiet=False):
        """Log what a new game state brings: its messages, and level changes.
        quiet: the game is saving/restoring for a checkpoint; skip its chatter."""
        st = state.get("status") or {}
        if st.get("name"):
            self.bind(st["name"])
        turn, dlvl = st.get("turn"), st.get("dlvl")
        if turn is not None and self.turn is not None and turn < self.turn - 1:
            self.write(f"=== new game, {time.strftime('%Y-%m-%d %H:%M')} ===")
        if dlvl is not None and dlvl != self.dlvl and self.dlvl is not None:
            self.write(f"T{turn} D{dlvl}  --- now on Dlvl {dlvl} ({st.get('dungeon', '')}) ---")
        if turn is not None:
            self.turn, self.dlvl = turn, dlvl
        for m in [] if quiet else state.get("messages", []):
            self.write(f"{self.where()}  {m}")

    def copy_to(self, path):
        """Keep the log as it is now beside a checkpoint."""
        if self.path and os.path.exists(self.path):
            shutil.copy2(self.path, path)

    def restore(self, path, name):
        """Loading a checkpoint: the log goes back to what it was then."""
        self.bind(name)
        if os.path.exists(path):
            shutil.copy2(path, self.path)
        self.turn = None

    def tail(self, n=60):
        if not self.path or not os.path.exists(self.path):
            return ""
        with open(self.path) as f:
            return "".join(f.readlines()[-n:])


if __name__ == "__main__":
    import tempfile
    d = tempfile.mkdtemp()
    log = GameLog(d)
    log.on_state({"messages": ["Hello Dave, welcome to NetHack!"]})  # before the name is known
    log.on_state({"status": {"name": "Dave", "turn": 1, "dlvl": 1}, "messages": ["You see a fountain."]})
    log.on_state({"status": {"name": "Dave", "turn": 40, "dlvl": 2, "dungeon": "The Dungeons of Doom"},
                  "messages": ["You climb down the stairs."]})
    log.copy_to(os.path.join(d, "cp.log"))
    log.event("checkpoint saved")
    log.on_state({"status": {"name": "Dave", "turn": 90, "dlvl": 2}, "messages": ["You kill the leprechaun!"]})
    text = open(log.path).read()
    assert "welcome to NetHack" in text and "T40 D2  --- now on Dlvl 2" in text and "leprechaun" in text
    log.restore(os.path.join(d, "cp.log"), "Dave")
    assert "leprechaun" not in open(log.path).read()  # back to the checkpoint's log
    print("gamelog ok")
