"""The engine: fully deterministic. It reads each snapshot, keeps the
checks (hungry? wounded? threatened?), handles mechanics (--More--,
pre-game screens, hard safety rules) and carries out routines (explore,
fight, eat, rest, go down, ...) one key at a time. It never makes choices:
the brain picks the routine, the engine executes it and says when it's
done, failed, or something changed that the brain should look at.
"""

from __future__ import annotations

import re
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
DONT_MELEE = {"floating eye", "cockatrice", "chickatrice",
              "blue jelly", "spotted jelly", "ochre jelly", "green mold", "brown mold",
              "yellow mold", "red mold"}
# Dangerous to stand next to, not just to hit: worth waking the brain for.
DANGEROUS_NEAR = {"cockatrice", "chickatrice"}
SAFE_FOOD = ("food ration", "cram ration", "lembas wafer", "fortune cookie", "apple", "orange",
             "carrot", "melon", "banana", "pear", "slime mold", "C-ration", "K-ration",
             "pancake", "cream pie", "candy bar", "egg")
# pray.c: pleased() opens with "You feel that <god> is <mood>." (Hallu
# moods in the second half). Anything from angrygods() or prayer_done()'s
# failures means the god is now angry.
PRAYER_OK = re.compile(r"You feel that .* is (well-pleased|pleased|satisfied|pleased as punch|ticklish|full)\.")
PRAYER_FAILED = ("You feel that", "The voice of", "Thou ", '"Thou', "You feel like you are falling apart",
                 "Since you are in Gehennom")
# Messages that mean Luck dropped, and turns until it decays back to 0.
LUCK_PENALTIES = {"You murderer!": 1200, "You cannibal!": 3000, "That's bad luck!": 1200,
                  "You feel guilty": 3000}
HUNGRY = {"Hungry", "Weak", "Fainting", "Fainted"}

# Corpses safe for an ordinary character when fresh (NetHack 3.6). Leaves out
# anything poisonous, acidic-and-risky, were-, domestic (aggravate), stunning,
# hallucinogenic, petrifying, polymorphing, teleport-granting, mimicking,
# pre-rotted (zombies, mummies), and humanoids that are someone's kin.
SAFE_CORPSES = {
    "newt", "jackal", "fox", "coyote", "sewer rat", "giant rat", "rock mole", "woodchuck",
    "gecko", "iguana", "baby crocodile", "crocodile", "lizard", "lichen", "rothe", "dingo",
    "wolf", "giant beetle", "floating eye", "acid blob", "gnome", "gnome lord", "gnome king",
    "hill orc", "Mordor orc", "Uruk-hai", "orc shaman", "goblin", "hobgoblin", "hill giant",
    "pony", "horse", "warhorse", "jaguar", "lynx", "panther",
}
NEVER_ROTS = {"lichen", "lizard"}
FRESH_TURNS = 30
RACE_KIN = {"gnome": ("gnome",), "orc": ("orc", "Uruk-hai"), "dwarf": ("dwarf",),
            "elf": ("elf",), "human": ("human",)}


@dataclass
class Memory:
    """What the pilot remembers between states."""
    last_pray_turn: int | None = None
    prayer_broken: bool = False                   # a prayer failed: the god is angry, never pray again
    luck_bad_until: int = 0                       # turn a known Luck penalty has decayed by
    feverish: bool = False                        # lycanthropy (a major trouble prayer cures)
    searched: dict = field(default_factory=dict)  # (dlvl, x, y) -> times searched there
    peaceful: dict = field(default_factory=dict)  # (dlvl, x, y) -> turn we declined to attack there
    waits: dict = field(default_factory=dict)     # (dlvl, x, y) -> turns spent waiting for it to clear
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
    pending_item: str = ""                        # letter for the next "What do you want to ..." prompt
    searched_out: set = field(default_factory=set)  # dlvls where searching the walls found nothing
    looted: set = field(default_factory=set)      # (dlvl, x, y) squares we already picked over
    loot_classes: str = ""                        # classes to take from a pickup menu
    avoid: set = field(default_factory=set)       # monster names never to melee (from the orders)
    engraving: bool = False                       # an Elbereth engraving is in progress
    corridors: set = field(default_factory=set)   # (dlvl, x, y) corridor squares seen
    kills: dict = field(default_factory=dict)     # (dlvl, x, y) -> (monster, turn) where we killed it
    eating_corpse: bool = False                   # an 'e' for a floor corpse is in progress
    declined_corpse: bool = False                 # we said no to a floor corpse just now
    stats: dict = field(default_factory=dict)     # counters for measuring the pilot
    retrieve: set = field(default_factory=set)    # names of things we threw, to pick back up
    probed: set = field(default_factory=set)      # (dlvl, x, y) blank squares we've tried to step into


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
                # They move, so plan through them; the routine deals with one
                # in the way. Except ones we must never bump into.
                return not (self.memory and c["name"] in self.memory.avoid)
            return False  # traps
        return self.ch(x, y) in FLOOR_CHARS

    def step_ok(self, a: tuple, b: tuple) -> bool:
        c = self.cells.get(b)
        if c and c["kind"] == "object" and c["name"] == "boulder":
            # Walking into a boulder pushes it: fine if the square beyond is open.
            beyond = (2 * b[0] - a[0], 2 * b[1] - a[1])
            bc = self.cells.get(beyond)
            return (self.ch(*beyond) in FLOOR_CHARS and not (bc and bc["kind"] in ("monster", "object"))
                    and not (a[0] != b[0] and a[1] != b[1]))  # No pushing diagonally.
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
        if c and "peaceful" in c:
            return bool(c["peaceful"])  # The game's own answer (what farlook shows).
        when = self.memory.peaceful.get((self.dlvl, x, y)) if self.memory else None
        return when is not None and self.status.get("turn", 0) - when < 10  # Just declined one here.

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
    if c and c["kind"] == "invisible":
        # Hit it: that fights the unseen thing, or clears a stale marker.
        return "F" + KEY_FOR[(nxt[0] - v.pos[0], nxt[1] - v.pos[1])], "attack the unseen thing in the way"
    if c and c["kind"] == "monster":
        if v.peaceful(*nxt):
            spot = (v.dlvl, *nxt)
            memory.waits[spot] = memory.waits.get(spot, 0) + 1
            if memory.waits[spot] > 10:  # It isn't moving: go another way.
                memory.blocked.add(spot)
                memory.waits[spot] = 0
                return None, f"failed: the peaceful {c['name']} won't move; routing around it"
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
    if hp <= 5 or hp * 7 <= hpmax:  # pray.c critically_low_hp: major trouble
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
            entry = {"name": c["name"], "x": x, "y": y, "distance": dist,
                     "difficulty": c.get("difficulty", 0)}
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
    # Major trouble (pray.c in_trouble) is what a prayer fixes with the
    # timeout under 200. Hunger counts only when there's no food to eat.
    conds = set(st.get("conditions", []))
    trouble = ([c for c in ("Stone", "Slime", "Strngl", "Sick") if c in conds]
               + (["critical HP"] if wound_tier(hp, hpmax) == "critical" else [])
               + ([st.get("hunger", "").strip()] if st.get("hunger", "").strip() in ("Weak", "Fainting", "Fainted")
                  and not safe_food else [])
               + (["lycanthropy"] if memory.feverish else []))
    stairs = [xy for xy in ((x, y) for (d, x, y), n in memory.features.items()
                            if d == v.dlvl and n == "staircase down")]
    return {
        "hunger": st.get("hunger", "").strip(),
        "hp": hp, "hpmax": hpmax, "wounded": wound_tier(hp, hpmax),
        # Major trouble needs the prayer timeout at 200 or less. It starts at
        # 300 and is rnz(350) after a prayer, over 1000 about 8% of the time.
        # A failed prayer angers the god for good; bad Luck fails it too.
        "prayer_safe": not memory.prayer_broken and turn >= memory.luck_bad_until
                       and (turn >= 300 if memory.last_pray_turn is None
                            else turn - memory.last_pray_turn >= 1000),
        "major_trouble": trouble,
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
    if v.kind == "more" or (v.kind == "menu" and v.ctx.get("how") == "none") \
            or (v.ctx.get("more") and v.kind not in ("menu",)):
        # A --More-- can be showing while a prompt (getlin, y/n) is already
        # pending behind it: dismiss it first, or typed answers are eaten.
        return "\r", "dismiss --More--"
    if v.kind == "menu" and v.ctx.get("how") == "any" and memory.loot_classes:
        return _pick_from_menu(v, memory), "take the wanted items"
    if memory.engraving:
        prompt = v.ctx.get("prompt", "")
        if v.kind == "yn" and prompt.startswith("What do you want to write with"):
            return "-", "write with a fingertip"
        if v.kind == "yn" and "add to the current engraving" in prompt:
            return "n", "write fresh"
        if v.kind == "getlin" and "write" in prompt:
            memory.engraving = False
            return "Elbereth\r", "write Elbereth"
    if v.kind == "yn":
        prompt = v.ctx.get("prompt", "")
        if "trouble lifting" in prompt or "Continue?" in prompt and memory.loot_classes:
            return "n", "too heavy: leave it"
        if prompt.startswith(("Do you want your possessions identified", "Do you want to see")):
            return "n", "game over: skip the end-of-game lists"
        if prompt.startswith("Really attack"):
            if memory.pending_fight:
                memory.peaceful[(v.dlvl, *memory.pending_fight)] = v.status.get("turn", 0)
            return "n", "never attack a peaceful"
        if prompt.startswith("Are you sure you want to pray") and memory.pending_pray:
            memory.pending_pray = False
            return "y", "confirm the prayer"
        if prompt.startswith("What do you want to eat") and memory.pending_food:
            letter, memory.pending_food = memory.pending_food, ""
            return letter, "eat it"
        if prompt.startswith("What do you want to eat") and memory.declined_corpse:
            memory.declined_corpse = False
            return "\x1b", "declined the corpse; not eating from the pack either"
        if prompt.startswith("What do you want to") and memory.pending_item:
            letter, memory.pending_item = memory.pending_item, ""
            return letter, f"answer with item {letter}"
        if ("eat it?" in prompt or "eat one?" in prompt) and memory.eating_corpse:
            memory.eating_corpse = False
            name = corpse_name(prompt)
            ok, why = corpse_safe(name, memory, v)
            memory.kills.pop((v.dlvl, *v.pos), None)
            memory.declined_corpse = not ok  # NetHack will then ask what to eat from the pack.
            _count(memory, "corpses_eaten" if ok else "corpses_declined")
            if not ok:
                _count(memory, f"declined: {why}")
            return ("y", f"eat the {name} corpse") if ok else ("n", f"not eating it: {why}")
        if "eat it?" in prompt and memory.pending_food:
            return "n", "not the corpse: the item from the pack"
    return None


def _count(memory: "Memory", key: str, n: int = 1) -> None:
    memory.stats[key] = memory.stats.get(key, 0) + n


def corpse_name(prompt: str) -> str:
    """'There is a partly eaten jackal corpse here; eat it?' -> 'jackal'."""
    text = prompt.split(" corpse")[0]
    for lead in ("There is an ", "There is a ", "There are "):
        if text.startswith(lead):
            text = text[len(lead):]
    words = text.split()
    while words and (words[0].isdigit() or words[0] in ("partly", "eaten")):
        words.pop(0)
    return " ".join(words)


def corpse_safe(name: str, memory: "Memory", v: "View") -> tuple[bool, str]:
    """Safe species, not our own kind, and fresh (our kill, recent). The
    same question also comes up for ordinary food lying here."""
    if any(f in name for f in SAFE_FOOD):
        return True, "ordinary food"
    if name not in SAFE_CORPSES:
        return False, f"{name} isn't on the safe list"
    race = v.status.get("race", "")
    if any(k in name for k in RACE_KIN.get(race, ())):
        return False, "cannibalism"
    if name in NEVER_ROTS:
        return True, "never rots"
    kill = memory.kills.get((v.dlvl, *v.pos))
    if not kill or kill[0] != name:
        return False, "don't know how old it is"
    age = v.status.get("turn", 0) - kill[1]
    return (age <= FRESH_TURNS, f"{age} turns old")


MENU_HEADERS = {"Coins": "$", "Weapons": ")", "Armor": "[", "Rings": "=", "Amulets": '"',
                "Tools": "(", "Comestibles": "%", "Potions": "!", "Scrolls": "?", "Spellbooks": "+",
                "Wands": "/", "Gems/Stones": "*", "Boulders/Statues": "`", "Iron balls": "0",
                "Chains": "_"}


def _pick_from_menu(v: View, memory: Memory) -> str:
    """Select the menu items whose class is wanted, then confirm."""
    keys, cls = "", ""
    for item in v.ctx.get("items", []):
        if not item["selectable"]:
            cls = MENU_HEADERS.get(item["text"].strip(), "")
        elif item["key"] and cls and (cls in memory.loot_classes or (
                cls == ")" and any(t in item["text"] for t in ("dagger", "dart", "knife", "shuriken")))) \
                and not any(w in item["text"] for w in NOT_CARRIED + ("corpse",)):
            keys += item["key"]
    memory.loot_classes = ""
    return keys + "\r"


# ---------- routines ----------
# Each step returns (keys, note) to keep going, or (None, "done: ...") /
# (None, "failed: ...") when it's finished.

DOOR_NOT_CLOSED = ("This door is broken", "This door is already open", "You see no door there",
                   "This doorway has no door")


def r_explore(v: View, memory: Memory, args: dict):
    if any(m.startswith(DOOR_NOT_CLOSED) for m in v.s.get("messages", [])) and memory.last_door:
        memory.features[memory.last_door] = "broken door"  # Our picture was stale.
    if any("Closed for inventory" in m for m in v.s.get("messages", [])):
        for dx, dy in DIRS.values():  # A shop door: kicking it angers the shopkeeper.
            memory.dead_doors.add((v.dlvl, v.pos[0] + dx, v.pos[1] + dy))
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
    """Search next to walls that face unexplored space: a hidden door there
    leads somewhere new. Walls between two known areas can't hide anything
    useful, so they're skipped."""
    def facing_unknown(x, y):
        for dx, dy in ORTHO:
            wx, wy = x + dx, y + dy
            if v.ch(wx, wy) in WALL or (v.ch(wx, wy) == " " and not v.cells.get((wx, wy))):
                beyond = [(wx + dx * k, wy + dy * k) for k in (1, 2, 3)]
                if all(v.ch(bx, by) == " " and not v.cells.get((bx, by)) for bx, by in beyond):
                    return True
        return False

    def spot(x, y, rounds):
        return memory.searched.get((v.dlvl, x, y), 0) < rounds and facing_unknown(x, y)
    here = (v.dlvl, *v.pos)
    for rounds in (1, 2):
        if spot(*v.pos, rounds):
            memory.searched[here] = memory.searched.get(here, 0) + 1
            return "10s", "search the walls here"
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
    _count(memory, "prayers")
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


def r_step_away(v: View, memory: Memory, args: dict):
    """Back off from a monster: {target: name} (default: nearest hostile)."""
    target = (args.get("target") or "").lower()
    foes = [(x, y) for (x, y), c in v.cells.items() if c["kind"] == "monster"
            and not v.peaceful(x, y) and (not target or target in c["name"])]
    if not foes:
        return None, "done: nothing to back away from"
    def gap(p):
        return min(max(abs(p[0] - fx), abs(p[1] - fy)) for fx, fy in foes)
    if args.get("steps", 0) >= int(args.get("max_steps", 3)) or gap(v.pos) >= 3:
        return None, "done: backed away"
    options = [(v.pos[0] + dx, v.pos[1] + dy) for dx, dy in DIRS.values()]
    options = [p for p in options if v.step_ok(v.pos, p) and not v.cells.get(p, {}).get("kind") == "monster"]
    best = max(options, key=gap, default=None)
    if best is None or gap(best) <= gap(v.pos):
        return None, "failed: nowhere further away to step"
    args["steps"] = args.get("steps", 0) + 1
    return KEY_FOR[(best[0] - v.pos[0], best[1] - v.pos[1])], "step away"


def r_elbereth(v: View, memory: Memory, args: dict):
    """Engrave Elbereth in the dust with a fingertip, then rest on it until
    HP recovers: most monsters won't melee you while you stand on it (3.6:
    attacking from it erodes it, so this never attacks)."""
    st = v.status
    if not args.get("sent"):
        args["sent"], args["at"], args["turn"] = True, v.pos, st.get("turn", 0)
        memory.engraving = True
        return "E", "engrave Elbereth"
    if v.pos != tuple(args["at"]) or st.get("turn", 0) - args["turn"] > 300:
        return None, "done: left the Elbereth square"
    if st.get("hp", 0) >= st.get("hpmax", 1) * 0.7:
        return None, "done: healed up on Elbereth"
    if any("You disturb the engraving" in m or "engraving now reads" in m for m in v.s.get("messages", [])):
        args["sent"] = False  # Smudged: write it again.
    return "5s", f"rest on Elbereth (HP {st.get('hp')}/{st.get('hpmax')})"


THROWABLE = ("dagger", "knife", "spear", "javelin", "dart", "shuriken")


def throwable(v: View) -> dict | None:
    """A throwable item that isn't the wielded weapon."""
    for item in v.s.get("inventory", []):
        if item["class"] == ")" and any(t in item["text"] for t in THROWABLE) \
                and "weapon in hand" not in item["text"]:
            return item
    return None


def in_line(a: tuple, b: tuple) -> tuple[int, int] | None:
    """The unit step from a toward b if they share a row, column or diagonal."""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if (dx == 0 or dy == 0 or abs(dx) == abs(dy)) and (dx or dy):
        return ((dx > 0) - (dx < 0), (dy > 0) - (dy < 0))
    return None


def r_throw(v: View, memory: Memory, args: dict):
    """Throw a dagger (or similar) at a monster in a straight line;
    {target: name}. Wielded weapons are never thrown."""
    if args.get("sent"):
        return None, "done: thrown"
    item = throwable(v)
    if not item:
        return None, "failed: nothing to throw"
    target = (args.get("target") or "").lower()
    for (x, y), c in v.cells.items():
        if c["kind"] == "monster" and (not target or target in c["name"]):
            step = in_line(v.pos, (x, y))
            if step and max(abs(x - v.pos[0]), abs(y - v.pos[1])) <= 8:
                args["sent"] = True
                memory.retrieve.add(next(t for t in THROWABLE if t in item["text"]))
                _count(memory, f"throws at {c['name']}")
                return "t" + item["letter"] + KEY_FOR[step], f"throw {item['letter']} at the {c['name']}"
    return None, "failed: no target in a straight line"


def r_use(v: View, memory: Memory, args: dict):
    """A command that asks for an item: quaff, read, wear, wield, zap..."""
    if args.get("sent"):
        return None, "done: used"
    args["sent"] = True
    memory.pending_item = str(args.get("item", ""))
    return str(args["command"]), f"{args['command']!r} with item {memory.pending_item}"


def r_loot(v: View, memory: Memory, args: dict):
    """Walk to the nearest visible item of a wanted class and pick it up
    (only on the square it set out for, so it never grabs whatever it
    happens to walk over)."""
    classes = str(args.get("classes", ""))
    here = (v.dlvl, *v.pos)
    if args.get("sent"):
        memory.looted.add(here)
        args.pop("sent")
        args.pop("target", None)
        return None, "done: picked over"
    if any(c["kind"] == "monster" and c["name"] == "shopkeeper" for c in v.cells.values()):
        return None, "done: a shopkeeper is watching; nothing here is free"

    def wanted(x, y):
        c = v.cells.get((x, y))
        if c is not None and c["kind"] == "object" and c.get("class") == ")" \
                and any(t in c["name"] for t in THROWABLE if t not in ("spear", "javelin")) \
                and (v.dlvl, x, y) not in memory.looted:
            return True  # Daggers, darts, knives: light, and what we throw.
        return (c is not None and c["kind"] == "object" and c.get("class", "") in classes
                and not any(w in c["name"] for w in NOT_CARRIED + ("corpse",))
                and (v.dlvl, x, y) not in memory.looted and (v.dlvl, x, y) not in memory.blocked)
    if args.get("target") and tuple(args["target"]) == v.pos and here not in memory.looted:
        args["sent"] = True
        memory.loot_classes = classes
        return ",", "pick up"
    path = bfs(v, wanted)
    if path:
        args["target"] = path[-1]
        return _step(v, memory, path, f"walk to loot at {path[-1]}")
    return None, "done: no wanted items in view"


NOT_CARRIED = ("box", "chest", "boulder", "heavy iron ball", "iron chain")  # open or leave these


def r_probe_dark(v: View, memory: Memory, args: dict):
    """Dark caves (the Mines) show walls but not their floor: probe blank
    squares next to places we've stood. Bumping rock costs no time."""
    def probe_dir(x, y):
        for dx, dy in ORTHO:
            b = (x + dx, y + dy)
            if v.ch(*b) == " " and not v.cells.get(b) and (v.dlvl, *b) not in memory.probed:
                return dx, dy
        return None
    if (v.dlvl, *v.pos) in memory.visited and probe_dir(*v.pos):
        dx, dy = probe_dir(*v.pos)
        memory.probed.add((v.dlvl, v.pos[0] + dx, v.pos[1] + dy))
        return KEY_FOR[(dx, dy)], "probe the dark"
    path = bfs(v, lambda x, y: (v.dlvl, x, y) in memory.visited and probe_dir(x, y) is not None)
    if path:
        return _step(v, memory, path, f"go probe the dark near {path[-1]}")
    return None, "done: nothing left to probe"


def _dead_end(v: View, x: int, y: int) -> bool:
    """A corridor square with one way out: hidden passages hide past these."""
    if v.ch(x, y) != "#" and not (v.memory and (v.dlvl, x, y) in v.memory.corridors):
        return False
    return sum(v.walkable(x + dx, y + dy) for dx, dy in DIRS.values()) == 1


def r_search_dead_ends(v: View, memory: Memory, args: dict):
    here = (v.dlvl, *v.pos)
    if _dead_end(v, *v.pos) and memory.searched.get(here, 0) < 1:
        memory.searched[here] = 1
        return "10s", "search the dead end"
    path = bfs(v, lambda x, y: _dead_end(v, x, y) and memory.searched.get((v.dlvl, x, y), 0) < 1)
    if path:
        return _step(v, memory, path, f"go to the dead end at {path[-1]}")
    return None, "done: no unsearched dead ends"


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
    "loot": (r_loot, "pick up visible items of the given classes; {classes: e.g. '?!/=\"+('}"),
    "search_dead_ends": (r_search_dead_ends, "search corridor dead ends for hidden passages"),
    "throw": (r_throw, "throw a dagger/knife/spear/dart at a monster in a straight line; {target: name}"),
    "elbereth": (r_elbereth, "engrave Elbereth in the dust here; most monsters won't melee you on it"),
    "step_away": (r_step_away, "back off from a monster; {target: optional name, max_steps: default 3}"),
    "use": (r_use, "a command that takes an item, e.g. {command: 'q', item: 'f'} to quaff f; also r read, W wear, w wield, P put on, z zap, T take off"),
    "keys": (r_keys, "send raw keys once to answer a game prompt; {keys}. Not for walking"),
}


HUNGER_RANK = ["", "Hungry", "Weak", "Fainting", "Fainted"]


def _key(why: str) -> str:
    """An escalation's identity, ignoring numbers (HP, difficulty) that change."""
    return re.sub(r"\d+", "#", why)

DEFAULT_ORDERS = {
    "fight_up_to": None,        # melee adjacent hostiles up to this difficulty (None: your level + 2)
    "avoid": sorted(DONT_MELEE),  # never melee these
    "eat_at": "Hungry",         # eat known-safe food at this hunger ("never" to stop)
    "rest_below": 0.5,          # rest when HP is below this fraction and nothing's in view
    "pray_when_critical": True,  # pray at critical HP when prayer should be safe
    "pickup_gold": True,        # walk to visible gold
    "descend": True,            # default activity ends by taking the stairs down
    "loot": "$?!/=\"+(%",        # item classes to pick up ($ gold ? scroll ! potion / wand = ring " amulet + book ( tool % food, never corpses)
    "explore_fully": True,      # search dead ends for hidden passages before going down
    "eat_corpses": "unless_satiated",  # fresh safe kills: "unless_satiated", "hungry" or "never"
    "ranged_kill": ["floating eye", "acid blob", "gas spore"],  # throw at these when in line
    "retreat_below": 0.35,      # badly hurt with a hostile adjacent: ask the brain before it's critical
}

WALK_ONLY = set("hjklyubnHJKLYUBN0123456789")


class Engine:
    """Deterministic: runs mechanics, standing orders, the brain's current
    routine and a default activity, one key at a time. Escalates to the
    brain only what the standing orders don't cover."""

    def __init__(self) -> None:
        self.memory = Memory()
        self.orders = dict(DEFAULT_ORDERS)
        self.routine: str | None = None
        self.args: dict = {}
        self.last_checks: dict = {}
        self.acknowledged: set[str] = set()  # escalations the brain's routine is handling
        self.note = ""
        self._loot_args: dict = {"classes": self.orders["loot"]}
        self._acct: tuple = ("start", None)  # (activity of the last keys, turn then)

    def _activity(self) -> str:
        """Which activity the last keys belonged to, for turn accounting."""
        note = self.note or ""
        if self.routine:
            return self.routine
        if note.startswith("standing order: "):
            return note[16:].split(":")[0].split(",")[0].split(" the ")[0].split(" (")[0].strip()
        return note.split(":")[0] if ":" in note else note.split(" ")[0]

    def order(self, routine: str, args: dict | None = None, handles: list[str] | None = None) -> None:
        """Run `routine` next. `handles`: the escalations it answers, so the
        standing orders stop raising them while it runs."""
        if routine not in ROUTINES:
            raise ValueError(f"unknown routine {routine!r}")
        # Everything the brain has answered stays answered until its routine
        # finishes, even if a later answer switches routines (badly hurt ->
        # elbereth, then too-tough monster -> fight): otherwise two alarms
        # take turns re-firing and the brain ping-pongs between them.
        self.acknowledged |= {_key(h) for h in handles or []}
        self.routine, self.args = routine, dict(args or {})

    def set_orders(self, changes: dict) -> list[str]:
        """Update standing orders; returns what was rejected."""
        bad = [k for k in changes if k not in DEFAULT_ORDERS]
        self.orders.update({k: v for k, v in changes.items() if k in DEFAULT_ORDERS})
        return bad

    def step(self, s: dict) -> tuple[str | None, list[str]]:
        """Keys to send for this snapshot (or None), and escalations for the
        brain (empty when the engine has it covered)."""
        self.memory.avoid = set(self.orders["avoid"])
        v = View(s, self.memory)
        for (x, y), c in v.cells.items():
            if c["kind"] == "feature":
                self.memory.features[(v.dlvl, x, y)] = c["name"]
        for y, row in enumerate(v.map):
            for x, ch in enumerate(row, start=1):
                if ch == "#" and (x, y) not in v.cells:
                    self.memory.corridors.add((v.dlvl, x, y))
        if v.pos:
            self.memory.visited.add((v.dlvl, *v.pos))

        self._record_kills(v)
        self._read_messages(v)
        turn = v.status.get("turn")
        if turn is not None and self._acct[1] is not None and turn > self._acct[1]:
            _count(self.memory, f"turns: {self._acct[0]}", turn - self._acct[1])
        self._acct = (self._activity(), turn if turn is not None else self._acct[1])
        mech = mechanics(v, self.memory)
        if mech:
            self.note = mech[1]
            return mech[0], []
        if v.kind != "command":
            if self.routine == "keys":  # The brain's answer to this prompt.
                keys, self.note = r_keys(v, self.memory, self.args)
                self._end_routine()
                if keys:
                    return keys, []
            return None, [f"prompt: {v.kind} {v.ctx.get('prompt') or ''!r} choices {v.ctx.get('choices') or ''!r}"]

        c = checks(v, self.memory)
        self.last_checks = c

        standing = self._standing(v, c)
        if standing is not None:
            keys, why = standing
            if keys is None:
                return None, [why]
            self.note = why
            return self._stuck_guard(v, keys, why)

        if self.routine:
            if self.routine == "keys" and set(self.args.get("keys", "")) <= WALK_ONLY:
                self._end_routine()
                return None, ["keys rejected: walking is the engine's job (use explore, go_to, go_down)"]
            fn, _ = ROUTINES[self.routine]
            keys, note = fn(v, self.memory, self.args)
            self.note = note
            if keys is not None:
                return self._stuck_guard(v, keys, note)
            finished = f"{self.routine} {note}"
            self._end_routine()
            if " failed:" in finished:
                return None, [finished]  # The brain's plan didn't work: its call.
        return self._default_activity(v)

    def _record_kills(self, v: View) -> None:
        """'You kill the jackal!' after we attacked a square: remember what
        died there and when, so its corpse can be judged."""
        m = self.memory
        for msg in v.s.get("messages", []):
            for verb in ("You kill the ", "You destroy the ", "You kill it"):
                if msg.startswith(verb) and m.pending_fight:
                    name = msg[len(verb):].rstrip("!.").strip() if verb != "You kill it" else "?"
                    m.kills[(v.dlvl, *m.pending_fight)] = (name, v.status.get("turn", 0))
                    m.pending_fight = None
                    _count(m, "kills")
                    _count(m, "safe kills" if name in SAFE_CORPSES else f"unsafe kill: {name}")

    def _read_messages(self, v: View) -> None:
        """Prayer results and Luck penalties, from every snapshot's messages
        (--More-- ones too: that's where a prayer's result shows)."""
        m, turn = self.memory, v.status.get("turn", 0)
        for msg in v.s.get("messages", []):
            undecided = m.stats.get("prayers ok", 0) + m.stats.get("prayers failed", 0) < m.stats.get("prayers", 0)
            if undecided and m.last_pray_turn is not None and turn - m.last_pray_turn <= 10:
                if PRAYER_OK.match(msg) or msg.startswith("You are surrounded by a shimmering light"):
                    _count(m, "prayers ok")
                elif msg.startswith(PRAYER_FAILED):
                    m.prayer_broken = True
                    _count(m, "prayers failed")
            for text, turns in LUCK_PENALTIES.items():
                if text in msg:  # Luck recovers one point per 600 turns.
                    m.luck_bad_until = max(m.luck_bad_until, turn + turns)
                    _count(m, "luck penalties")
            if "You feel feverish" in msg:
                m.feverish = True
            elif "You feel purified" in msg:
                m.feverish = False

    def _corpse_to_eat(self, v: View, c: dict):
        """A fresh safe kill with a corpse still on it, within a short walk."""
        o, m = self.orders, self.memory
        policy = o["eat_corpses"]
        if policy == "never" or c["hunger"] == "Satiated" or c["visible_hostiles"]:
            return None
        if policy == "hungry" and c["hunger"] not in HUNGRY:
            return None
        turn = c["turn"]
        spots = {(x, y) for (d, x, y), (name, when) in m.kills.items()
                 if d == v.dlvl and name in SAFE_CORPSES
                 and (name in NEVER_ROTS or turn - when <= FRESH_TURNS)
                 and not any(k in name for k in RACE_KIN.get(v.status.get("race", ""), ()))}
        if not spots:
            return None
        if v.pos in spots:
            if "corpse" not in " ".join(v.s.get("messages", [])) and (v.dlvl, *v.pos) in m.looted:
                return None
            m.looted.add((v.dlvl, *v.pos))
            m.eating_corpse = True  # The kill record stays until the prompt is answered.
            return "e", "eat the fresh kill"
        def has_corpse(x, y):
            cell = v.cells.get((x, y))
            return (x, y) in spots and cell is not None and cell["name"] == "corpse"
        path = bfs(v, has_corpse)
        if path and len(path) <= 8:
            return _step(v, m, path, f"walk to the fresh kill at {path[-1]}")
        return None

    def _end_routine(self) -> None:
        self.routine, self.args, self.acknowledged = None, {}, set()

    def _escalate(self, why: str):
        return None if _key(why) in self.acknowledged else (None, why)

    def _standing(self, v: View, c: dict):
        """Standing orders, most urgent first. Returns (keys, why), an
        escalation (None, why), or None when no order applies."""
        o, m = self.orders, self.memory
        if c["major_trouble"] and o["pray_when_critical"] and c["prayer_safe"]:
            return r_pray(v, m, {})[0], f"standing order: pray ({', '.join(c['major_trouble'])})"
        if c["wounded"] == "critical":
            esc = self._escalate("critical HP and prayer isn't safe")
            if esc:
                return esc
        if c["adjacent_hostiles"] and c["hp"] < c["hpmax"] * float(o["retreat_below"]):
            names = ", ".join(sorted({m["name"] for m in c["adjacent_hostiles"]}))
            esc = self._escalate(f"badly hurt (HP {c['hp']}/{c['hpmax']}) with {names} adjacent")
            if esc:
                return esc
        for mon in c["visible_hostiles"]:
            if mon["name"] == "gas spore" and mon["distance"] <= 1:
                if c["hp"] > 26:  # Its blast is 4d6 (max 24): take it, and it may kill neighbors.
                    m.pending_fight = (mon["x"], mon["y"])
                    return ("F" + KEY_FOR[(mon["x"] - v.pos[0], mon["y"] - v.pos[1])],
                            "standing order: pop the gas spore (HP can take the blast)")
                keys, note = r_step_away(v, m, {"target": "gas spore", "max_steps": 1})
                if keys:
                    return keys, "standing order: back off from the gas spore before it pops"
            if mon["name"] in o["ranged_kill"] and throwable(v) and in_line(v.pos, (mon["x"], mon["y"])) \
                    and mon["distance"] <= 8 and (mon["name"] != "gas spore" or mon["distance"] >= 2):
                keys, note = r_throw(v, m, {"target": mon["name"]})
                if keys:
                    return keys, "standing order: " + note
        limit = o["fight_up_to"] if o["fight_up_to"] is not None else (c["xlvl"] or 1) + 2
        for mon in c["adjacent_hostiles"]:
            if mon["name"] in o["avoid"]:
                # Never melee it; paths already route around it. Only ones
                # that hurt just by being near are worth asking about.
                esc = (self._escalate(f"{mon['name']} adjacent (dangerous to be near)")
                       if mon["name"] in DANGEROUS_NEAR else None)
            elif mon["difficulty"] <= limit:
                m.pending_fight = (mon["x"], mon["y"])
                return ("F" + KEY_FOR[(mon["x"] - v.pos[0], mon["y"] - v.pos[1])],
                        f"standing order: fight the {mon['name']}")
            else:
                esc = self._escalate(f"{mon['name']} adjacent, difficulty {mon['difficulty']} > {limit}")
            if esc:
                return esc
        eat_at = o["eat_at"]
        hunger = HUNGER_RANK.index(c["hunger"]) if c["hunger"] in HUNGER_RANK else 0  # Satiated: 0
        if eat_at in HUNGER_RANK and hunger >= HUNGER_RANK.index(eat_at) > 0:
            if c["safe_food"]:
                m.pending_food = c["safe_food"][0]["letter"]
                return "e", f"standing order: eat ({c['hunger']})"
            if hunger >= HUNGER_RANK.index("Weak"):
                # Prayer (above) handles it when the gate is open; else ask.
                esc = self._escalate(f"{c['hunger']} and no known-safe food")
                if esc:
                    return esc
            # Merely Hungry: keep going; the next safe kill is a meal.
        corpse = self._corpse_to_eat(v, c)
        if corpse:
            return corpse[0], "standing order: " + corpse[1]
        if c["hp"] < c["hpmax"] * float(o["rest_below"]) and not c["visible_hostiles"]:
            return "20s", f"standing order: rest (HP {c['hp']}/{c['hpmax']})"
        if o["pickup_gold"] and "$" not in str(o["loot"]) and c["gold_visible"] \
                and not c["visible_hostiles"] and not self.routine:
            keys, note = r_pickup_gold(v, m, {})
            if keys:
                return keys, "standing order: " + note
        return None

    def _default_activity(self, v: View):
        """Nothing urgent, no routine from the brain: clear the level. Loot
        what's wanted, explore everything, search dead ends, then go down
        (searching the walls if there are no stairs)."""
        m = self.memory
        burdened = v.status.get("encumbrance", "") != ""
        if self.orders["loot"] and not burdened and not self.last_checks.get("visible_hostiles"):
            keys, note = r_loot(v, m, self._loot_args)
            if keys:
                self.note = "loot: " + note
                return self._stuck_guard(v, keys, note)
            self._loot_args = {"classes": self.orders["loot"]}
        keys, note = r_explore(v, m, {})
        if keys:
            self.note = "explore: " + note
            return self._stuck_guard(v, keys, note)
        stairs_known = self.last_checks.get("stairs_down") is not None
        if not stairs_known:  # No way down in sight: feel around dark areas first.
            keys, note = r_probe_dark(v, m, {})
            if keys:
                self.note = "probe: " + note
                return self._stuck_guard(v, keys, note)
        if self.orders["explore_fully"] and not stairs_known:
            keys, note = r_search_dead_ends(v, m, {})
            if keys:
                self.note = "search dead ends: " + note
                return self._stuck_guard(v, keys, note)
        if self.orders["descend"]:
            keys, note = r_go_down(v, m, {"start_dlvl": v.dlvl})
            if keys:
                self.note = "go down: " + note
                return self._stuck_guard(v, keys, note)
        if v.dlvl not in m.searched_out:
            keys, note = r_search_walls(v, m, {})
            if keys:
                self.note = "search walls: " + note
                return self._stuck_guard(v, keys, note)
            m.searched_out.add(v.dlvl)
        # A never-melee monster parked in the way (a floating eye in a
        # corridor, say): they do drift, so wait a while before giving up.
        blockers = [mon["name"] for mon in self.last_checks.get("visible_hostiles", [])
                    if mon["name"] in self.orders["avoid"] and mon["distance"] <= 2]
        waited = m.stats.get(f"waited on dlvl {v.dlvl}", 0)
        if blockers and waited < 60:
            _count(m, f"waited on dlvl {v.dlvl}", 5)
            self.note = f"wait for the {blockers[0]} to move out of the way"
            return "5s", []
        return None, ["no way on: explored, searched the walls, no stairs down known"
                      + (f" ({', '.join(blockers)} in the way)" if blockers else "")]

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
            if not self.routine:  # The engine's own activity: pass a turn and pick another target.
                return "s", f"stuck on {keys!r}: marked blocked, trying elsewhere"
            what = self.routine
            self._end_routine()
            return None, [f"{what} stuck: {keys!r} changes nothing here"]
        return keys, []
