"""The engine: fully deterministic. It reads each snapshot, keeps the
checks (hungry? wounded? threatened?), handles mechanics (--More--,
pre-game screens, hard safety rules) and carries out routines (explore,
fight, eat, rest, go down, ...) one key at a time. It never makes choices:
the brain picks the routine, the engine executes it and says when it's
done, failed, or something changed that the brain should look at.
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
    pending_food: str = ""                        # letter to answer an eat prompt with
    pending_pray: bool = False                    # a prayer confirmation is expected
    last_door: tuple | None = None                # (dlvl, x, y) of the door we last tried to open


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
        is standing on it. A correction learned from a message (a 'closed
        door' that turned out broken) wins over the displayed glyph."""
        remembered = self.memory.features.get((self.dlvl, x, y), "") if self.memory else ""
        c = self.cells.get((x, y))
        if c and c["kind"] == "feature" and remembered != "broken door":
            return c["name"]
        return remembered

    def walkable(self, x: int, y: int) -> bool:
        c = self.cells.get((x, y))
        if c:
            if c["kind"] in ("object", "pet", "you"):
                return c["name"] != "boulder"
            if c["kind"] == "feature":
                return c["name"] in WALKABLE_FEATURES
            if c["kind"] in ("monster", "invisible"):
                return True  # They move; the routine deals with one in the way.
            return False  # traps
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
                    and not self.peaceful(cx, cy):
                yield (cx, cy), c["name"]

    def peaceful(self, x: int, y: int) -> bool:
        """Peaceful per the game (farlook), or one we declined to attack."""
        c = self.cells.get((x, y))
        return bool(c and c.get("peaceful")) or (
            self.memory is not None and (self.dlvl, x, y) in self.memory.peaceful)

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


def _step(v: View, memory: Memory, path: list[tuple], note: str):
    """First step along a path, minding whoever is standing in it."""
    nxt = path[0]
    c = v.cells.get(nxt)
    if c and c["kind"] in ("monster", "invisible"):
        if v.peaceful(*nxt):
            return "s", f"wait for the peaceful {c['name']} to move"
        return None, f"failed: a {c['name']} is in the way"
    return _toward(v, path), note


def _frontier(v: View, memory: Memory):
    """A walkable square we haven't stood on, next to blank map. Standing
    there reveals what's around it; solid rock stays blank forever, so
    squares already visited don't count."""
    def goal(x, y):
        return (v.dlvl, x, y) not in memory.visited and (v.dlvl, x, y) not in memory.blocked and any(
            v.ch(x + dx, y + dy) == " " and not v.cells.get((x + dx, y + dy))
            for dx, dy in DIRS.values())
    return goal



ORTHO = [(1, 0), (-1, 0), (0, 1), (0, -1)]
WALL = set("|-")


def wound_tier(hp: int, hpmax: int) -> str:
    if hp < max(6, hpmax // 7):
        return "critical"
    if hp * 3 < hpmax:
        return "badly hurt"
    if hp * 3 < hpmax * 2:
        return "hurt"
    return "fine"


# ---------- checks ----------

def checks(v: View, memory: Memory) -> dict:
    """What the brain decides on. Only facts the engine can compute."""
    st = v.status
    hp, hpmax, turn = st.get("hp", 0), st.get("hpmax", 1), st.get("turn", 0)
    adjacent, visible, dangerous = [], [], []
    if v.pos:
        for (x, y), c in v.cells.items():
            if c["kind"] != "monster" or v.peaceful(x, y):
                continue
            dist = max(abs(x - v.pos[0]), abs(y - v.pos[1]))
            entry = {"name": c["name"], "x": x, "y": y, "distance": dist}
            visible.append(entry)
            if dist == 1:
                adjacent.append(entry)
                if c["name"] in DONT_MELEE:
                    dangerous.append(c["name"])
    food = [{"letter": i["letter"], "text": i["text"]} for i in v.s.get("inventory", [])
            if i["class"] == "%"]
    safe_food = [f for f in food if any(k in f["text"] for k in SAFE_FOOD)
                 and "cursed" not in f["text"].replace("uncursed", "")]
    explored = v.pos is not None and bfs(v, _frontier(v, memory)) is None
    stairs = [xy for xy in ((x, y) for (d, x, y), n in memory.features.items()
                            if d == v.dlvl and n == "staircase down")]
    return {
        "hunger": st.get("hunger", ""),
        "hp": hp, "hpmax": hpmax, "wounded": wound_tier(hp, hpmax),
        "prayer_safe": (memory.last_pray_turn is None and turn > 300)
                       or (memory.last_pray_turn is not None and turn - memory.last_pray_turn > 1000),
        "adjacent_hostiles": adjacent,
        "visible_hostiles": visible,
        "dangerous_adjacent": dangerous,
        "food": food,
        "safe_food": safe_food,
        "level_explored": explored,
        "stairs_down": stairs[0] if stairs else None,
        "on_stairs_down": v.pos is not None and v.feature(*v.pos) == "staircase down",
        "gold_visible": any(c["kind"] == "object" and c["name"] == "gold piece" for c in v.cells.values()),
        "dlvl": v.dlvl, "turn": turn, "xlvl": st.get("xlvl"),
        "conditions": st.get("conditions", []),
    }


# ---------- mechanics: no decision involved ----------

def mechanics(v: View, memory: Memory) -> tuple[str | None, str] | None:
    """Keys for prompts that have exactly one right answer, or None."""
    if v.pos is None:  # before the game
        if v.kind == "menu" and any("start game" in i["text"] for i in v.ctx.get("items", [])):
            return "y", "accept the character"
        if v.kind == "key":
            return "y", "let the game pick race and alignment"
    if v.kind == "more" or (v.kind == "menu" and v.ctx.get("how") == "none"):
        return "\r", "dismiss --More--"
    if v.kind == "yn":
        prompt = v.ctx.get("prompt", "")
        if prompt.startswith("Really attack"):
            if memory.pending_fight:
                memory.peaceful.add((v.dlvl, *memory.pending_fight))
            return "n", "never attack a peaceful"
        if prompt.startswith("Are you sure you want to pray") and memory.pending_pray:
            memory.pending_pray = False
            return "y", "confirm the prayer"
        if prompt.startswith("What do you want to eat") and memory.pending_food:
            letter, memory.pending_food = memory.pending_food, ""
            return letter, "eat it"
        if "eat it?" in prompt and memory.pending_food:
            return "n", "not the corpse: the item from the pack"
    return None


# ---------- routines ----------
# Each step returns (keys, note) to keep going, or (None, "done: ...") /
# (None, "failed: ...") when it's finished.

DOOR_NOT_CLOSED = ("This door is broken", "This door is already open", "You see no door there",
                   "This doorway has no door")


def r_explore(v: View, memory: Memory, args: dict):
    if any(m.startswith(DOOR_NOT_CLOSED) for m in v.s.get("messages", [])) and memory.last_door:
        memory.features[memory.last_door] = "broken door"  # Our picture was stale.
    for dx, dy in ORTHO:
        d = (v.dlvl, v.pos[0] + dx, v.pos[1] + dy)
        if v.feature(*d[1:]) == "closed door" and d not in memory.dead_doors:
            if any("This door is locked" in m for m in v.s.get("messages", [])):
                memory.kicks[d] = memory.kicks.get(d, 0) + 1
                if memory.kicks[d] > 6:
                    memory.dead_doors.add(d)
                    continue
                return "\x04" + KEY_FOR[(dx, dy)], "kick the locked door"
            memory.last_door = d
            return "o" + KEY_FOR[(dx, dy)], "open the door"
    path = bfs(v, _frontier(v, memory))
    if path:
        return _step(v, memory, path, f"explore toward {path[-1]}")
    door = bfs(v, lambda x, y: any(v.feature(x + dx, y + dy) == "closed door"
                                   and (v.dlvl, x + dx, y + dy) not in memory.dead_doors
                                   for dx, dy in ORTHO))
    if door:
        return _step(v, memory, door, "walk to a closed door")
    return None, "done: nothing left to explore"


def r_search_walls(v: View, memory: Memory, args: dict):
    def spot(x, y, rounds):
        return memory.searched.get((v.dlvl, x, y), 0) < rounds and any(
            v.ch(x + dx, y + dy) in WALL or v.ch(x + dx, y + dy) == " " for dx, dy in DIRS.values())
    here = (v.dlvl, *v.pos)
    for rounds in (1, 2):
        if spot(*v.pos, rounds):
            memory.searched[here] = memory.searched.get(here, 0) + 1
            return "15s", "search the walls here"
        path = bfs(v, lambda x, y: spot(x, y, rounds))
        if path:
            return _step(v, memory, path, f"go search near {path[-1]}")
    return None, "failed: searched every wall twice"


def r_go_down(v: View, memory: Memory, args: dict):
    if args.setdefault("start_dlvl", v.dlvl) != v.dlvl:
        return None, "done: went down"
    if v.feature(*v.pos) == "staircase down":
        return ">", "take the stairs down"
    path = bfs(v, lambda x, y: v.feature(x, y) == "staircase down")
    if path:
        return _step(v, memory, path, "head for the stairs down")
    return None, "failed: no known way down"


def r_go_to(v: View, memory: Memory, args: dict):
    goal = (int(args["x"]), int(args["y"]))
    if v.pos == goal:
        return None, "done: arrived"
    path = bfs(v, lambda x, y: (x, y) == goal)
    return _step(v, memory, path, f"walk to {goal}") if path else (None, f"failed: no path to {goal}")


def r_fight(v: View, memory: Memory, args: dict):
    target = (args.get("target") or "").lower()
    for (mx, my), name in v.hostiles_adjacent(memory):
        if target and target not in name:
            continue
        if name in DONT_MELEE and not args.get("even_if_dangerous"):
            return None, f"failed: {name} is on the don't-melee list"
        memory.pending_fight = (mx, my)
        return "F" + KEY_FOR[(mx - v.pos[0], my - v.pos[1])], f"attack the {name}"
    memory.pending_fight = None
    # Close in on the named (or nearest) visible hostile, if any.
    wanted = [(x, y) for (x, y), c in v.cells.items() if c["kind"] == "monster"
              and not v.peaceful(x, y) and (not target or target in c["name"])]
    if wanted:
        path = bfs(v, lambda x, y: any(max(abs(x - a), abs(y - b)) == 1 for a, b in wanted))
        if path:
            return _step(v, memory, path, "close in")
    return None, "done: nothing left to fight"


def r_eat(v: View, memory: Memory, args: dict):
    if args.get("sent"):
        return None, "done: ate"
    letter = args.get("letter") or next((f["letter"] for f in checks(v, memory)["safe_food"]), "")
    if not letter:
        return None, "failed: no safe food in the pack"
    memory.pending_food = letter
    args["sent"] = True
    return "e", f"eat item {letter}"


def r_rest(v: View, memory: Memory, args: dict):
    st = v.status
    goal = int(args.get("until_hp") or st.get("hpmax", 1))
    if st.get("hp", 0) >= goal:
        return None, "done: rested"
    if v.monsters_visible():
        return None, "failed: something's in view"
    return "20s", f"rest (HP {st.get('hp')}/{goal})"


def r_pray(v: View, memory: Memory, args: dict):
    if args.get("sent"):
        return None, "done: prayed"
    args["sent"] = True
    memory.pending_pray = True
    memory.last_pray_turn = v.status.get("turn", 0)
    return "#pray\n", "pray"


def r_pickup_gold(v: View, memory: Memory, args: dict):
    path = bfs(v, lambda x, y: (c := v.cells.get((x, y))) is not None
               and c["kind"] == "object" and c["name"] == "gold piece")
    return _step(v, memory, path, "walk to the gold") if path else (None, "done: no gold in view")


def r_pick_up(v: View, memory: Memory, args: dict):
    goal = (int(args["x"]), int(args["y"])) if "x" in args else v.pos
    if args.get("sent"):
        return None, "done: picked up"
    if v.pos == goal:
        args["sent"] = True
        return ",", "pick it up"
    path = bfs(v, lambda x, y: (x, y) == goal)
    return _step(v, memory, path, f"walk to the item at {goal}") if path else (None, f"failed: no path to {goal}")


def r_keys(v: View, memory: Memory, args: dict):
    if args.get("sent"):
        return None, "done: sent"
    args["sent"] = True
    return args.get("keys", ""), f"press {args.get('keys', '')!r}"


ROUTINES = {
    "explore": (r_explore, "walk to unexplored areas, opening (or kicking) doors"),
    "search_walls": (r_search_walls, "search along the walls for hidden doors"),
    "go_down": (r_go_down, "walk to the known stairs down and descend"),
    "go_to": (r_go_to, "walk to map square {x, y}"),
    "fight": (r_fight, "melee adjacent hostiles, or close in; {target: optional name}"),
    "eat": (r_eat, "eat food from the pack; {letter: optional inventory letter}"),
    "rest": (r_rest, "search in place to heal; {until_hp: optional}"),
    "pray": (r_pray, "pray to your god (only safe about once per 1000 turns)"),
    "pickup_gold": (r_pickup_gold, "walk onto visible gold (autopickup takes it)"),
    "pick_up": (r_pick_up, "walk to an item and pick it up; {x, y} (default: here). A menu comes back to you as a prompt"),
    "keys": (r_keys, "send raw keys once, e.g. to answer a prompt; {keys}"),
}


class Engine:
    """Runs the current routine one key at a time and reports what the
    brain needs to hear about."""

    def __init__(self) -> None:
        self.memory = Memory()
        self.routine: str | None = None
        self.args: dict = {}
        self.last_checks: dict = {}
        self.note = ""

    def order(self, routine: str, args: dict | None = None) -> None:
        if routine not in ROUTINES:
            raise ValueError(f"unknown routine {routine!r}")
        self.routine, self.args = routine, dict(args or {})

    def step(self, s: dict) -> tuple[str | None, list[str]]:
        """Keys to send for this snapshot (or None), and events for the
        brain (empty when nothing needs deciding)."""
        v = View(s, self.memory)
        for (x, y), c in v.cells.items():
            if c["kind"] == "feature":
                self.memory.features[(v.dlvl, x, y)] = c["name"]
        if v.pos:
            self.memory.visited.add((v.dlvl, *v.pos))

        mech = mechanics(v, self.memory)
        if mech:
            self.note = mech[1]
            return mech[0], []
        if v.kind != "command":
            if self.routine == "keys":  # The brain's answer to this prompt.
                keys, self.note = r_keys(v, self.memory, self.args)
                self.routine = None
                if keys:
                    return keys, []
            return None, [f"prompt: {v.kind} {v.ctx.get('prompt') or ''!r} choices {v.ctx.get('choices') or ''!r}"]

        now = checks(v, self.memory)
        events = self._changes(self.last_checks, now)
        self.last_checks = now
        if events or self.routine is None:
            return None, events or ["idle: no routine"]

        fn, _ = ROUTINES[self.routine]
        keys, note = fn(v, self.memory, self.args)
        self.note = note
        if keys is None:
            finished = f"{self.routine} {note}"
            self.routine = None
            return None, [finished]
        return self._stuck_guard(v, keys, note)

    def _stuck_guard(self, v: View, keys: str, note: str):
        """The same keys five times with the turn and position unchanged
        means they do nothing here: block the target and tell the brain."""
        here = (keys, v.status.get("turn"), v.pos)
        m = self.memory
        m.stuck = m.stuck + 1 if here == m.last_move else 0
        m.last_move = here
        if m.stuck >= 5:
            m.stuck = 0
            d = DIRS.get(keys[-1:]) if keys else None
            if d:
                m.blocked.add((v.dlvl, v.pos[0] + d[0], v.pos[1] + d[1]))
                if keys[0] in "o\x04":
                    m.dead_doors.add((v.dlvl, v.pos[0] + d[0], v.pos[1] + d[1]))
            routine, self.routine = self.routine, None
            return None, [f"{routine} stuck: {keys!r} changes nothing here"]
        return keys, []

    @staticmethod
    def _changes(before: dict, now: dict) -> list[str]:
        """Check changes worth waking the brain for."""
        if not before:
            return ["game state available"]
        ev = []
        if now["hunger"] != before["hunger"]:
            ev.append(f"hunger now {now['hunger'] or 'not hungry'}")
        order = ["fine", "hurt", "badly hurt", "critical"]
        if order.index(now["wounded"]) > order.index(before["wounded"]):
            ev.append(f"now {now['wounded']} (HP {now['hp']}/{now['hpmax']})")
        new = {m["name"] for m in now["visible_hostiles"]} - {m["name"] for m in before["visible_hostiles"]}
        if new:
            ev.append("hostile in view: " + ", ".join(sorted(new)))
        if now["dangerous_adjacent"] and not before["dangerous_adjacent"]:
            ev.append("dangerous monster adjacent: " + ", ".join(now["dangerous_adjacent"]))
        if now["dlvl"] != before["dlvl"]:
            ev.append(f"arrived on dungeon level {now['dlvl']}")
        if now["conditions"] != before["conditions"]:
            ev.append("conditions now " + (", ".join(now["conditions"]) or "none"))
        return ev
