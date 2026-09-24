"""Deterministic autopilot: everything with a known right answer.

`decide(state, memory)` returns `(keys, reason)` to send, or `(None, why)`
when the situation needs judgment (the LLM or the human). It never guesses:
unknown prompts, unknown items and dangerous monsters are deferred.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

# vi-keys: direction -> (dx, dy)
DIRS = {"h": (-1, 0), "l": (1, 0), "k": (0, -1), "j": (0, 1),
        "y": (-1, -1), "u": (1, -1), "b": (-1, 1), "n": (1, 1)}
KEY_FOR = {v: k for k, v in DIRS.items()}

# Terrain the map row shows directly.
FLOOR_CHARS = set(".#<>_{")
# Features (from `cells`) you can stand on; doors are special-cased.
WALKABLE_FEATURES = {"doorway", "open door", "broken door", "staircase up", "staircase down",
                     "ladder up", "ladder down", "altar", "fountain", "sink", "grave", "throne",
                     "ice", "lowered drawbridge", "dark part of a room"}
NO_DIAGONAL = {"open door"}  # NetHack: no diagonal moves into or out of a doorway with a door.

# Monsters never to melee (passive or on-death effects).
DONT_MELEE = {"floating eye", "cockatrice", "chickatrice", "gas spore", "acid blob",
              "blue jelly", "spotted jelly", "ochre jelly", "green mold", "brown mold",
              "yellow mold", "red mold"}
SAFE_FOOD = ("food ration", "cram ration", "lembas wafer", "fortune cookie", "apple", "orange",
             "carrot", "melon", "banana", "pear", "slime mold", "C-ration", "K-ration",
             "pancake", "cream pie", "candy bar", "egg")
HUNGRY = {"Hungry", "Weak", "Fainting", "Fainted"}


@dataclass
class Memory:
    """What the pilot remembers between states."""
    last_pray_turn: int | None = None
    searched: dict = field(default_factory=dict)  # (dlvl, x, y) -> times searched there
    peaceful: set = field(default_factory=set)    # (dlvl, x, y) of monsters we declined to attack
    pending_fight: tuple | None = None            # square we just tried to fight
    visited: set = field(default_factory=set)     # (dlvl, x, y) squares stood on
    kicks: dict = field(default_factory=dict)     # (dlvl, x, y) of a locked door -> kicks
    dead_doors: set = field(default_factory=set)  # doors we gave up on
    features: dict = field(default_factory=dict)  # (dlvl, x, y) -> feature name last seen there
    blocked: set = field(default_factory=set)     # (dlvl, x, y) targets that didn't work out
    last_move: tuple = ()                         # (keys, turn, pos) of the last move sent
    stuck: int = 0                                # repeats of a move that changed nothing


class View:
    """Convenience over one state snapshot."""

    def __init__(self, s: dict, memory: Memory | None = None) -> None:
        self.s = s
        self.memory = memory
        self.ctx = s["context"]
        self.kind = self.ctx["kind"]
        self.status = s.get("status", {})
        self.map = s.get("map", [])
        self.pos = (s["player"]["x"], s["player"]["y"]) if "player" in s else None
        self.cells = {(c["x"], c["y"]): c for c in s.get("cells", [])}
        self.dlvl = self.status.get("dlvl", 0)

    def ch(self, x: int, y: int) -> str:
        if 0 <= y < len(self.map) and 1 <= x <= len(self.map[y]):
            return self.map[y][x - 1]
        return " "

    def feature(self, x: int, y: int) -> str:
        """The terrain feature here, remembered if something (like you)
        is standing on it."""
        c = self.cells.get((x, y))
        if c and c["kind"] == "feature":
            return c["name"]
        return self.memory.features.get((self.dlvl, x, y), "") if self.memory else ""

    def walkable(self, x: int, y: int) -> bool:
        c = self.cells.get((x, y))
        if c:
            if c["kind"] in ("object", "pet", "you"):
                return c["name"] != "boulder"
            if c["kind"] == "feature":
                return c["name"] in WALKABLE_FEATURES
            return False  # monsters, traps, invisible
        return self.ch(x, y) in FLOOR_CHARS

    def step_ok(self, a: tuple, b: tuple) -> bool:
        if not self.walkable(*b):
            return False
        diagonal = a[0] != b[0] and a[1] != b[1]
        return not (diagonal and (self.feature(*a) in NO_DIAGONAL or self.feature(*b) in NO_DIAGONAL))

    def hostiles_adjacent(self, memory: Memory):
        x, y = self.pos
        for (cx, cy), c in self.cells.items():
            if c["kind"] == "monster" and max(abs(cx - x), abs(cy - y)) == 1 \
                    and (self.dlvl, cx, cy) not in memory.peaceful:
                yield (cx, cy), c["name"]

    def monsters_visible(self) -> bool:
        return any(c["kind"] == "monster" for c in self.cells.values())

    def food_letter(self) -> str | None:
        for item in self.s.get("inventory", []):
            if item["class"] == "%" and any(f in item["text"] for f in SAFE_FOOD) \
                    and "cursed" not in item["text"].replace("uncursed", ""):
                return item["letter"]
        return None


def bfs(v: View, goal) -> list[tuple] | None:
    """Shortest walkable path from the player to the first square where
    goal(x, y) is true. Returns the path (excluding the start) or None."""
    start = v.pos
    prev = {start: None}
    q = deque([start])
    while q:
        cur = q.popleft()
        if cur != start and goal(*cur):
            path = []
            while cur != start:
                path.append(cur)
                cur = prev[cur]
            return path[::-1]
        for dx, dy in DIRS.values():
            nxt = (cur[0] + dx, cur[1] + dy)
            if nxt not in prev and v.step_ok(cur, nxt) \
                    and not (v.memory and (v.dlvl, *nxt) in v.memory.blocked):
                prev[nxt] = cur
                q.append(nxt)
    return None


def _toward(v: View, path: list[tuple]) -> str:
    x, y = v.pos
    nx, ny = path[0]
    return KEY_FOR[(nx - x, ny - y)]


def _frontier(v: View, memory: Memory):
    """A walkable square we haven't stood on, next to blank map. Standing
    there reveals what's around it; solid rock stays blank forever, so
    squares already visited don't count."""
    def goal(x, y):
        return (v.dlvl, x, y) not in memory.visited and (v.dlvl, x, y) not in memory.blocked and any(
            v.ch(x + dx, y + dy) == " " and not v.cells.get((x + dx, y + dy))
            for dx, dy in DIRS.values())
    return goal


def decide(s: dict, memory: Memory) -> tuple[str | None, str]:
    v = View(s, memory)
    for (x, y), c in v.cells.items():
        if c["kind"] == "feature":
            memory.features[(v.dlvl, x, y)] = c["name"]
    keys, reason = _decide(v, s, memory)
    # Stuck guard: a move that leaves the turn and position unchanged five
    # times running marks its target blocked, so exploring picks another.
    if v.kind == "command" and keys and keys in DIRS:
        here = (keys, v.status.get("turn"), v.pos)
        memory.stuck = memory.stuck + 1 if here == memory.last_move else 0
        memory.last_move = here
        if memory.stuck >= 5:
            dx, dy = DIRS[keys]
            memory.blocked.add((v.dlvl, v.pos[0] + dx, v.pos[1] + dy))
            memory.stuck = 0
            return decide(s, memory) if memory.blocked else (None, "stuck")
    return keys, reason


def _decide(v: "View", s: dict, memory: Memory) -> tuple[str | None, str]:

    # --- before the game: accept the offered character ---------------
    if v.pos is None:
        if v.kind == "menu" and any("start game" in i["text"] for i in v.ctx.get("items", [])):
            return "y", "accept the character"
        if v.kind == "key":
            return "y", "let the game pick race and alignment"

    # --- prompts ------------------------------------------------------
    if v.kind == "more" or (v.kind == "menu" and v.ctx.get("how") == "none"):
        return "\r", "dismiss --More--"
    if v.kind == "yn":
        prompt = v.ctx.get("prompt", "")
        if prompt.startswith("Really attack"):
            if memory.pending_fight:
                memory.peaceful.add((v.dlvl, *memory.pending_fight))
            return "n", "never attack a peaceful"
        if prompt.startswith("Are you sure you want to pray"):
            return "y", "confirm prayer"
        if prompt.startswith("What do you want to eat"):
            letter = v.food_letter()
            return (letter, "eat known-safe food") if letter else ("\x1b", "no safe food")
        if "eat it?" in prompt:  # corpse on the floor
            return "n", "don't eat unknown corpses"
        return None, f"unfamiliar question: {prompt!r}"
    if v.kind != "command" or v.pos is None:
        return None, f"unfamiliar prompt ({v.kind})"

    memory.visited.add((v.dlvl, *v.pos))
    st = v.status
    hp, hpmax, turn = st.get("hp", 0), st.get("hpmax", 1), st.get("turn", 0)

    # --- survival -----------------------------------------------------
    if hp < max(6, hpmax // 7):
        can_pray = (memory.last_pray_turn is None and turn > 300) or \
                   (memory.last_pray_turn is not None and turn - memory.last_pray_turn > 1000)
        if can_pray:
            memory.last_pray_turn = turn
            return "#pray\n", f"HP {hp}/{hpmax}: pray (timeout should be safe)"
        return None, f"HP {hp}/{hpmax} and prayer isn't safe yet"
    if st.get("hunger") in HUNGRY:
        if v.food_letter():
            return "e", f"{st['hunger']}: eat"
        return None, f"{st['hunger']} and no known-safe food"

    # --- fighting -----------------------------------------------------
    for (mx, my), name in v.hostiles_adjacent(memory):
        if name in DONT_MELEE:
            return None, f"{name} adjacent: don't melee it"
        memory.pending_fight = (mx, my)
        return "F" + KEY_FOR[(mx - v.pos[0], my - v.pos[1])], f"fight {name}"
    memory.pending_fight = None

    # --- recover ------------------------------------------------------
    if hp < hpmax * 2 // 3 and not v.monsters_visible():
        return "20s", f"HP {hp}/{hpmax}: rest"

    # --- gold ---------------------------------------------------------
    gold = bfs(v, lambda x, y: (c := v.cells.get((x, y))) is not None
               and c["kind"] == "object" and c["name"] == "gold piece"
               and (v.dlvl, x, y) not in memory.blocked)
    if gold and not v.monsters_visible():
        return _toward(v, gold), "pick up gold"

    # --- explore ------------------------------------------------------
    path = bfs(v, _frontier(v, memory))
    if path:
        nxt = path[0]
        return _toward(v, path), f"explore toward {path[-1]}"
    # closed doors are frontiers too; they only open orthogonally
    ORTHO = [(1, 0), (-1, 0), (0, 1), (0, -1)]
    for dx, dy in ORTHO:
        d = (v.dlvl, v.pos[0] + dx, v.pos[1] + dy)
        if v.feature(*d[1:]) == "closed door" and d not in memory.dead_doors:
            if any("This door is locked" in m for m in s.get("messages", [])):
                memory.kicks[d] = memory.kicks.get(d, 0) + 1
                if memory.kicks[d] > 6:
                    memory.dead_doors.add(d)
                    continue
                return "\x04" + KEY_FOR[(dx, dy)], "door is locked: kick it"
            return "o" + KEY_FOR[(dx, dy)], "open door"
    door = bfs(v, lambda x, y: any(v.feature(x + dx, y + dy) == "closed door"
                                   and (v.dlvl, x + dx, y + dy) not in memory.dead_doors
                                   for dx, dy in ORTHO))
    if door:
        return _toward(v, door), "walk to a closed door"
    here = (v.dlvl, *v.pos)

    # --- level done: go down -----------------------------------------
    if v.feature(*v.pos) == "staircase down":
        return ">", "level explored: descend"
    stairs = bfs(v, lambda x, y: v.feature(x, y) == "staircase down")
    if stairs:
        return _toward(v, stairs), "level explored: head for the stairs down"

    # --- search for hidden passages ------------------------------------
    # Walk the walls: search 15 turns at each wall-side square, twice over.
    WALL = set("|-")

    def search_spot(x, y, rounds):
        return memory.searched.get((v.dlvl, x, y), 0) < rounds and any(
            v.ch(x + dx, y + dy) in WALL or v.ch(x + dx, y + dy) == " " for dx, dy in DIRS.values())

    for rounds in (1, 2):
        if search_spot(*v.pos, rounds):
            memory.searched[here] = memory.searched.get(here, 0) + 1
            return "15s", "nothing left to explore: search the walls for a hidden door"
        spot = bfs(v, lambda x, y: search_spot(x, y, rounds))
        if spot:
            return _toward(v, spot), f"go search the walls near {spot[-1]}"
    return None, "explored and searched every wall twice, no stairs: need a plan"
