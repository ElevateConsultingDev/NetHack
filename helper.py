#!/usr/bin/env python3
"""NetHack with a Claude helper on the same screen.

The game runs in a pty on the left (drawn through pyte, a terminal emulator);
a chat pane sits on the right. ^] (or ⌃G t) switches focus. Each question goes to
`claude -p` along with what's on screen and, through the aipipe socket
(src/aipipe.c, NETHACK_CONTROL), the inventory. Run it with ./play.
"""
import curses
import locale
import json
import os
import pty
import shutil
import time
import re
import select
import signal
import socket
import struct
import subprocess
import sys
import tempfile
import textwrap
import threading
import fcntl
import termios

import pyte

import gamelog
import guard
import saves
import palette

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(HERE, "playground")
SAVES = os.path.join(GAME, "save")
SNAPS = os.path.join(HERE, "checkpoints")  # outside playground/, which a NetHack install wipes
LOGS = os.path.join(HERE, "logs")          # one game log per character (gamelog.py)
KEEP_SNAPS = 20  # checkpoints kept per character (prune in the saves list)
MODEL = os.environ.get("NH_HELPER_MODEL", "sonnet")
HELPER_W = int(os.environ.get("NH_HELPER_WIDTH", "40"))
def ctrl_opt(letter):
    """The bytes for Control-Option-letter (Option sends Alt: macos-option-as-alt)."""
    return b"\x1b" + bytes([ord(letter) & 0x1f])


# the wrapper's own shortcuts: ⌃G, then a letter (internally each one is a
# Control-Option code, which also works directly where nothing else takes it)
LEADER = b"\x07"  # ⌃G: NetHack only uses it in debug mode
TOGGLE = (b"\x1d", ctrl_opt("T"))  # ^] or ⌃G t: type into the helper / the game
FKEYS = {ctrl_opt("F"): b"#fog\r",     # lift / bring back the fog of war
         ctrl_opt("D"): b"#godown\r",  # travel to the down stairs
         ctrl_opt("U"): b"#goup\r"}    # travel to the up stairs
WHAT_NOW = ctrl_opt("W")   # ask the helper what to do now
SNAPSHOT = ctrl_opt("S")   # checkpoint the game now
REWIND = ctrl_opt("R")     # go back to the last checkpoint
SAVES_KEY = ctrl_opt("L")  # the saves list: load, delete, prune, new game
SEARCH = ctrl_opt("K")     # search commands, items and map things
COPY = ctrl_opt("C")       # copy the game screen to the clipboard as text
SELECT = ctrl_opt("V")     # select mode: drag a rectangle to copy it
ZOOM_IN, ZOOM_OUT = ctrl_opt("I"), ctrl_opt("O")  # (or the wheel over the map)
LEADER_KEYS = {"t": "T", "f": "F", "d": "D", "u": "U", "w": "W", "s": "S", "r": "R", "l": "L",
               "k": "K", "c": "C", "v": "V", "i": "I", "o": "O"}
BAR = "⌃G: f fog  d/u stairs  w what now?  k search  s checkpoint  r back  l saves  c copy  v select  i/o zoom  t helper"
LEADER_BAR = (" ⌃G then: f fog of war  d down stairs  u up stairs  w what now?  k search  s checkpoint  l saves  "
              "r back to last checkpoint  c copy screen  v select  i zoom in  o zoom out  t helper/game   (anything else cancels) ")
MOUSE_ON = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"   # clicks, drags (for resizing), SGR coordinates
MOUSE_OFF = "\x1b[?1006l\x1b[?1002l\x1b[?1000l"
UP, DOWN = (b"\x1b[A", b"\x1bOA"), (b"\x1b[B", b"\x1bOB")
COMMANDS = palette.load_commands(os.path.join(HERE, "src", "cmd.c"))
EXTRAS = [dict(label="what now", detail="ask the helper what to do right now  [⌃G w]", action=("fkey", WHAT_NOW)),
          dict(label="checkpoint", detail="save a checkpoint to come back to  [⌃G s]", action=("fkey", SNAPSHOT)),
          dict(label="back to checkpoint", detail="go back to the last checkpoint  [⌃G r]", action=("fkey", REWIND)),
          dict(label="saves", detail="load, delete or prune saves and checkpoints; new game  [⌃G l]",
               action=("fkey", SAVES_KEY)),
          dict(label="copy screen", detail="copy the game screen as text  [⌃G c]", action=("fkey", COPY)),
          dict(label="zoom in", detail="bigger map squares  [⌃G i, wheel up over the map]", action=("fkey", ZOOM_IN)),
          dict(label="zoom out", detail="smaller map squares  [⌃G o, wheel down over the map]", action=("fkey", ZOOM_OUT)),
          dict(label="select mode", detail="drag a rectangle to copy it  [⌃G v]", action=("fkey", SELECT)),
          dict(label="switch focus", detail="type into the helper or the game  [⌃], ⌃G t]", action=("fkey", b"\x1d"))]
for _c in COMMANDS:  # the wrapper's shortcuts for game commands
    _f = {"fog": "⌃G f", "godown": "⌃G d", "goup": "⌃G u"}.get(_c["label"])
    if _f:
        _c["detail"] = _c["detail"][:-1] + f", {_f}]"
SAVE_KEYS = b"Sy\r"     # save, yes, dismiss "Saving..." (the game then exits)
MOUSE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")  # SGR mouse report (mode 1006)
MENU_ITEM = re.compile(r"(?:^|[ \u2502])([a-zA-Z$#*-])\) ")  # " a) a +1 long sword"
MAP_W = 80  # the map's width; the status/inventory panel starts right after it
MAP_H = 21  # map rows, y = 0..20
GX = 3      # gutter left of the game for row numbers (y)
RULER = 2   # rows under the game for column numbers (x)
# kitty can draw text scaled up in place (its text-sizing protocol, OSC 66);
# elsewhere a zoomed square is a block of its character
KITTY = os.environ.get("TERM") == "xterm-kitty" or "KITTY_WINDOW_ID" in os.environ
try:  # terminals that show images draw the zoomed map as a picture, with truly bigger characters
    import mapimage
    GRAPHICS = not KITTY and os.environ.get("TERM_PROGRAM") in ("ghostty", "WezTerm")
except ImportError:  # no Pillow
    GRAPHICS = False
ROW_SQUEEZE = 0.62  # picture zoom: squares ~5/8 as tall as the cell shape, so rows sit close
ZOOMS = ([(1, 1)] + [(z, z * ROW_SQUEEZE) for z in (1.25, 1.5, 1.75, 2, 2.5, 3, 3.5, 4)] if GRAPHICS
         else [(1, 1), (2, 2), (3, 3), (4, 4)] if KITTY  # columns x rows per map square
         else [(1, 1), (2, 1), (4, 2), (6, 3)])
SGR_FG = {"black": 30, "red": 31, "green": 32, "brown": 33, "blue": 34, "magenta": 35,
          "cyan": 36, "white": 37}


def big_char(row, col, scale, ch, c):
    """kitty escape codes drawing one character `scale` times bigger at a screen cell,
    in the colors of pyte cell c."""
    code = SGR_FG.get(c.fg.removeprefix("bright"))
    sgr = ["0"] + (["1"] if c.bold or c.fg.startswith("bright") else []) + (["7"] if c.reverse else [])
    if code:
        sgr.append(str(code + (60 if c.fg.startswith("bright") else 0)))
    return f"\x1b[{row + 1};{col + 1}H\x1b[{';'.join(sgr)}m\x1b]66;s={scale};{ch}\x07"
PANEL_TOP = 0  # messages stop at the map's edge (cursinit.c), so the panel can use every row
MENU_PAGE = re.compile(r"\(Page \d+ of \d+\)")  # footer of a curses menu with more pages

SYSTEM = """You are a friendly NetHack 3.6 expert sitting next to the player, \
who plays in a terminal with the standard keyboard commands (curses interface). \
Each message gives the current screen, the inventory, and any question the game \
is asking, then the player's question.

Answer briefly and practically: a few sentences or a short list, under about \
120 words, about what is on screen now. Name the exact keys to press. Warn about \
real dangers (low HP, hunger, cursed or unknown items, peaceful monsters, \
shopkeepers, floating eyes, cockatrices).

The player has turned on a cheat: you also get the whole level as it really is, every monster, every item (truly identified, with blessed/cursed status), every trap, and the inventory fully identified. Use it freely, spoilers are wanted, but say so when you are telling them something they could not have seen. Coordinates are x=column (1 is the left edge of the map), y=row (0 is the top). \
Plain text only, no markdown: it is shown in a narrow terminal pane. \
Every message gives the game log's file name and its latest lines. The log is the whole \
game so far (every message with turn T and dungeon level D, level changes, warnings, \
checkpoints, earlier questions); when you need older history, read the file with the Read \
tool (it is in your working directory). \
Write keys the Mac way: ⌃ is Control (⌃D kicks), ⌥ is Option, which is NetHack's Meta/Alt \
(⌥L loots, ⌥P prays; never write M-l), ⇧ is Shift. Extended commands can always be typed \
with # (#loot). This player's helper shortcuts: ⌃G f fog of war, ⌃G d / ⌃G u walk to the \
down / up stairs, ⌃G k search, ⌃G s checkpoint, ⌃G r back to the last checkpoint, ⌃G l saves."""

ASCII = str.maketrans("─│┌┐└┘├┤┬┴┼", "-|+++++++++")  # box drawing as plain ASCII, any font
COLORS = {"black": 0, "red": 1, "green": 2, "brown": 3, "blue": 4,
          "magenta": 5, "cyan": 6, "white": 7}


class Watcher:
    """Listens on the aipipe socket and keeps the game's latest state."""

    def __init__(self):
        self.path = f"/tmp/nhhelper-{os.getpid()}.sock"  # macOS: under 104 bytes
        self.state = {}
        self.srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.srv.bind(self.path)
        self.srv.listen(1)
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        while True:  # a new connection each time the game restarts (checkpoints, loads)
            try:
                conn, _ = self.srv.accept()
            except OSError:
                return
            self.state = {}
            for line in conn.makefile("r", errors="replace"):
                try:
                    self.state = json.loads(line)
                except ValueError:
                    pass

    def close(self):
        self.srv.close()
        if os.path.exists(self.path):
            os.unlink(self.path)


class Helper:
    """The chat: transcript, input line, and one claude -p conversation."""

    def __init__(self):
        self.lines = [("dim", "Ask anything about the game. ⌃] switches focus.")]
        self.input = ""
        self.busy = False
        self.session = None
        self.scroll = 0  # lines up from the bottom
        self.on_answer = None  # called after each answer (the app saves the history)

    def save(self, path):
        """The transcript and Claude conversation, so they come back with the game."""
        if path:
            with open(path + ".tmp", "w") as f:
                json.dump({"session": self.session, "lines": self.lines[-1000:]}, f)
            os.replace(path + ".tmp", path)

    def load(self, path):
        """Bring back a saved transcript (replacing this one) and its Claude conversation."""
        try:
            with open(path) as f:
                d = json.load(f)
        except (OSError, ValueError):
            return False
        self.lines = [tuple(l) for l in d.get("lines", [])] + [("dim", "(history restored)")]
        self.session, self.scroll = d.get("session"), 0
        return True

    def ask(self, question, snapshot, redraw, log=None):
        self.lines.append(("you", "> " + question))
        self.busy = True
        if log:
            log.event(f"asked the helper: {question}")

        def run():
            try:
                answer, self.session = ask_claude(question, snapshot, self.session)
                self.lines.append(("text", answer))
                if self.on_answer:
                    self.on_answer()
                if log:
                    log.event("helper: " + answer.replace("\n", " / "))
            except RuntimeError as e:
                self.lines.append(("err", f"error: {e}"))
            self.busy = False
            redraw()
        threading.Thread(target=run, daemon=True).start()


def ask_claude(question, snapshot, session):
    """Runs claude -p (subscription login; its only tool is Read, in the logs folder,
    for the full game log); returns (answer, session)."""
    os.makedirs(LOGS, exist_ok=True)
    cmd = ["claude", "-p", "--output-format", "json", "--model", MODEL,
           "--tools", "Read", "--allowedTools", "Read", "--setting-sources", "", "--strict-mcp-config",
           "--system-prompt", SYSTEM]
    if session:
        cmd += ["--resume", session]
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    prompt = f"Game state:\n{snapshot}\n\nQuestion: {question}"
    try:
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                             timeout=180, cwd=LOGS, env=env)
    except subprocess.TimeoutExpired:
        raise RuntimeError("Claude took longer than 120s")
    except FileNotFoundError:
        raise RuntimeError("claude is not on PATH")
    try:
        result = json.loads(out.stdout)
    except ValueError:
        raise RuntimeError((out.stderr or out.stdout or "no output").strip()[:300])
    if result.get("is_error"):
        raise RuntimeError(str(result.get("result") or "Claude error")[:300])
    return str(result.get("result", "")).strip(), result.get("session_id") or session


def snapshot(screen, state):
    """What the player sees, plus what the aipipe channel adds (inventory, prompt)."""
    rows = [r.rstrip() for r in screen.display]
    parts = ["Screen:\n" + "\n".join(rows).strip("\n")]
    inv = state.get("inventory")
    if inv:
        parts.append("Inventory (weight of each stack in brackets):\n"
                     + "\n".join(f"{i['letter']} - {i['text']} [{i.get('weight')}]" for i in inv))
    ctx = state.get("context") or {}
    if ctx.get("prompt"):
        parts.append(f"The game is asking: {ctx['prompt']}")
    rev = state.get("reveal")
    if rev:
        you = state.get("player", {})
        parts.append(f"CHEAT, the whole level as it really is (you are @ at x={you.get('x')} y={you.get('y')}):\n"
                     + "\n".join(r.rstrip() for r in rev["map"]).strip("\n"))
        parts.append("Monsters:\n" + "\n".join(
            f"x={m['x']} y={m['y']} {m['name']} hp={m['hp']}" + (" tame" if m["tame"] else " peaceful" if m["peaceful"] else "")
            for m in rev["monsters"]))
        parts.append("Items on the floor:\n" + "\n".join(f"x={o['x']} y={o['y']} {o['text']}" for o in rev["objects"]))
        parts.append("Traps:\n" + "\n".join(f"x={t['x']} y={t['y']} {t['name']}" for t in rev["traps"]))
        parts.append("Inventory, truly identified:\n" + "\n".join(f"{i['letter']} - {i['text']}" for i in rev["inventory"]))
        st, pray = state.get("status") or {}, rev.get("prayer") or {}
        parts.append("Character: " + ", ".join(f"{k} {v}" for k, v in st.items() if k != "conditions")
                     + f", conditions {' '.join(st.get('conditions', [])) or 'none'}"
                     + f"; luck {pray.get('luck')}, prayer timeout {pray.get('timeout')}, god anger {pray.get('anger')}"
                     + f", nutrition {rev.get('nutrition')}, alignment record {rev.get('align_record')}")
        parts.append("Intrinsics: " + (", ".join(rev.get("intrinsics", [])) or "none"))
        parts.append("Pets: " + ("; ".join(
            f"{(p['name'] + ' the ') if p['name'] else ''}{p['species']} at x={p['x']} y={p['y']}: level {p['level']}, "
            f"HP {p['hp']}/{p['hpmax']}, AC {p['ac']}, speed {p['speed']}, tameness {p['tameness']}/20, "
            f"turns until hungry {p.get('turns_until_hungry')}" + (", leashed" if p["leashed"] else "")
            + (", carrying " + ", ".join(p["carrying"]) if p["carrying"] else "")
            for p in rev.get("pets", [])) or "none"))
        parts.append("Timed effects (buffs and ailments, turns left): "
                     + (", ".join(f"{t['name']} {t['turns']}" for t in rev.get("timed", [])) or "none"))
        parts.append("Spells: " + (", ".join(f"{sp['name']} (level {sp['level']}, remembered {sp['turns_left']} more turns)"
                                             for sp in rev.get("spells", [])) or "none"))
        parts.append("Skills: " + ", ".join(f"{k['name']} {k['level']}/{k['max']}" + (" CAN ADVANCE (#enhance)" if k["can_advance"] else "")
                                            for k in rev.get("skills", [])))
        parts.append("Conduct counts: " + ", ".join(f"{k} {v}" for k, v in (rev.get("conduct") or {}).items()))
        parts.append("Discoveries: " + (", ".join(rev.get("discoveries", [])) or "none"))
        parts.append("Killed so far: " + (", ".join(f"{n} x{c}" for n, c in (rev.get("vanquished") or {}).items()) or "nothing"))
    return "\n\n".join(parts)


OBJECT_CLASSES = {")": "weapon", "[": "armor", "!": "potion", "?": "scroll", "/": "wand",
                  "=": "ring", '"': "amulet", "(": "tool", "%": "food", "*": "gem or rock",
                  "$": "gold", "`": "boulder or statue", "+": "spellbook", "0": "iron ball",
                  "_": "iron chain"}
INV_GROUPS = [("$", "Coins"), (")", "Weapons"), ("[", "Armor"), ("%", "Food"), ("?", "Scrolls"),
              ("+", "Spellbooks"), ("!", "Potions"), ("=", "Rings"), ('"', "Amulets"), ("/", "Wands"),
              ("(", "Tools"), ("*", "Gems & rocks"), ("`", "Boulders & statues"), ("0", "Iron balls"),
              ("_", "Chains")]
IN_USE = re.compile(r"\((being worn|weapon in hand|wielded|on left|on right|in quiver|lit|in use|"
                    r"embedded|tethered|attached|chained|alternate weapon; not wielded)")
MENU_LINE = re.compile(r"^([< ])([a-zA-Z$#])([>)]) (.*?)\s*$")  # a curses menu line; <a> = selected
LEGEND_ORDER = ("you", "pet", "monster", "invisible", "object", "trap", "feature")


def legend(state):
    """(symbol, name, y, x) for each distinct symbol on the map now (from aipipe's
    cells); y, x is one square showing it, for its color."""
    rows, seen, out = state.get("map") or [], set(), []
    cells = sorted(state.get("cells", []),
                   key=lambda c: LEGEND_ORDER.index(c["kind"]) if c["kind"] in LEGEND_ORDER else 99)
    for c in cells:
        row = rows[c["y"]] if c["y"] < len(rows) else ""
        ch = row[c["x"] - 1] if 0 < c["x"] <= len(row) else "?"
        name = OBJECT_CLASSES.get(c.get("class"), c["name"]) if c["kind"] == "object" else c["name"]
        if (ch, name) not in seen:
            seen.add((ch, name))
            out.append((ch, name, c["y"], c["x"]))
    return out


def term_size():
    rows, cols = struct.unpack("hh", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 4))
    return rows, cols


def layout(rows, cols, helper_w=None):
    """Game pane width and height; the helper gets the rest of the columns.

    By default the game takes up to 130 columns (room beside the 80-column map
    for menus and the panel) before the helper drops below HELPER_W, down to 25.
    helper_w is the width the player dragged the helper to."""
    if helper_w:
        return max(80, cols - GX - 1 - max(20, helper_w)), rows - 1 - RULER
    game_w = max(80, min(cols - 26 - GX, max(130, cols - HELPER_W - 1 - GX)))
    return game_w, rows - 1 - RULER


class App:
    def __init__(self, scr, argv):
        self.scr = scr
        self.watcher = Watcher()
        self.helper = Helper()
        self.log = gamelog.GameLog(LOGS)
        self.hist_for = None  # the log file whose helper history is loaded
        self.helper.on_answer = lambda: self.helper.save(self.hist_path())
        self.held = None      # a dangerous key held back by the guard, sent if pressed again
        self.warned = set()   # warnings already shown (each shows once while it applies)
        self.seq = 0
        self.popup = None     # actions for a clicked inventory item: x, y, w, letter, text, acts
        self.search = None    # the ⌃G k search: query, sel, items, results
        self.selecting = False  # ⌃G v: frozen screen, drag a rectangle to copy
        self.sel = None         # (y0, x0, y1, x1) of the rectangle being dragged
        self.leader = False     # ⌃G pressed, waiting for its letter
        self.map_top = 1      # screen row of map row y=0 (found from the cursor on @)
        self.panel_items = {} # game-pane row -> inventory letter, for clicks
        self.panel_spans = {} # game-pane row -> [(col0, col1, action)]: filters, Done, Cancel
        self.inv_filter = None  # the inventory group shown (None: all)
        self.panel_on = False
        self.helper_w = None    # helper width once dragged
        self.legend_max = None  # legend lines once dragged
        self.legend_div = None  # screen row of the legend/chat divider
        self.drag = None        # ("v", x) or ("h", y) while a divider is dragged
        self.zoom = 0           # index into ZOOMS
        self.zoom_view = None   # (x0, y0, bw, bh, top, bottom) of the zoomed map on screen
        self.big = self.big_sent = None  # kitty: big-character escapes drawn / last sent
        self.img = self.img_sent = None  # picture zoom: what to show / what's on screen
        self.focus = "game"
        self.lock = threading.Lock()
        curses.start_color()
        curses.use_default_colors()
        curses.curs_set(1)
        curses.raw()  # ^C, ^Z, ^S belong to the game
        curses.nonl()
        self.pairs = {}
        rows, cols = term_size()
        self.gw, self.gh = layout(rows, cols)
        self.screen = pyte.Screen(self.gw, self.gh)
        self.stream = pyte.ByteStream(self.screen)
        self.stream.use_utf8 = False  # the game sends ASCII + ACS line drawing, which pyte skips in UTF-8 mode
        self.argv = argv
        self.saving = None    # "checkpoint", "load" or "new" while the wrapper has the game saving
        self.over = False     # the game ended (died or quit); the saves list is up
        self.snap_dlvl = None # dungeon level of the last automatic checkpoint
        self.load_target = None  # what to load once the game has saved: a saves.listing() item
        self.holding = False  # checkpoint/load in progress: don't draw the game restarting
        self.cursor_shown = True
        self.new_name = None  # the character to start for a new game
        self.saves_ui = None  # the ⌃G l list: items, sel, confirm, naming
        self.save_name = None # this character's save file name, once known
        self.spawn()
        self.resized = False
        signal.signal(signal.SIGWINCH, lambda *_: setattr(self, "resized", True))

    def spawn(self, name=None):
        """Start (or restart) the game, as character `name` if given; a saved game
        restores automatically."""
        if name:
            args, i = [], 0
            while i < len(self.argv):  # drop any -u NAME / -uNAME
                if self.argv[i] == "-u":
                    i += 2
                    continue
                if not self.argv[i].startswith("-u"):
                    args.append(self.argv[i])
                i += 1
            self.argv = args + ["-u", name]
        self.screen.reset()
        self.started = time.time()
        pid, self.fd = pty.fork()
        if pid == 0:
            os.chdir(GAME)
            os.environ["TERM"] = "xterm"
            os.environ["NETHACK_CONTROL"] = self.watcher.path
            os.environ.setdefault("NETHACK_REVEAL", "1")  # the helper sees the whole level; NETHACK_REVEAL= turns it off
            os.environ.setdefault("NETHACKOPTIONS", "@" + os.path.join(HERE, "nethackrc"))
            os.execv("./nethack", ["nethack"] + self.argv)
        self.pid = pid
        self._winsize()

    def send(self, data):
        """Keys to the game; dropped when there is no game (ended, or restarting)."""
        if self.over:
            return
        try:
            os.write(self.fd, data)
        except OSError:
            pass

    def say(self, kind, text):
        self.helper.scroll = 0
        self.helper.lines.append((kind, text))

    def save_game(self, why):
        """Have the game save and exit; game_exited() takes it from there."""
        st = self.watcher.state
        if self.saving or (st.get("context") or {}).get("kind") != "command":
            return False
        self.saving = why
        self.holding = True  # keep this screen up through the save and restart
        self.started = time.time()
        self.snap_info = st.get("status") or {}
        self.send(SAVE_KEYS)
        return True

    def game_exited(self):
        """The game process ended: finish a checkpoint, load or new game, or (after
        a death) put up the saves list. False means the wrapper should quit."""
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
        os.close(self.fd)
        files = sorted((os.path.join(SAVES, f) for f in os.listdir(SAVES)), key=os.path.getmtime)
        fresh = [f for f in files if os.path.getmtime(f) >= self.started]
        why, self.saving = self.saving, None
        if why and fresh:
            save = fresh[-1]
            self.save_name = os.path.basename(save)
            self.checkpoint(save)  # whatever happens next, this point is kept
            if why == "load":
                self.load(self.load_target)
            elif why == "new":
                self.spawn(self.new_name)
            else:
                self.spawn()
            return True
        if fresh:  # the player saved (S): done for now
            return False
        if not self.save_name or not saves.snapshots(SNAPS, self.save_name):
            return False  # nothing of this character's to go back to (never offer someone else's)
        self.over = True
        self.log.event("game over")
        self.open_saves()
        self.say("err", "Game over. Pick a checkpoint and press Enter to play on from there; q quits.")
        return True

    def hist_path(self):
        return self.log.path[:-4] + ".helper.json" if self.log.path else None

    def checkpoint(self, save):
        """Keep a copy of a just-saved game."""
        os.makedirs(SNAPS, exist_ok=True)
        info = self.snap_info
        snap = os.path.join(SNAPS, f"{os.path.basename(save)}@{info.get('turn', 0):06d}-D{info.get('dlvl', 0)}")
        shutil.copy2(save, snap)
        self.log.event(f"checkpoint saved (Dlvl {info.get('dlvl')}, turn {info.get('turn')})")
        self.log.copy_to(snap + ".log")  # the log as of this checkpoint
        self.helper.save(self.hist_path())
        if self.hist_path() and os.path.exists(self.hist_path()):
            shutil.copy2(self.hist_path(), snap + ".helper.json")  # and the helper conversation
        for old in saves.snapshots(SNAPS, self.save_name)[:-KEEP_SNAPS]:
            os.unlink(old)
        self.say("dim", f"Checkpoint saved (Dlvl {info.get('dlvl')}, turn {info.get('turn')}). ⌃G r goes back to the last one.")

    def load(self, item):
        """Start the game from a saves.listing() item (a checkpoint or a saved game)."""
        if item["kind"] == "snap":
            shutil.copy2(item["path"], os.path.join(SAVES, item["base"]))
            self.log.restore(item["path"] + ".log", item["char"])  # the log goes back to then too
            if self.helper.load(item["path"] + ".helper.json"):  # and the helper conversation
                self.helper.save(self.hist_path())
            self.hist_for = self.log.path
        self.log.event(f"loaded {item['char']}: {item['what']}")
        self.save_name = item["base"]
        self.over = False
        self.say("dim", f"Loaded {item['char']}: {item['what']}.")
        self.spawn(item["char"])

    def request_load(self, item):
        """Load now if no game is running, else save the running game first."""
        if self.over:
            self.load(item)
        elif self.save_game("load"):
            self.load_target = item
        else:
            self.say("dim", "Loading works at the command prompt; finish this first.")

    def open_saves(self):
        items = saves.listing(SAVES, SNAPS)
        sel = next((k for k, i in enumerate(items) if i["base"] == self.save_name), 0)  # start on this character
        self.saves_ui = dict(items=items, sel=sel, confirm=None, naming=None)

    def close_saves(self):
        self.saves_ui = None
        self.screen.dirty.update(range(self.gh))

    def draw_saves(self):
        u = self.saves_ui
        y, x, w = 1, 2, min(self.gw - 4, 90)
        title = (f" New game, name: {u['naming']}_" if u["naming"] is not None else
                 " Delete this? d again to confirm, anything else cancels" if u["confirm"] == "d" else
                 " Keep only the newest 3 checkpoints of this character? p again to confirm" if u["confirm"] == "p" else
                 " Saves: Enter load  d delete  p prune to newest 3  n new game  Esc close")
        edge = "+" + "-" * (w - 2) + "+"
        self.gput(y, x, edge, curses.A_BOLD)
        self.gput(y + 1, x, "|" + title.ljust(w - 2)[:w - 2] + "|", curses.A_BOLD)
        n = 14
        first = max(0, min(u["sel"] - n // 2, len(u["items"]) - n))
        for i in range(n):
            k = first + i
            it = u["items"][k] if k < len(u["items"]) else None
            line = f" {it['char'][:14]:<14} {it['what']:<24} {it['when']}" if it else ""
            if not u["items"] and i == 0:
                line = " (no saved games or checkpoints yet)"
            self.gput(y + 2 + i, x, "|" + line.ljust(w - 2)[:w - 2] + "|",
                      curses.A_REVERSE if it and k == u["sel"] else 0)
        self.gput(y + 2 + n, x, edge, curses.A_BOLD)

    def saves_key(self, data):
        """Keys while the saves list is up; False means quit (q after a death)."""
        u = self.saves_ui
        items, sel = u["items"], u["sel"]
        if u["naming"] is not None:  # typing a new character's name
            if data in (b"\r", b"\n"):
                name = u["naming"].strip()
                self.close_saves()
                if name:
                    self.new_game(name)
            elif data == b"\x1b":
                u["naming"] = None
            elif data in (b"\x7f", b"\x08"):
                u["naming"] = u["naming"][:-1]
            else:
                u["naming"] += "".join(c for c in data.decode("latin-1") if c.isalnum())[:20]
            return
        if u["confirm"]:
            what, u["confirm"] = u["confirm"], None
            if data.decode("latin-1") == what and items:
                it = items[sel]
                if what == "d":
                    saves.remove(it["path"])
                    self.say("dim", f"Deleted {it['char']}: {it['what']}.")
                else:
                    gone = saves.prune(SNAPS, it["base"], keep=3)
                    self.say("dim", f"Pruned {gone} older checkpoints of {it['char']}.")
                u["items"] = saves.listing(SAVES, SNAPS)
                u["sel"] = min(sel, max(0, len(u["items"]) - 1))
            return
        if data in UP or data in DOWN:
            u["sel"] = max(0, min(len(items) - 1, sel + (1 if data in DOWN else -1)))
        elif data in (b"\r", b"\n") and items:
            self.close_saves()
            self.request_load(items[sel])
        elif data in (b"d", b"p") and items:
            u["confirm"] = data.decode()
        elif data == b"n":
            u["naming"] = ""
        elif data == b"q" and self.over:
            return False
        elif data == b"\x1b" and not self.over:
            self.close_saves()

    def new_game(self, name):
        if any(saves.char_name(f) == name for f in os.listdir(SAVES)):
            self.say("err", f"{name} already has a saved game; that one will load. Delete it first for a fresh start.")
        self.new_name = name
        if self.over:
            self.over = False
            self.spawn(name)
        elif not self.save_game("new"):
            self.say("dim", "A new game starts from the command prompt; finish this first.")

    def _winsize(self):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("hhhh", self.gh, self.gw, 0, 0))

    def _resize(self):
        self.resized = False
        rows, cols = term_size()
        curses.resizeterm(rows, cols)
        self.gw, self.gh = layout(rows, cols, self.helper_w)
        self.screen.resize(self.gh, self.gw)
        self._winsize()
        os.kill(self.pid, signal.SIGWINCH)
        self.scr.clear()
        self.big_sent = None  # kitty: the big characters were cleared too
        self.img_sent = None  # and the map picture
        self.screen.dirty.update(range(self.gh))

    def color(self, fg, bg, bold):
        f = COLORS.get(fg.removeprefix("bright"), -1)
        b = COLORS.get(bg.removeprefix("bright"), -1)
        if f != -1 and (bold or fg.startswith("bright")) and curses.COLORS >= 16:
            f += 8
        key = (f, b)
        if key not in self.pairs:
            n = len(self.pairs) + 1
            if n >= curses.COLOR_PAIRS:
                return 0
            curses.init_pair(n, f, b)
            self.pairs[key] = n
        return curses.color_pair(self.pairs[key])

    def move_cursor(self, y, x):
        """Park the cursor, clamped to the screen (a narrow terminal can't fit the game)."""
        rows, cols = self.scr.getmaxyx()
        try:
            self.scr.move(max(0, min(rows - 1, y)), max(0, min(cols - 1, x)))
        except curses.error:
            pass

    def put(self, y, x, s, attr=0):
        try:
            self.scr.addstr(y, x, s, attr)
        except curses.error:  # the bottom-right cell; curses moves past it
            pass

    def gput(self, y, x, s, attr=0):
        """put() in game-pane coordinates (right of the gutter)."""
        self.put(y, x + GX, s, attr)

    def row_text(self, r):
        return "".join(c.data or " " for c in (self.screen.buffer[r][i] for i in range(self.gw))).rstrip()

    def status_rows(self):
        """The game's two bottom status lines, if that's what the bottom rows hold now."""
        rows = [self.gh - 2, self.gh - 1]
        return rows if any(re.search(r"\bHP:-?\d", self.row_text(r)) for r in rows) else []

    def panel_visible(self):
        """The panel shows when there's room beside the map and a game going."""
        return self.gw - MAP_W - 1 >= 20 and bool(self.watcher.state.get("status"))

    def beside_rows(self):
        """Rows where the game has a box or menu beside the map (the panel gives them up)."""
        skip, buf = self.status_rows(), self.screen.buffer
        return {r for r in range(PANEL_TOP, self.gh) if r not in skip
                and any(buf[r][c].data not in (" ", "") for c in range(MAP_W, self.gw))}

    def overlay(self):
        """Is the game drawing over the map (a box or menu covering it)? The screen differs
        from the map the game reports."""
        rows, top, buf = self.watcher.state.get("map") or [], self.map_top, self.screen.buffer
        return any((buf[top + y][x - 1].data or " ").translate(ASCII) != row[x - 1]
                   for y, row in enumerate(rows) if top + y < self.gh
                   for x in range(1, min(MAP_W, len(row) + 1)))

    def cell_attr(self, c):
        attr = self.color(c.fg, c.bg, c.bold)
        if c.bold:
            attr |= curses.A_BOLD
        if c.reverse:
            attr |= curses.A_REVERSE
        if c.underscore:
            attr |= curses.A_UNDERLINE
        return attr

    def zoom_active(self):
        """Zoomed drawing only while the map is what's on screen (not menus, cursor picks...)."""
        st = self.watcher.state
        if not (self.zoom > 0 and st.get("player")) or self.popup or self.search or self.saves_ui:
            return False
        kind = (st.get("context") or {}).get("kind")
        if kind in ("command", "yn", "more"):
            return True
        # boxes and menus beside the map, prompts on the message line: the map is still
        # uncovered, so stay zoomed; a cursor pick (a bare key wait with nothing beside the
        # map) or anything drawn over the map shows the normal map
        return not self.overlay() and (kind != "key" or bool(self.beside_rows()))

    def set_zoom(self, step):
        self.zoom = max(0, min(len(ZOOMS) - 1, self.zoom + step))
        self.screen.dirty.update(range(self.gh))

    def draw_zoom(self):
        """The map region, each square drawn as a block of its character, around you."""
        if not self.zoom_active():
            if self.zoom_view:
                self.zoom_view = None
                self.screen.dirty.update(range(self.gh))
                if KITTY:
                    self.scr.redrawwin()  # repaint every cell, so no big characters are left
            return
        bw, bh = ZOOMS[self.zoom]
        top, bottom = self.map_top, self.gh if self.panel_on else self.gh - 2
        you = self.watcher.state["player"]
        ncols, nrows = int(MAP_W // bw), int((bottom - top) // bh)
        x0 = max(1, min(MAP_W - ncols, you["x"] - ncols // 2))
        y0 = max(0, min(MAP_H - nrows, you["y"] - nrows // 2)) if nrows < MAP_H else 0
        self.zoom_view = (x0, y0, bw, bh, top, bottom)
        buf, big, grid = self.screen.buffer, [], [[] for _ in range(nrows)]
        if GRAPHICS:  # blank the map area; the picture goes over it
            for r in range(top, bottom):
                self.gput(r, 0, " " * MAP_W)
            for j in range(nrows):
                y = y0 + j
                if y < MAP_H and top + y < self.gh:
                    grid[j] = [((buf[top + y][x - 1].data or " ").translate(ASCII),) +
                               (buf[top + y][x - 1].fg, buf[top + y][x - 1].bold, buf[top + y][x - 1].reverse)
                               for x in range(x0, min(MAP_W, x0 + ncols))]
        for r in range(top, bottom) if not GRAPHICS else ():
            j, k = divmod(r - top, bh)
            y = y0 + j
            for i in range(ncols):
                x = x0 + i
                if j < nrows and y < MAP_H and x < MAP_W and top + y < self.gh:
                    c = buf[top + y][x - 1]
                    ch = (c.data or " ").translate(ASCII)
                    if KITTY or GRAPHICS:  # curses keeps the block blank; the terminal draws over it
                        self.gput(r, i * bw, " " * bw)
                        if k == 0 and KITTY:  # blanks too: they clear an old big character
                            big.append(big_char(r, GX + i * bw, bw, ch, c))
                        elif k == 0 and j < len(grid) and i < MAP_W:
                            grid[j].append((ch, c.fg, c.bold, c.reverse))
                    else:
                        self.gput(r, i * bw, ch * bw, self.cell_attr(c))
                else:
                    self.gput(r, i * bw, " " * bw)
            self.gput(r, ncols * bw, " " * (MAP_W - ncols * bw))
        self.screen.dirty.update(range(top, bottom))  # redraw normally when zoom ends
        self.big = "".join(big)
        grid = [row for row in grid if row]
        self.img = (top, bw, bh, tuple(map(tuple, grid))) if grid else None

    def cell_pixels(self):
        """A character cell's size in pixels, from the terminal (or a guess)."""
        try:
            rows, cols, xp, yp = struct.unpack("HHHH", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 8))
            if xp and yp:
                return xp // cols, yp // rows
        except OSError:
            pass
        return 9, 18

    def show_image(self):
        """Picture zoom: draw the zoomed map as an image over its cells, or take it away."""
        want = self.img if self.zoom_view else None
        if want == self.img_sent:
            return
        if want:
            top, sw, sh, grid = want
            cw, ch = self.cell_pixels()
            png = mapimage.render(grid, cw, ch, sw, sh)
            out = mapimage.place(png, top, GX, round(len(grid[0]) * sw), round(len(grid) * sh))
        else:
            out = mapimage.delete()
        sys.stdout.write("\x1b7" + out + "\x1b8")  # keep curses' cursor and colors
        sys.stdout.flush()
        self.img_sent = want

    def draw_game(self):
        buf = self.screen.buffer
        on = self.panel_visible()
        if on != self.panel_on:  # repaint what the panel covered, or uncovered
            self.panel_on = on
            self.screen.dirty.update(range(self.gh))
        hide = self.status_rows() if on else []  # they're shown in the panel instead
        for y in sorted(self.screen.dirty):
            if y >= self.gh:
                continue
            if y in hide:
                self.gput(y, 0, " " * self.gw)
                continue
            line = buf[y]
            for x in range(self.gw):
                c = line[x]
                self.gput(y, x, (c.data or " ").translate(ASCII), self.cell_attr(c))
        self.screen.dirty.clear()

    def draw_axes(self):
        """Row numbers (y) in the gutter and column numbers (x) under the game."""
        you = self.watcher.state.get("player") or {}
        if self.zoom_view:
            x0, y0, bw, bh, top, bottom = self.zoom_view
            rows = {top + int((y - y0) * bh): y for y in range(y0, MAP_H)}  # screen row of each map row
            for r in range(self.gh):
                y = rows.get(r) if top <= r < bottom else None
                self.put(r, 0, f"{y:2d} " if y is not None else "   ",
                         curses.A_REVERSE if y is not None and y == you.get("y") else curses.A_DIM)
            self.put(self.gh, 0, " " * (GX + MAP_W))
            self.put(self.gh + 1, 0, " x ", curses.A_DIM)
            self.gput(self.gh + 1, 0, " " * MAP_W)
            free = 0  # first column not yet used by a label
            for x in range(x0, MAP_W):
                col = int((x - x0) * bw)
                if col >= MAP_W:
                    break
                if col >= free and (bw >= 2 or x % 5 == 0 or x == you.get("x")):
                    self.gput(self.gh + 1, col, str(x), curses.A_REVERSE if x == you.get("x") else curses.A_DIM)
                    free = col + len(str(x)) + 1
            self.gput(self.gh + 1, MAP_W + 1, f"you: x={you['x']} y={you.get('y')}  zoom {bw:g}x".ljust(24), curses.A_BOLD)
            return
        for r in range(self.gh):
            y = r - self.map_top
            label = f"{y:2d} " if 0 <= y < MAP_H else "   "
            self.put(r, 0, label, curses.A_REVERSE if y == you.get("y") else curses.A_DIM)
        tens = "".join(str(x // 10) if x % 10 == 0 else " " for x in range(1, MAP_W))
        units = "".join(str(x % 10) for x in range(1, MAP_W))
        self.put(self.gh, 0, "   ", 0)
        self.put(self.gh + 1, 0, " x ", curses.A_DIM)
        self.gput(self.gh, 0, tens, curses.A_DIM)
        self.gput(self.gh + 1, 0, units, curses.A_DIM)
        if you.get("x"):
            col = you["x"] - 1
            self.gput(self.gh, col, tens[col], curses.A_REVERSE)
            self.gput(self.gh + 1, col, units[col], curses.A_REVERSE)
            self.gput(self.gh + 1, MAP_W + 1, f"you: x={you['x']} y={you.get('y')}".ljust(24), curses.A_BOLD)

    def inventory_menu(self):
        """When the game shows a menu of your own items beside the map (D, i, multi-pick):
        {"title", "items": {letter: selected}}; None for other menus and paged ones."""
        if (self.watcher.state.get("context") or {}).get("kind") != "menu":
            return None
        inv = {i["letter"]: i["text"] for i in self.watcher.state.get("inventory", [])}
        title, items, matched = None, {}, 0
        for r in sorted(self.beside_rows()):
            raw = self.row_text(r).translate(ASCII)[MAP_W:].lstrip("|")  # keep the selection column (" a)" / "<a>")
            text = raw.strip().strip("|+-").strip()
            if "(Page" in text:
                return None  # items on other pages aren't on screen
            m = MENU_LINE.match(raw.rstrip().rstrip("|"))
            if m:
                items[m.group(2)] = m.group(1) == "<"
                matched += inv.get(m.group(2), "").endswith(m.group(4).strip())
            elif text and title is None:
                title = text
        if not items or matched * 2 < len(items):
            return None
        return {"title": title or "Choose", "items": items}

    def inventory_lines(self, w):
        """The one inventory list: grouped, filtered, in-use items green, and the place
        where the game's item questions and item menus are answered."""
        st = self.watcher.state.get("status") or {}
        inv = self.watcher.state.get("inventory", [])
        yellow = self.color("yellow", "default", True) | curses.A_BOLD
        menu, asked = self.inventory_menu(), guard.asked_letters(self.watcher.state)
        if menu:
            head = [(f"{menu['title']}  Click items, then Done:", yellow, None)]
        elif asked:
            head = [(f"{asked[0]} Click one:", yellow, None)]
        else:
            head = [("Inventory (click an item)".ljust(w - 6) + "weight", curses.A_DIM, None)]
        present = [(sym, name) for sym, name in INV_GROUPS if any(i.get("class") == sym for i in inv)]
        if self.inv_filter not in [sym for sym, _ in present]:
            self.inv_filter = None
        lines, text, spans = head, "Show: ", []
        for sym, name in [(None, "All")] + present:  # the filter rows: click a group to show only it
            label = f"[{name}]" if sym == self.inv_filter else name
            if spans and len(text) + len(label) > w:
                lines.append((text, curses.A_DIM, spans))
                text, spans = "      ", []
            spans.append((len(text), len(text) + len(label), ("filter", sym)))
            text += label + "  "
        lines.append((text, curses.A_DIM, spans))
        green = self.color("green", "default", True)
        for sym, name in present:
            if self.inv_filter not in (None, sym):
                continue
            lines.append((name, curses.A_UNDERLINE, None))
            for i in (i for i in inv if i.get("class") == sym):
                attr, mark = (green if IN_USE.search(i["text"]) else 0), " "
                if menu:
                    sel = menu["items"].get(i["letter"])
                    mark = "✓" if sel else " " if sel is not None else "·"
                    attr = (attr | curses.A_BOLD) if sel is not None else curses.A_DIM
                elif asked:
                    fits = i["letter"] in asked[1]
                    mark, attr = (">", attr | curses.A_BOLD) if fits else (" ", curses.A_DIM)
                row = f"{mark}{i['letter']}) {i['text']}"
                if i.get("weight") is not None:  # weight, right-aligned (whole stack)
                    row = row[:w - 6].ljust(w - 5) + f"{i['weight']:>5}"
                lines.append((row, attr, i["letter"]))
        if inv and all("weight" in i for i in inv):  # total under the weights, and the capacity
            total = sum(i["weight"] for i in inv)
            label = f"Total ({st.get('capacity')} before you're Burdened)" if st.get("capacity") else "Total"
            lines.append((label[:w - 6].ljust(w - 5) + f"{total:>5}", curses.A_BOLD, None))
        if menu:
            lines.append(("[ Done ]   [ Cancel ]", yellow, [(0, 8, ("keys", b"\r")), (11, 21, ("keys", b"\x1b"))]))
        return lines

    def draw_panel(self):
        """Status, location and inventory beside the map, unless the game has a menu there."""
        self.panel_items, self.panel_spans = {}, {}
        if not self.panel_on:
            return
        w = self.gw - MAP_W - 1
        st, you = self.watcher.state.get("status"), self.watcher.state.get("player") or {}
        hp, hpmax = st.get("hp", 0), st.get("hpmax", 1) or 1
        frac = hp / hpmax
        hp_col = "green" if frac >= 1 else "yellow" if frac >= .5 else "red"
        s_ = st.get("str", 0)
        strength = f"18/{s_ - 18:02d}" if 18 < s_ <= 117 else "18/**" if s_ == 118 else str(s_ - 100 if s_ > 118 else s_)
        flags = [f for f in [st.get("hunger"), st.get("encumbrance")] + st.get("conditions", []) if f]
        rev = self.watcher.state.get("reveal") or {}
        pray = rev.get("prayer") or {}
        more = [(f"Carrying {st.get('weight')}/{st.get('capacity')} wt   Speed {st.get('speed')}", 0, None),
                (f"Next level at {st.get('next_exp')} xp   God: {st.get('god')}", 0, None)]
        if pray:  # hidden numbers, from the cheat
            more.append((f"Luck {pray.get('luck')}  Prayer timeout {pray.get('timeout')}  "
                         f"Nutrition {rev.get('nutrition')}  Alignment {rev.get('align_record')}",
                         self.color("magenta", "default", False), None))
            more += [(l, self.color("magenta", "default", False), None)
                     for l in textwrap.wrap("Intrinsics: " + (", ".join(rev.get("intrinsics", [])) or "none"), w)]
        for pet in rev.get("pets", []):  # tame monsters, with the hidden numbers in magenta
            name = f"{pet['name']} the {pet['species']}" if pet["name"] else pet["species"]
            more.append((f"Pet: {name}  L{pet['level']}  HP {pet['hp']}/{pet['hpmax']}  AC {pet['ac']}  "
                         f"Spd {pet['speed']}", curses.A_BOLD, None))
            hunger = pet.get("turns_until_hungry")
            hunger = "?" if hunger is None else "hungry now" if hunger < 0 else f"hungry in {hunger}"
            more += [(l, self.color("magenta", "default", False), None) for l in textwrap.wrap(
                f"  tame {pet['tameness']}/20, {hunger}, at x={pet['x']} y={pet['y']}"
                + (", leashed" if pet["leashed"] else "")
                + (", carrying " + ", ".join(pet["carrying"]) if pet["carrying"] else ""), w)]
        lines = [(f"{st.get('gender', '').capitalize()} {st.get('race', '')} {st.get('role', '')}, "
                  f"{st.get('alignment', '')}", curses.A_BOLD, None),
                 (f"HP {hp}/{hpmax}", self.color(hp_col, "default", True) | curses.A_BOLD, None),
                 (f"Pw {st.get('pw')}/{st.get('pwmax')}   AC {st.get('ac')}", 0, None),
                 (f"Xp {st.get('xlvl')}/{st.get('exp')}   $ {st.get('gold')}   T {st.get('turn')}", 0, None),
                 (f"Dlvl {st.get('dlvl')}  {st.get('dungeon', '')}", 0, None),
                 (f"Location x={you.get('x')} y={you.get('y')}", curses.A_BOLD, None),
                 (f"St {strength} Dx {st.get('dex')} Co {st.get('con')} In {st.get('int')} "
                  f"Wi {st.get('wis')} Ch {st.get('cha')}", 0, None)] + more + [
                 (" ".join(flags), self.color("yellow", "default", True) | curses.A_BOLD, None),
                 ]
        lines += self.inventory_lines(w)
        lines.append(("", 0, None))
        status = "  ".join(re.sub(r"  +", "  ", self.row_text(r)).strip() for r in self.status_rows())
        lines += [(l, 0, None) for l in textwrap.wrap(status, w)]  # the game's status lines, as one
        # the game's box beside the map keeps its rows, unless it's a list of your items
        # (then this panel is the list: inventory_lines() shows it)
        taken = set() if self.inventory_menu() else self.beside_rows()
        free = [r for r in range(PANEL_TOP, self.gh) if r not in taken]
        for r in free:
            self.gput(r, MAP_W, "|")  # map | panel
        for n, r in enumerate(free):
            text, attr, letter = lines[n] if n < len(lines) else ("", 0, None)
            if r == free[-1] and len(lines) > n + 1:
                text, letter = "...", None
            self.gput(r, MAP_W + 1, text[:w].ljust(w), attr)
            if isinstance(letter, str):
                self.panel_items[r] = letter
            elif letter:  # clickable spans on this row: filter names, Done, Cancel
                self.panel_spans[r] = letter

    def draw_helper(self):
        rows, cols = self.scr.getmaxyx()
        x0, w = GX + self.gw + 1, cols - GX - self.gw - 1
        if w < 10:
            return
        for y in range(rows - 1):
            self.put(y, GX + self.gw, "|")  # game | helper, drag to resize
        top = 0
        entries = legend(self.watcher.state)
        if entries:  # the map legend, packed into lines across the pane, symbols in their map colors
            lines, cur, width = [], [], 0
            for e in entries:
                n = len(e[0]) + 1 + len(e[1])
                if cur and width + 2 + n > w - 1:
                    lines.append(cur)
                    cur, width = [], 0
                cur.append(e)
                width += n + (2 if width else 0)
            lines.append(cur)
            lines = lines[:self.legend_max or max(3, rows // 3)]
            if self.legend_max:  # the height it was dragged to
                lines += [[]] * (self.legend_max - len(lines))
            for y, line in enumerate(lines):
                self.put(y, x0, " " * (w - 1))
                col = x0
                for ch, name, my, mx in line:
                    r = self.map_top + my
                    cell = self.screen.buffer[r][mx - 1] if 0 <= r < self.gh and 0 < mx <= self.gw else None
                    self.put(y, col, ch, (self.cell_attr(cell) if cell else 0) | curses.A_BOLD)
                    self.put(y, col + 1, f" {name}"[:max(0, x0 + w - 1 - col - 1)], curses.A_BOLD)
                    col += len(ch) + 1 + len(name) + 2
            top = len(lines)
            self.put(top, x0 - 1, "+" + "-" * (w - 1))  # legend | chat, drag to resize
            self.legend_div = top
            top += 1
        else:
            self.legend_div = None
        body = []
        for kind, text in self.helper.lines:
            attr = {"you": curses.A_BOLD, "dim": curses.A_DIM,
                    "err": self.color("red", "default", False),
                    "warn": self.color("yellow", "default", True) | curses.A_BOLD}.get(kind, 0)
            for para in text.split("\n"):
                body += [(attr, l) for l in (textwrap.wrap(para, w - 1) or [""])]
            body.append((0, ""))
        if self.helper.busy:
            body.append((curses.A_DIM, "thinking..."))
        h = rows - 4 - top
        self.put(rows - 3, x0 - 1, "+" + "-" * (w - 1))  # chat | input
        self.helper.scroll = max(0, min(self.helper.scroll, len(body) - h))
        body = body[max(0, len(body) - h - self.helper.scroll):len(body) - self.helper.scroll]
        for y in range(h):
            attr, l = body[y] if y < len(body) else (0, "")
            self.put(top + y, x0, l.ljust(w - 1)[:w - 1], attr)
        mark = curses.A_REVERSE if self.focus == "helper" else curses.A_DIM
        self.put(rows - 2, x0, ("> " + self.helper.input)[-(w - 1):].ljust(w - 1), mark)

    def draw_bar(self):
        rows, cols = self.scr.getmaxyx()
        where = "HELPER (Enter asks, Esc back)" if self.focus == "helper" else "GAME"
        self.put(rows - 1, 0, f" {BAR}  |  typing goes to: {where} ".ljust(cols - 1)[:cols - 1],
                 curses.A_REVERSE)

    def redraw(self):
        if self.selecting:  # frozen while a rectangle is being selected
            return
        self.paint()

    SELECT_BAR = " SELECT: drag a rectangle, let go to copy it.  ⌃G v or Esc: back to the game "

    def select_mouse(self, b, x, y, press):
        """Select mode: drag a rectangle, release copies exactly that text."""
        rows, cols = self.scr.getmaxyx()
        y, x = max(0, min(rows - 2, y)), max(0, min(cols - 1, x))  # stay on screen, above the bar
        if press and b == 0:
            self.sel = (y, x, y, x)
        elif press and b == 32 and self.sel:
            self.sel = self.sel[:2] + (y, x)
        elif not press and self.sel:
            y0, x0, y1, x1 = self.sel
            top, bot, left, right = min(y0, y1), max(y0, y1), min(x0, x1), max(x0, x1)
            text = "\n".join(self.scr.instr(r, left, right - left + 1).decode(errors="replace").rstrip()
                             for r in range(top, bot + 1)) + "\n"
            subprocess.run(["pbcopy"], input=text, text=True)
            self.sel = None
            self.paint(bar=f" Copied {right - left + 1}x{bot - top + 1} to the clipboard. Drag again, or ⌃G v/Esc: back to the game ")
            return
        else:
            return
        self.paint(bar=self.SELECT_BAR)
        y0, x0, y1, x1 = self.sel
        for r in range(min(y0, y1), max(y0, y1) + 1):
            self.scr.chgat(r, min(x0, x1), abs(x1 - x0) + 1, curses.A_REVERSE)
        self.scr.refresh()

    def paint(self, bar=None):
        bar = bar or (LEADER_BAR if self.leader else None)
        if self.holding and time.time() - self.started > 5:
            self.holding = False  # the restart is taking long: show what's there
            self.screen.dirty.update(range(self.gh))
        with self.lock:
            if not self.holding:  # while the game saves and restarts, the last screen stays up
                self.draw_game()
                self.draw_zoom()
                self.draw_axes()
                self.draw_panel()
            if self.popup:
                self.draw_popup()
            if self.search:
                self.draw_search()
            if self.saves_ui:
                self.draw_saves()
            self.draw_helper()
            self.draw_bar()
            if bar:
                self.put(self.scr.getmaxyx()[0] - 1, 0, bar.ljust(self.scr.getmaxyx()[1] - 1),
                         curses.A_REVERSE | curses.A_BOLD)
            if self.drag:  # where the divider will go
                rows, cols = self.scr.getmaxyx()
                if self.drag[0] == "v":
                    for y in range(rows - 1):
                        self.put(y, self.drag[1], "#", curses.A_REVERSE)
                else:
                    self.put(self.drag[1], GX + self.gw + 1, "#" * (cols - GX - self.gw - 2), curses.A_REVERSE)
            show = not (GRAPHICS and self.zoom_view and self.focus == "game")  # the big @ marks you
            if show != self.cursor_shown:
                self.cursor_shown = show
                try:
                    curses.curs_set(1 if show else 0)
                except curses.error:
                    pass
            you = self.watcher.state.get("player")  # none for a moment while the game restarts
            if self.focus == "game" and self.zoom_view and you:
                x0, y0, bw, bh, top, _ = self.zoom_view
                self.move_cursor(min(top + int((you["y"] - y0) * bh), self.gh - 1), GX + int((you["x"] - x0) * bw))
            elif self.focus == "game":
                self.move_cursor(min(self.screen.cursor.y, self.gh - 1), GX + min(self.screen.cursor.x, self.gw - 1))
            else:
                rows, _ = self.scr.getmaxyx()
                self.move_cursor(rows - 2, min(GX + self.gw + 3 + len(self.helper.input), self.scr.getmaxyx()[1] - 2))
            self.scr.refresh()
            if KITTY and self.zoom_view and self.big != self.big_sent:
                # after curses: save cursor and colors, draw the big characters, restore
                sys.stdout.write("\x1b7" + self.big + "\x1b8")
                sys.stdout.flush()
            self.big_sent = self.big if self.zoom_view else None
            if GRAPHICS:
                self.show_image()

    def helper_key(self, data):
        if data in (b"\x1b[5~", b"\x1b[6~"):  # Page Up / Page Down scroll the conversation
            self.helper.scroll += 10 if data == b"\x1b[5~" else -10
            return
        for b in data:
            ch = chr(b)
            if b == 27:
                self.focus = "game"
                return
            if ch in "\r\n":
                q = self.helper.input.strip()
                self.helper.input = ""
                if q:
                    self.ask(q)
            elif b in (8, 127):
                self.helper.input = self.helper.input[:-1]
            elif b == 21:  # ^U clears the line
                self.helper.input = ""
            elif ch.isprintable():
                self.helper.input += ch

    def open_popup(self, x, y, letter):
        item = next((i for i in self.watcher.state.get("inventory", []) if i["letter"] == letter), None)
        if not item:
            return
        acts = guard.item_actions(item.get("class", ""), item["text"])
        title = f"{letter} - {item['text']}"
        w = min(max(len(title), 18) + 2, MAP_W - 2)
        self.popup = dict(x=max(0, MAP_W - w - 1), y=max(0, min(y, self.gh - len(acts) - 3)), w=w,
                          letter=letter, text=item["text"], acts=acts)

    def close_popup(self):
        self.popup = None
        self.screen.dirty.update(range(self.gh))  # repaint what it covered

    def draw_popup(self):
        p = self.popup
        lines = [f"{p['letter']} - {p['text']}"[:p["w"] - 2]] + [f" {k} - {label}" for k, label in p["acts"]]
        edge = "+" + "-" * (p["w"] - 2) + "+"
        self.gput(p["y"], p["x"], edge, curses.A_BOLD)
        for i, l in enumerate(lines):
            self.gput(p["y"] + 1 + i, p["x"], "|" + l.ljust(p["w"] - 2) + "|", curses.A_BOLD if i == 0 else 0)
        self.gput(p["y"] + 1 + len(lines), p["x"], edge, curses.A_BOLD)

    def choose(self, key):
        p = self.popup
        self.close_popup()
        self.item_action(key, p["letter"], p["text"])

    def item_action(self, key, letter, text):
        """Do an inventory action: the command key, then the item's letter."""
        p = dict(letter=letter, text=text)
        if key == "?":
            self.ask(f"About my {p['text']} (inventory letter {p['letter']}): what is it, and what should I do with it?")
            return
        held = ("item", key, p["letter"])
        if key in guard.ITEM_PROMPTS and self.held != held:
            why = guard.check(dict(self.watcher.state, context={"kind": "yn", "prompt": guard.ITEM_PROMPTS[key]}),
                              p["letter"].encode())
            if why:
                self.held = held
                self.say("err", f"HELD: {why} Choose it again to do it anyway.")
                return
        self.held = None
        self.send((key + p["letter"]).encode())

    def popup_key(self, data):
        keys = [k for k, _ in self.popup["acts"]]
        if data.decode("latin-1") in keys:
            self.choose(data.decode("latin-1"))
        else:
            self.close_popup()

    def copy_screen(self):
        """The game pane as plain text on the macOS clipboard."""
        text = "\n".join(r.translate(ASCII).rstrip() for r in self.screen.display).strip("\n") + "\n"
        try:
            subprocess.run(["pbcopy"], input=text, text=True, check=True)
            self.say("dim", f"Copied the game screen ({text.count(chr(10))} lines) to the clipboard.")
        except (OSError, subprocess.CalledProcessError) as e:
            self.say("err", f"Copy failed: {e}")

    def open_search(self):
        self.search = dict(query="", sel=0, items=palette.entries(self.watcher.state, COMMANDS, EXTRAS))
        self.search["results"] = palette.search("", self.search["items"])

    def close_search(self):
        self.search = None
        self.screen.dirty.update(range(self.gh))

    def search_box(self):
        return 1, 2, min(self.gw - 4, 90)  # y, x, width

    def draw_search(self):
        y, x, w = self.search_box()
        q, res = self.search, self.search["results"]
        edge = "+" + "-" * (w - 2) + "+"
        self.gput(y, x, edge, curses.A_BOLD)
        self.gput(y + 1, x, "|" + f" Search: {q['query']}_".ljust(w - 2)[:w - 2] + "|", curses.A_BOLD)
        for i in range(12):
            e = res[i] if i < len(res) else None
            line = f" {e['label'][:30]:<30} {e['detail']}" if e else ""
            attr = curses.A_REVERSE if e and i == q["sel"] else 0
            self.gput(y + 2 + i, x, "|" + line.ljust(w - 2)[:w - 2] + "|", attr)
        self.gput(y + 14, x, edge, curses.A_BOLD)

    def run_entry(self, e):
        self.close_search()
        act = e["action"]
        if act[0] == "keys":
            self.send(act[1])
        elif act[0] == "item":
            self.item_action(*act[1:])
        elif act[0] == "goto":
            self.send(f"#goto\r{act[1]} {act[2]}\r".encode())
        elif act[0] == "fkey":
            self.handle_key(act[1])

    def search_key(self, data):
        q = self.search
        if data == b"\x1b":
            self.close_search()
            return
        if data in (b"\r", b"\n"):
            if q["results"]:
                self.run_entry(q["results"][q["sel"]])
            return
        if data in UP or data in DOWN:
            q["sel"] = max(0, min(len(q["results"]) - 1, q["sel"] + (1 if data in DOWN else -1)))
            return
        for b in data:
            if b in (8, 127):
                q["query"] = q["query"][:-1]
            elif b == 21:
                q["query"] = ""
            elif chr(b).isprintable():
                q["query"] += chr(b)
        q["sel"] = 0
        q["results"] = palette.search(q["query"], q["items"])

    def drag_mouse(self, b, x, y, press):
        """Dragging a divider resizes regions; True if this event was part of a drag."""
        rows, cols = self.scr.getmaxyx()
        if press and b == 0 and not self.drag:
            if x == GX + self.gw and y < rows - 1:
                self.drag = ("v", x)
            elif self.legend_div is not None and y == self.legend_div and x > GX + self.gw:
                self.drag = ("h", y)
            return bool(self.drag)
        if not self.drag:
            return False
        if press and b == 32:  # moved with the button held
            if self.drag[0] == "v":
                self.drag = ("v", max(GX + 80, min(cols - 21, x)))
            else:
                self.drag = ("h", max(1, min(rows - 8, y)))
            return True
        if not press:  # released: apply
            kind, pos = self.drag
            self.drag = None
            if kind == "v":
                self.helper_w = cols - pos - 1
                self._resize()
            else:
                self.legend_max = pos
            return True
        return True

    def click(self, x, y):
        """A left click: menu lines send their letter, inventory lines open their actions,
        the map gets the click, the pane takes focus."""
        if x >= GX + self.gw:
            self.focus = "helper"
            return
        x -= GX  # game-pane coordinates from here on
        if x < 0 or y >= self.gh:
            return
        if self.focus == "helper" and not (self.search or self.popup or self.saves_ui):
            self.focus = "game"  # coming back from the helper: this click only switches focus
            return
        if self.search:
            by, bx, w = self.search_box()
            i = y - by - 2
            if bx <= x < bx + w and 0 <= i < len(self.search["results"]):
                self.run_entry(self.search["results"][i])
            else:
                self.close_search()
            return
        if self.popup:
            p, i = self.popup, y - self.popup["y"] - 2
            if p["x"] <= x < p["x"] + p["w"] and 0 <= i < len(p["acts"]):
                self.choose(p["acts"][i][0])
            else:
                self.close_popup()
            return
        self.focus = "game"
        if self.zoom_view and x < MAP_W and self.zoom_view[4] <= y < self.zoom_view[5]:
            return  # map clicks don't move you
        for c0, c1, act in self.panel_spans.get(y, []) if x > MAP_W else []:
            if c0 <= x - MAP_W - 1 < c1:
                if act[0] == "filter":
                    self.inv_filter = act[1]
                else:
                    self.send(act[1])
                return
        letter = self.panel_items.get(y) if x >= MAP_W else None
        if letter and self.inventory_menu():  # the game's item menu: toggle it there
            self.send(letter.encode())
            return
        if letter:  # an item in the status/inventory panel
            if (self.watcher.state.get("context") or {}).get("kind") == "command":
                self.open_popup(x, y, letter)
            else:  # the game is asking which item
                self.send(letter.encode())
            return
        row = "".join(self.screen.buffer[y][i].data for i in range(self.gw))
        if "--More--" in row:
            self.send(b"\r")
            return
        hits = [m for m in MENU_ITEM.finditer(row) if m.start() <= x]
        if hits:  # a menu
            self.send(hits[-1].group(1).encode())

    def wheel(self, x, down):
        """Wheel: scrolls the helper transcript, or pages a multi-page game menu."""
        if x >= GX + self.gw:
            self.helper.scroll += -3 if down else 3
        elif any(MENU_PAGE.search(line) for line in self.screen.display):
            self.send(b">" if down else b"<")  # only in a menu: on the map > goes downstairs
        elif GX <= x < GX + MAP_W:
            self.set_zoom(-1 if down else 1)

    def ask(self, question):
        if not self.helper.busy:
            self.helper.scroll = 0
            st = self.watcher.state
            mine = [i for i in saves.listing(SAVES, SNAPS) if i["base"] == self.save_name]
            extra = ("\n\nCheckpoints of this game: " + (", ".join(f"{i['what']} ({i['when']})" for i in mine) or "none")
                     + f"\n\nGame log file: {os.path.basename(self.log.path or '(not started yet)')}"
                     + "\nLatest log lines:\n" + self.log.tail(60))
            self.helper.ask(question, snapshot(self.screen, st) + extra, self.redraw, self.log)

    def game_key(self, data):
        """Send a key to the game, unless the guard holds it (then a second press sends it)."""
        if len(data) == 2 and data[0] == 0x1b and 0x20 < data[1] < 0x7f and data[1:] not in (b"[", b"O"):
            data = bytes([data[1] | 0x80])  # Option+key (Esc, key at once): NetHack's Meta, as 8-bit
        if data == self.held:
            self.held = None
        elif data:
            why = guard.check(self.watcher.state, data)
            if why:
                self.held = data
                self.helper.scroll = 0
                self.helper.lines.append(("err", f"HELD: {why} Press the same key again to do it anyway."))
                self.log.event("guard held a key: " + why)
                return
            self.held = None
        self.send(data)

    def check_warnings(self):
        state = self.watcher.state
        if state.get("seq", 0) == self.seq:
            return
        self.seq = state.get("seq", 0)
        self.log.on_state(state, quiet=self.holding or bool(self.saving))  # a checkpoint's save/restore chatter
        if self.log.path and self.log.path != self.hist_for:  # this character's helper history
            self.hist_for = self.log.path
            if os.path.exists(self.hist_path()):
                current = self.helper.lines
                self.helper.load(self.hist_path())
                self.helper.lines += current[1:]  # keep what was said since this start
        if self.holding and (state.get("context") or {}).get("kind") == "command" and state.get("player"):
            self.holding = False  # the restarted game is back at its prompt: show it
            self.screen.dirty.update(range(self.gh))
        you, cur = state.get("player") or {}, self.screen.cursor
        if (state.get("context") or {}).get("kind") == "command" and cur.x == you.get("x", 0) - 1:
            self.map_top = cur.y - you.get("y", 0)  # curses parks the cursor on you
        now = guard.warnings(state)
        for w in sorted(now - self.warned):
            self.helper.scroll = 0
            self.helper.lines.append(("warn", "! " + w))
            self.log.event("warning: " + w)
        self.warned = now
        dlvl = (state.get("status") or {}).get("dlvl")
        if dlvl and dlvl != self.snap_dlvl and self.save_game("checkpoint"):
            self.snap_dlvl = dlvl  # one automatic checkpoint per level reached

    def run(self):
        sys.stdout.write(MOUSE_ON)  # mouse clicks, SGR coordinates
        sys.stdout.flush()
        self.redraw()
        while True:
            if self.resized:
                self._resize()
            try:
                r, _, _ = select.select([0] if self.over else [self.fd, 0], [], [], 0.2)
            except InterruptedError:
                continue
            if self.fd in r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    data = b""
                if not data:
                    if not self.game_exited():
                        return
                    continue
                self.stream.feed(data)
            self.check_warnings()
            if 0 in r:
                data = os.read(0, 1024)
                for m in MOUSE.finditer(data):
                    b, x, y = int(m.group(1)), int(m.group(2)) - 1, int(m.group(3)) - 1
                    if self.selecting:
                        self.select_mouse(b, x, y, m.group(4) == b"M")
                        continue
                    if self.drag_mouse(b, x, y, m.group(4) == b"M"):
                        continue
                    if m.group(4) == b"M" and b == 0:  # left press
                        self.click(x, y)
                    elif b in (64, 65):  # wheel up, down
                        self.wheel(x, b == 65)
                data = MOUSE.sub(b"", data)
                if self.handle_key(data) is False:
                    return
            self.redraw()

    def handle_key(self, data):
        """One chunk of keyboard input; False means quit."""
        if self.leader:  # the letter after ⌃G
            self.leader = False
            letter = LEADER_KEYS.get(data.decode("latin-1").lower())
            if not letter:
                return
            data = ctrl_opt(letter)
        elif data == LEADER:
            self.leader = True
            return
        if self.selecting or data == SELECT:  # ⌃G v in, ⌃G v or Esc out; other keys wait
            if self.selecting and data not in (SELECT, b"\x1b"):
                return
            self.selecting, self.sel = not self.selecting, None
            self.paint(bar=self.SELECT_BAR if self.selecting else None)
            return
        if self.saves_ui and data:
            return self.saves_key(data)
        if self.over:  # dead, list closed somehow: q quits, anything else reopens it
            if data == b"q":
                return False
            self.open_saves()
        elif data == SAVES_KEY:
            self.open_saves()
        elif self.search and data:
            self.search_key(data)
        elif data == SEARCH:
            self.open_search()
        elif data == COPY:
            self.copy_screen()
        elif data in (ZOOM_IN, ZOOM_OUT):
            self.set_zoom(1 if data == ZOOM_IN else -1)
        elif self.popup and data:
            self.popup_key(data)
        elif any(t == data or data.startswith(t) for t in TOGGLE):
            self.focus = "helper" if self.focus == "game" else "game"
        elif data in FKEYS:
            self.send(FKEYS[data])
        elif data == WHAT_NOW:
            self.ask("What should I do right now?")
        elif data == SNAPSHOT:
            if not self.save_game("checkpoint"):
                self.say("dim", "Checkpoints happen at the command prompt; finish this first.")
        elif data == REWIND:
            last = saves.snapshots(SNAPS, self.save_name)
            if not self.save_name or not last:
                self.say("dim", "No checkpoint yet (one is made on each new level, or press ⌃G s).")
            else:
                self.request_load(next(i for i in saves.listing(SAVES, SNAPS) if i["path"] == last[-1]))
        elif self.focus == "game":
            self.game_key(data)
        else:
            self.helper_key(data)

    def close(self):
        self.helper.save(self.hist_path())
        try:
            sys.stdout.write(MOUSE_OFF)
            sys.stdout.flush()
        except OSError:  # the terminal is already gone (window closed)
            pass
        self.watcher.close()
        try:
            os.kill(self.pid, signal.SIGHUP)  # NetHack saves on hangup
        except ProcessLookupError:
            return
        # wait for that save and keep a checkpoint of it, so the latest progress
        # also lives outside playground/
        for _ in range(50):
            try:
                if os.waitpid(self.pid, os.WNOHANG)[0]:
                    break
            except ChildProcessError:
                break
            time.sleep(0.1)
        files = [os.path.join(SAVES, f) for f in os.listdir(SAVES)]
        fresh = [f for f in files if os.path.getmtime(f) >= self.started]
        if fresh:
            save = max(fresh, key=os.path.getmtime)
            self.save_name = os.path.basename(save)
            self.snap_info = self.watcher.state.get("status") or getattr(self, "snap_info", {})
            self.checkpoint(save)


def main(scr):
    signal.signal(signal.SIGHUP, lambda *_: sys.exit())  # closed terminal: still save and clean up
    app = App(scr, sys.argv[1:])
    try:
        app.run()
    finally:
        app.close()


if __name__ == "__main__":
    locale.setlocale(locale.LC_ALL, "")  # curses draws ⌃ ⌥ and other non-ASCII text
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main)
