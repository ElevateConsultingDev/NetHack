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


class RuleBrain:
    """Fixed priorities; the stand-in until (or when) Haiku isn't available."""

    name = "rules"

    def decide(self, c: dict, events: list[str], s: dict) -> Order:
        if any(e.startswith("prompt:") for e in events):
            return Order(None, say="unfamiliar prompt; over to you")
        failed = {e.split()[0] for e in events if " failed:" in e or " stuck:" in e}
        order = self._pick(c, events)
        if order.routine in failed:
            return Order(None, say=f"{order.routine} just failed ({'; '.join(events)}); your call")
        return order

    def _pick(self, c: dict, events: list[str]) -> Order:
        if c["wounded"] == "critical":
            if c["prayer_safe"]:
                return Order("pray", say="nearly dead and prayer should be safe")
            return Order(None, say="nearly dead and prayer isn't safe; your call")
        if c["dangerous_adjacent"]:
            return Order(None, say=f"{', '.join(c['dangerous_adjacent'])} next to me; not touching it")
        if c["adjacent_hostiles"]:
            return Order("fight", say=f"fighting the {c['adjacent_hostiles'][0]['name']}")
        if c["hunger"] in ("Hungry", "Weak", "Fainting"):
            if c["safe_food"]:
                return Order("eat", {"letter": c["safe_food"][0]["letter"]}, say=f"{c['hunger']}: eating")
            return Order(None, say=f"{c['hunger']} and no safe food; your call")
        if c["wounded"] in ("hurt", "badly hurt") and not c["visible_hostiles"]:
            return Order("rest", say="resting up")
        if c["gold_visible"] and not c["visible_hostiles"]:
            return Order("pickup_gold")
        if not c["level_explored"]:
            return Order("explore")
        if c["stairs_down"]:
            return Order("go_down", say="level done, heading down")
        if not any(e.startswith("search_walls failed") for e in events):
            return Order("search_walls", say="no way on; searching for hidden doors")
        return Order(None, say="explored, searched, no stairs; your call")

    def chat(self, text: str, c: dict, s: dict) -> Order:
        return Order(None, say="(rule brain: I can't chat; start with --brain haiku)")


SYSTEM = """You are the brain of a NetHack 3.6 autopilot, playing for a human who watches and chats with you.

An engine does everything deterministic. You never press movement keys yourself: you pick a ROUTINE and the engine carries it out step by step until it's done, fails, or something changes, then asks you again. The engine also handles --More--, pre-game screens, prayer confirmation, and never attacks peacefuls.

Routines (name: what it does; args):
{routines}

Each time you're asked you get EVENTS (why you're being asked), CHECKS (hunger, wounds, threats, food, exploration, stairs), STATUS, recent MESSAGES, INVENTORY, the PROMPT if the game is asking something, and the MAP (x = column + 1 of each row, y = row index; @ is you).

Reply with exactly ONE line of JSON and nothing else:
{{"routine": "<name or null>", "args": {{...}}, "say": "<one short sentence to the human>"}}
- routine null means: when asked for a decision, wait for the human; when the human is only chatting, keep the current routine.
- To answer a game prompt, use routine "keys" with the exact keys (e.g. "y", "n", an inventory letter, "\\u001b" for Escape).
- Prefer the big routines: explore until it says done, then search_walls if there are no stairs down, then go_down. Use go_to only for a specific named thing, and if the same go_to fails twice, drop it.
- NOTABLE lists everything named on the map with coordinates. Map symbols like ? ! % [ ) = are just items on the floor (scroll, potion, food, armor, weapon, ring); they are never required to find stairs.
- Play solid, conservative NetHack: don't melee floating eyes or cockatrices, eat when Hungry, pray when HP is critically low and prayer is safe (about once per 1000 turns), rest when hurt and alone, explore before descending, don't eat unknown or old corpses, keep your pet alive.
- When the human gives an order, follow it unless it's clearly suicidal, and say so if you refuse.
"""


def _brief(c: dict, events: list[str], s: dict, chat: str | None) -> str:
    st = s.get("status", {})
    ctx = s.get("context", {})
    rows = [f"{y:2d} {row.rstrip()}" for y, row in enumerate(s.get("map", [])) if row.strip()]
    inv = [f"{i['letter']} - {i['text']}" for i in s.get("inventory", [])]
    parts = []
    if chat is not None:
        parts.append(f"THE HUMAN SAYS: {chat}")
    parts += [
        "EVENTS: " + ("; ".join(events) if events else "(none)"),
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


class HaikuBrain:
    name = "haiku"
    TIMEOUT_S = 60

    def __init__(self, model: str = "haiku", log_path: str | None = None) -> None:
        self.model = model
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
        cmd = [
            "claude", "-p",
            "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
            "--model", self.model,
            "--system-prompt", SYSTEM.format(routines=routines),
            "--tools", "",                 # No built-in tools: it only answers.
            "--strict-mcp-config",         # No MCP servers.
            "--setting-sources=",          # Keep the user's CLAUDE.md, hooks, plugins out.
            "--resume" if self.started else "--session-id", self.session_id,
        ]
        self._proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                      stderr=self.log, text=True, cwd=tempfile.gettempdir())
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
        return Order(routine, d.get("args") or {}, str(d.get("say") or ""))

    def decide(self, c: dict, events: list[str], s: dict) -> Order:
        order = self._parse(self._ask(_brief(c, events, s, None)))
        if order is None:
            fb = self.fallback.decide(c, events, s)
            fb.say = f"(brain unavailable{': ' + self.last_error if self.last_error else ''}; rules) {fb.say}"
            return fb
        return order

    def chat(self, text: str, c: dict, s: dict) -> Order:
        order = self._parse(self._ask(_brief(c, ["the human is talking to you"], s, text)))
        return order or Order(None, say=f"(no answer from the brain{': ' + self.last_error if self.last_error else ''})")
