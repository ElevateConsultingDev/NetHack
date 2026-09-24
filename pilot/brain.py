"""The brain: decides what the engine should do next.

Called only at decision points (a routine finished or failed, a check
changed, an unfamiliar prompt, or the human said something). It returns an
Order: a routine name and args for the engine, plus a short line to say.

RuleBrain is the stand-in: fixed priorities in code. HaikuBrain asks Claude
Haiku through a long-lived `claude -p` session (the same setup as the DnD
game's DM) and falls back to RuleBrain if the answer is missing or invalid.
"""

from __future__ import annotations

import json
import os
import urllib.request
import queue
import subprocess
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field

from .engine import ROUTINES


@dataclass
class Order:
    routine: str | None  # None: no change (chat) / wait for the human (decision)
    args: dict = field(default_factory=dict)
    say: str = ""
    orders: dict = field(default_factory=dict)  # standing-order changes


class RuleBrain:
    """Handles escalations with fixed rules; the stand-in for Haiku."""

    name = "rules"

    def decide(self, c: dict, events: list[str], s: dict, orders: dict | None = None) -> Order:
        ev = "; ".join(events)
        if ev.startswith("prompt:"):
            return Order("keys", {"keys": "\x1b"}, say="unfamiliar prompt: escape out of it")
        if ev.startswith("badly hurt") or ev.startswith("critical HP"):
            return Order("elbereth", say="hurt and in trouble: engraving Elbereth")
        if "(dangerous to be near)" in ev:
            return Order("step_away", say="backing away from something I shouldn't touch")
        if "adjacent, difficulty" in ev:
            name = ev.split(" adjacent")[0]
            return Order("fight", {"target": name}, say=f"the {name} is tough, but it's on me: fighting")
        if " failed:" in ev:
            return Order("explore", say="that didn't work; back to clearing the level")
        return Order(None, say=f"{ev}; your call")

    def chat(self, text: str, c: dict, s: dict, orders: dict) -> Order:
        return Order(None, say="(rule brain: I can't chat; start with --brain haiku)")


SYSTEM = """You are the brain of a NetHack 3.6 autopilot, playing to win (retrieve the Amulet of Yendor and ascend) for a human who watches and chats with you.

An ENGINE does everything deterministic, fast, without asking you:
- mechanics: --More--, pre-game screens, prayer confirmation, never attacking peacefuls;
- STANDING ORDERS (which you set): fight adjacent hostiles up to a difficulty, never melee the avoid list, eat known-safe food at a hunger level, rest when hurt and alone, pray on major trouble (critical HP, Weak with no food, stoning, sliming, strangling, sickness, lycanthropy) when the prayer gate is open (1000 turns apart, never after a failed prayer or a Luck penalty), pick up gold;
- a default activity: explore the level, go down the stairs when done, search the walls if there are no stairs.

You are asked when something is outside the standing orders (an ESCALATION): a monster that's too tough or on the avoid list, hunger with no safe food, critical HP when prayer isn't safe, an unfamiliar prompt, a routine of yours that failed, no way on, or the human talking to you.

You are also CONSULTED at checkpoints: arriving on a new level, the first sight of a monster type, and every 500 turns. That is your chance to plan: set standing orders for what's ahead (avoid a monster, fight_up_to, descend, eat_at, retreat_below). Routine null means carry on; that is the usual answer. A routine you give at a checkpoint runs only if nothing else is in progress.

Answer with a ROUTINE for the engine to carry out, and optionally standing-order changes. Routines:
{routines}

Standing-order keys: fight_up_to (int or null = your level + 2), avoid (list of monster names), eat_at ("Hungry", "Weak", or "never"), rest_below (fraction of max HP), pray_when_critical (bool), pickup_gold (bool), descend (bool), loot (string of item class symbols to pick up while clearing a level), explore_fully (bool: search dead ends before going down), retreat_below (fraction of max HP: below it, with a hostile adjacent, you're asked what to do).

The default activity clears each level: loot wanted items, explore everything, search dead ends, then go down. The goal is to get strong (experience, gear), not to dive.

You get ESCALATION or EVENTS, STANDING ORDERS, CHECKS, STATUS, MESSAGES, INVENTORY, PROMPT (if any), NOTABLE (named map cells with x,y) and the MAP (row index = y, column + 1 = x; @ is you).

Reply with exactly ONE line of JSON and nothing else:
{{"routine": "<name or null>", "args": {{...}}, "orders": {{...changes, or empty}}, "say": "<one short sentence to the human>"}}
- routine null: for an escalation, wait for the human; for chat, keep going as you were.
- "keys" is only for answering a game prompt (e.g. "y", "n", an inventory letter, "\\u001b" for Escape). Never walk with keys: the engine walks.
- Items: use routine "use" (quaff, read, wear, wield, zap...) or "pick_up". Map symbols ? ! % [ ) = are items, never required to find stairs.
- Play solid NetHack: Elbereth and retreat beat dying; don't melee floating eyes or cockatrices; don't eat unknown or old corpses; keep your pet; identify before relying on unknown items; Sokoban and the Mines' end are worth it once strong enough.
- Follow the human's orders unless clearly suicidal; say so if you refuse.
"""


def _brief(c: dict, events: list[str], s: dict, chat: str | None, orders: dict) -> str:
    st = s.get("status", {})
    ctx = s.get("context", {})
    rows = [f"{y:2d} {row.rstrip()}" for y, row in enumerate(s.get("map", [])) if row.strip()]
    inv = [f"{i['letter']} - {i['text']}" for i in s.get("inventory", [])]
    parts = []
    if chat is not None:
        parts.append(f"THE HUMAN SAYS: {chat}")
    parts += [
        ("EVENTS: " if chat is not None else "CONSULT: " if events and all(e.startswith("consult:") for e in events)
         else "ESCALATION: ") + ("; ".join(events) if events else "(none)"),
        "STANDING ORDERS: " + json.dumps(orders),
        "CHECKS: " + json.dumps({k: v for k, v in c.items() if k != "food"}),
        f"STATUS: {st.get('role')} XL{st.get('xlvl')} HP {st.get('hp')}/{st.get('hpmax')} "
        f"Pw {st.get('pw')}/{st.get('pwmax')} AC {st.get('ac')} Dlvl {st.get('dlvl')} T{st.get('turn')} "
        f"${st.get('gold')} {st.get('hunger', '')} {' '.join(st.get('conditions', []))}",
        "MESSAGES: " + (" | ".join(s.get("messages", [])) or "(none)"),
        "INVENTORY:\n" + "\n".join(inv),
    ]
    if ctx.get("kind") not in ("command", None):
        parts.append(f"PROMPT: {ctx.get('kind')} {ctx.get('prompt') or ''!r} choices={ctx.get('choices') or ''!r}"
                     + (f" items={[(i['key'], i['text']) for i in ctx.get('items', [])]}" if ctx.get("items") else ""))
    notable = []
    for cell in s.get("cells", []):
        if cell["kind"] == "you":
            continue
        tag = cell["kind"] + (" (peaceful)" if cell.get("peaceful") else "")
        notable.append(f"{tag}: {cell['name']} at ({cell['x']},{cell['y']})")
    parts.append("NOTABLE: " + ("; ".join(notable) or "(nothing)"))
    parts.append("MAP:\n" + "\n".join(rows))
    return "\n".join(parts)


JOURNAL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "journal.md")


def _journal() -> str:
    """The versioned lessons file, read fresh for every game."""
    try:
        with open(JOURNAL) as f:
            return "\n\nYOUR JOURNAL (lessons from past games; follow them):\n" + f.read()
    except OSError:
        return ""


class HaikuBrain:  # (ReplayBrain below stands in for it when rerunning a recorded game)
    name = "haiku"
    TIMEOUT_S = 60

    def __init__(self, model: str = "haiku", log_path: str | None = None, thinking_tokens: int = 0,
                 journal: bool = True) -> None:
        self.model = model
        self.journal = journal  # False: play without pilot/journal.md (the journal A/B check)
        # Thinking made each call 20-50s instead of 2-3s; checkpoints ask
        # dozens of times a game. Raise it if its decisions get worse.
        self.thinking_tokens = thinking_tokens
        self.fallback = RuleBrain()
        self.session_id = str(uuid.uuid4())
        self.started = False
        self.log = open(log_path, "a") if log_path else subprocess.DEVNULL
        self._proc: subprocess.Popen | None = None
        self._lines: queue.Queue = queue.Queue()
        self.last_error = ""

    # --- claude process (same pattern as the DnD game's claude_agent.py) ---

    def _start(self) -> None:
        routines = "\n".join(f"- {n}: {d}" for n, (_, d) in ROUTINES.items())
        if not self.started:  # A crashed first process may have claimed the id already.
            self.session_id = str(uuid.uuid4())
        cmd = [
            "claude", "-p",
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", self.model,
            "--system-prompt", SYSTEM.format(routines=routines) + (_journal() if self.journal else ""),
            "--tools", "",                 # No built-in tools: it only answers.
            "--strict-mcp-config",         # No MCP servers.
            "--setting-sources=",          # Keep the user's CLAUDE.md, hooks, plugins out.
            "--resume" if self.started else "--session-id", self.session_id,
        ]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self.log, text=True, cwd=tempfile.gettempdir(),
                                      env=dict(os.environ, MAX_THINKING_TOKENS=str(self.thinking_tokens)))
        self._lines = queue.Queue()
        threading.Thread(target=self._pump, args=(self._proc, self._lines), daemon=True).start()

    @staticmethod
    def _pump(proc, lines) -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def _ask(self, text: str) -> str | None:
        if self._proc is None or self._proc.poll() is not None:
            self._start()
        msg = {"type": "user", "message": {"role": "user", "content": text}}
        try:
            self._proc.stdin.write(json.dumps(msg) + "\n")
            self._proc.stdin.flush()
        except BrokenPipeError:
            self._proc = None
            return None
        deadline = time.time() + self.TIMEOUT_S
        while True:
            try:
                line = self._lines.get(timeout=max(0.0, deadline - time.time()))
            except queue.Empty:
                self._proc.kill()
                self._proc = None
                self.last_error = "timeout"
                return None
            if line is None:
                self._proc = None
                return None
            try:
                out = json.loads(line)
            except json.JSONDecodeError:
                continue
            if out.get("type") == "result":
                if out.get("is_error"):
                    self.last_error = out.get("result") or out.get("subtype", "error")
                    return None
                self.started = True
                return out.get("result", "")

    @staticmethod
    def _parse(text: str | None) -> Order | None:
        if not text:
            return None
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            d = json.loads(text[start:end + 1])
        except json.JSONDecodeError:
            return None
        routine = d.get("routine")
        if routine is not None and routine not in ROUTINES:
            return None
        return Order(routine, d.get("args") or {}, str(d.get("say") or ""),
                     d.get("orders") if isinstance(d.get("orders"), dict) else {})

    def close(self) -> None:
        if self._proc and self._proc.poll() is None:
            self._proc.kill()
        self._proc = None

    def decide(self, c: dict, events: list[str], s: dict, orders: dict) -> Order:
        order = self._parse(self._ask(_brief(c, events, s, None, orders)))
        if order is None:
            fb = self.fallback.decide(c, events, s, orders)
            fb.say = f"(brain unavailable{': ' + self.last_error if self.last_error else ''}; rules) {fb.say}"
            return fb
        return order

    def chat(self, text: str, c: dict, s: dict, orders: dict) -> Order:
        order = self._parse(self._ask(_brief(c, ["the human is talking to you"], s, text, orders)))
        return order or Order(None, say=f"(no answer from the brain{': ' + self.last_error if self.last_error else ''})")


class ReplayBrain(HaikuBrain):
    """Plays back a recorded game's brain answers in order, so a seeded
    game reruns exactly without calling the model."""

    def __init__(self, answers: list[dict]) -> None:
        super().__init__()
        self.answers = list(answers)

    def decide(self, c: dict, events: list[str], s: dict, orders: dict) -> Order:
        if not self.answers:
            return Order(None, say="(replay: no more recorded answers)")
        a = self.answers.pop(0)
        return Order(a["routine"], a["args"] or {}, a["say"], a["orders"] or {})


class QwenBrain(HaikuBrain):
    """The same brain on a local Ollama model (Qwen). One chat per game,
    history kept so context accumulates like Haiku's session; thinking
    off (it answered in about a second with it off, empty with it on)."""
    name = "qwen"
    URL = "http://127.0.0.1:11434/api/chat"
    TIMEOUT_S = 180  # Ollama serves one request at a time per model: parallel games queue.

    def __init__(self, model: str = "qwen3:8b", log_path: str | None = None, journal: bool = True) -> None:
        super().__init__(model, log_path, journal=journal)
        self._messages: list[dict] = []

    def _start(self) -> None:
        routines = "\n".join(f"- {n}: {d}" for n, (_, d) in ROUTINES.items())
        self._messages = [{"role": "system",
                           "content": SYSTEM.format(routines=routines) + (_journal() if self.journal else "")}]
        self.started = True

    def _ask(self, text: str) -> str | None:
        if not self._messages:
            self._start()
        self._messages.append({"role": "user", "content": text})
        body = {"model": self.model, "messages": self._messages[-41:] if len(self._messages) > 41 else self._messages,
                "stream": False, "think": False, "options": {"num_predict": 200, "temperature": 0.3}}
        if len(self._messages) > 41:  # Keep the system prompt when trimming old turns.
            body["messages"] = [self._messages[0]] + self._messages[-40:]
        req = urllib.request.Request(self.URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.TIMEOUT_S) as r:
                out = json.load(r)["message"].get("content", "")
        except Exception as e:  # timeout, server down, bad JSON: the rules answer instead
            self.last_error = f"{type(e).__name__}: {e}"[:80]
            self._messages.pop()
            return None
        self._messages.append({"role": "assistant", "content": out})
        return out

    def close(self) -> None:
        self._messages = []
