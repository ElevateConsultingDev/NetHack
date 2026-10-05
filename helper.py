#!/usr/bin/env python3
"""NetHack with a Claude helper on the same screen.

The game runs in a pty on the left (drawn through pyte, a terminal emulator);
a chat pane sits on the right. ^] or F1 switches focus. Each question goes to
`claude -p` along with what's on screen and, through the aipipe socket
(src/aipipe.c, NETHACK_CONTROL), the inventory. Run it with ./play.
"""
import curses
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

import guard
import palette

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(HERE, "playground")
SAVES = os.path.join(GAME, "save")
SNAPS = os.path.join(GAME, "snapshots")
KEEP_SNAPS = 10
MODEL = os.environ.get("NH_HELPER_MODEL", "sonnet")
HELPER_W = int(os.environ.get("NH_HELPER_WIDTH", "40"))
TOGGLE = (b"\x1d", b"\x1bOP", b"\x1b[11~")  # ^], F1 (two encodings)
FKEYS = {  # function key (two encodings each) -> extended command typed into the game
    b"\x1bOQ": b"#fog\r", b"\x1b[12~": b"#fog\r",  # F2: lift / bring back the fog of war
    b"\x1bOR": b"#godown\r", b"\x1b[13~": b"#godown\r",  # F3: travel to the down stairs
    b"\x1bOS": b"#goup\r", b"\x1b[14~": b"#goup\r",      # F4: travel to the up stairs
}
WHAT_NOW = b"\x1b[15~"  # F5: ask the helper what to do now
SNAPSHOT = b"\x1b[17~"  # F6: snapshot the game now
REWIND = b"\x1b[18~"    # F7: go back to the last snapshot
SEARCH = b"\x1b[19~"    # F8: fuzzy search over commands, items and map things
COPY = b"\x1b[20~"      # F9: copy the game screen to the clipboard as text
ZOOM_IN, ZOOM_OUT = b"\x1b[23~", b"\x1b[24~"  # F11, F12 (or the wheel over the map)
SELECT = b"\x1b[21~"    # F10: select mode: screen frozen, mouse back to the terminal
MOUSE_ON = "\x1b[?1000h\x1b[?1002h\x1b[?1006h"   # clicks, drags (for resizing), SGR coordinates
MOUSE_OFF = "\x1b[?1006l\x1b[?1002l\x1b[?1000l"
UP, DOWN = (b"\x1b[A", b"\x1bOA"), (b"\x1b[B", b"\x1bOB")
COMMANDS = palette.load_commands(os.path.join(HERE, "src", "cmd.c"))
EXTRAS = [dict(label="what now", detail="ask the helper what to do right now  [F5]", action=("fkey", WHAT_NOW)),
          dict(label="snapshot", detail="save a snapshot to come back to  [F6]", action=("fkey", SNAPSHOT)),
          dict(label="rewind", detail="go back to the last snapshot  [F7]", action=("fkey", REWIND)),
          dict(label="copy screen", detail="copy the game screen as text  [F9]", action=("fkey", COPY)),
          dict(label="zoom in", detail="bigger map squares  [F11, wheel up over the map]", action=("fkey", ZOOM_IN)),
          dict(label="zoom out", detail="smaller map squares  [F12, wheel down over the map]", action=("fkey", ZOOM_OUT)),
          dict(label="select mode", detail="freeze the screen to select text with the mouse  [F10]",
               action=("fkey", SELECT)),
          dict(label="switch focus", detail="type into the helper or the game  [F1, ^]]", action=("fkey", b"\x1d"))]
for _c in COMMANDS:  # the F-key shortcuts for game commands
    _f = {"fog": "F2", "godown": "F3", "goup": "F4"}.get(_c["label"])
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
ZOOMS = ([(1, 1), (2, 2), (3, 3), (4, 4)] if KITTY  # columns x rows per map square
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
Plain text only, no markdown: it is shown in a narrow terminal pane."""

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
        while True:  # a new connection each time the game restarts (snapshots)
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
        self.lines = [("dim", "Ask anything about the game. ^] or F1 switches focus.")]
        self.input = ""
        self.busy = False
        self.session = None
        self.scroll = 0  # lines up from the bottom

    def ask(self, question, snapshot, redraw):
        self.lines.append(("you", "> " + question))
        self.busy = True

        def run():
            try:
                answer, self.session = ask_claude(question, snapshot, self.session)
                self.lines.append(("text", answer))
            except RuntimeError as e:
                self.lines.append(("err", f"error: {e}"))
            self.busy = False
            redraw()
        threading.Thread(target=run, daemon=True).start()


def ask_claude(question, snapshot, session):
    """Runs claude -p (subscription login, no tools); returns (answer, session)."""
    cmd = ["claude", "-p", "--output-format", "json", "--model", MODEL,
           "--tools", "", "--setting-sources", "", "--strict-mcp-config",
           "--system-prompt", SYSTEM]
    if session:
        cmd += ["--resume", session]
    env = {k: v for k, v in os.environ.items() if not k.startswith("ANTHROPIC_")}
    prompt = f"Game state:\n{snapshot}\n\nQuestion: {question}"
    try:
        out = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                             timeout=120, cwd=tempfile.gettempdir(), env=env)
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
        parts.append("Inventory:\n" + "\n".join(f"{i['letter']} - {i['text']}" for i in inv))
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
    return "\n\n".join(parts)


OBJECT_CLASSES = {")": "weapon", "[": "armor", "!": "potion", "?": "scroll", "/": "wand",
                  "=": "ring", '"': "amulet", "(": "tool", "%": "food", "*": "gem or rock",
                  "$": "gold", "`": "boulder or statue", "+": "spellbook", "0": "iron ball",
                  "_": "iron chain"}
LEGEND_ORDER = ("you", "pet", "monster", "invisible", "object", "trap", "feature")


def legend(state):
    """'c name' for each distinct symbol on the map now (from aipipe's cells)."""
    rows, seen, out = state.get("map") or [], set(), []
    cells = sorted(state.get("cells", []),
                   key=lambda c: LEGEND_ORDER.index(c["kind"]) if c["kind"] in LEGEND_ORDER else 99)
    for c in cells:
        row = rows[c["y"]] if c["y"] < len(rows) else ""
        ch = row[c["x"] - 1] if 0 < c["x"] <= len(row) else "?"
        name = OBJECT_CLASSES.get(c.get("class"), c["name"]) if c["kind"] == "object" else c["name"]
        if (ch, name) not in seen:
            seen.add((ch, name))
            out.append(f"{ch} {name}")
    return out


def snapshots(save_name=None):
    """Snapshot files for one save file name (or all), oldest first."""
    if not os.path.isdir(SNAPS):
        return []
    files = [os.path.join(SNAPS, f) for f in os.listdir(SNAPS)
             if save_name is None or f.split("@")[0] == save_name]
    return sorted(files, key=os.path.getmtime)


def snap_label(path):
    turn, dlvl = os.path.basename(path).rsplit("@", 1)[-1].split("-D")
    return f"Dlvl {dlvl}, turn {int(turn)}"


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
        self.held = None      # a dangerous key held back by the guard, sent if pressed again
        self.warned = set()   # warnings already shown (each shows once while it applies)
        self.seq = 0
        self.popup = None     # actions for a clicked inventory item: x, y, w, letter, text, acts
        self.search = None    # the F8 search: query, sel, items, results
        self.selecting = False  # F10: frozen screen, drag a rectangle to copy
        self.sel = None         # (y0, x0, y1, x1) of the rectangle being dragged
        self.map_top = 1      # screen row of map row y=0 (found from the cursor on @)
        self.panel_items = {} # game-pane row -> inventory letter, for clicks
        self.panel_on = False
        self.helper_w = None    # helper width once dragged
        self.legend_max = None  # legend lines once dragged
        self.legend_div = None  # screen row of the legend/chat divider
        self.drag = None        # ("v", x) or ("h", y) while a divider is dragged
        self.zoom = 0           # index into ZOOMS
        self.zoom_view = None   # (x0, y0, bw, bh, top, bottom) of the zoomed map on screen
        self.big = self.big_sent = None  # kitty: big-character escapes drawn / last sent
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
        self.saving = None    # "snapshot" or "rewind" while the wrapper has the game saving
        self.over = False     # the game ended (died or quit) and a rewind is on offer
        self.snap_dlvl = None # dungeon level of the last automatic snapshot
        self.save_name = None # this character's save file name, once known
        self.spawn()
        self.resized = False
        signal.signal(signal.SIGWINCH, lambda *_: setattr(self, "resized", True))

    def spawn(self):
        """Start (or restart) the game; a saved game restores automatically."""
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
        self.snap_info = st.get("status") or {}
        self.send(SAVE_KEYS)
        return True

    def game_exited(self):
        """The game process ended: finish a snapshot or rewind, or offer a rewind
        after a death. False means the wrapper should quit."""
        try:
            os.waitpid(self.pid, 0)
        except ChildProcessError:
            pass
        os.close(self.fd)
        saves = sorted((os.path.join(SAVES, f) for f in os.listdir(SAVES)), key=os.path.getmtime)
        fresh = [f for f in saves if os.path.getmtime(f) >= self.started]
        why, self.saving = self.saving, None
        if why and fresh:
            save = fresh[-1]
            self.save_name = os.path.basename(save)
            if why == "snapshot":
                os.makedirs(SNAPS, exist_ok=True)
                info = self.snap_info
                shutil.copy2(save, os.path.join(
                    SNAPS, f"{os.path.basename(save)}@{info.get('turn', 0):06d}-D{info.get('dlvl', 0)}"))
                for old in snapshots(self.save_name)[:-KEEP_SNAPS]:
                    os.unlink(old)
                self.say("dim", f"Snapshot saved (Dlvl {info.get('dlvl')}, turn {info.get('turn')}). F7 goes back to it.")
            else:
                self.restore_snapshot()
            self.spawn()
            return True
        if fresh:  # the player saved (S): done for now
            return False
        snap = snapshots(self.save_name)[-1:] if snapshots(self.save_name) else []
        if not snap:
            return False
        self.over = True
        self.say("err", f"Game over. F7 rewinds to your last snapshot ({snap_label(snap[0])}); q quits.")
        return True

    def restore_snapshot(self):
        snap = snapshots(self.save_name)[-1]
        shutil.copy2(snap, os.path.join(SAVES, os.path.basename(snap).split("@")[0]))
        self.say("dim", f"Rewound to {snap_label(snap)}.")

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
        """The panel shows unless the game has something beside the map (a menu, a window)."""
        if self.gw - MAP_W - 1 < 20 or not self.watcher.state.get("status"):
            return False
        skip, buf = self.status_rows(), self.screen.buffer
        return not any(buf[r][c].data not in (" ", "") for r in range(PANEL_TOP, self.gh) if r not in skip
                       for c in range(MAP_W, self.gw))

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
        return (self.zoom > 0 and st.get("player")
                and (st.get("context") or {}).get("kind") in ("command", "yn", "more"))

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
        ncols, nrows = MAP_W // bw, (bottom - top) // bh
        x0 = max(1, min(MAP_W - ncols, you["x"] - ncols // 2))
        y0 = max(0, min(MAP_H - nrows, you["y"] - nrows // 2)) if nrows < MAP_H else 0
        self.zoom_view = (x0, y0, bw, bh, top, bottom)
        buf, big = self.screen.buffer, []
        for r in range(top, bottom):
            j, k = divmod(r - top, bh)
            y = y0 + j
            for i in range(ncols):
                x = x0 + i
                if j < nrows and y < MAP_H and x < MAP_W and top + y < self.gh:
                    c = buf[top + y][x - 1]
                    ch = (c.data or " ").translate(ASCII)
                    if KITTY:  # curses keeps the block blank; kitty draws the big character over it
                        self.gput(r, i * bw, " " * bw)
                        if k == 0:  # blanks too: they clear an old big character
                            big.append(big_char(r, GX + i * bw, bw, ch, c))
                    else:
                        self.gput(r, i * bw, ch * bw, self.cell_attr(c))
                else:
                    self.gput(r, i * bw, " " * bw)
            self.gput(r, ncols * bw, " " * (MAP_W - ncols * bw))
        self.screen.dirty.update(range(top, bottom))  # redraw normally when zoom ends
        self.big = "".join(big)

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
            for r in range(self.gh):
                j, k = divmod(r - top, bh)
                y = y0 + j
                label = f"{y:2d} " if top <= r < bottom and k == 0 and y < MAP_H else "   "
                self.put(r, 0, label, curses.A_REVERSE if label.strip() and y == you.get("y") else curses.A_DIM)
            self.put(self.gh, 0, " " * (GX + MAP_W))
            self.put(self.gh + 1, 0, " x ", curses.A_DIM)
            for i in range(MAP_W // bw):
                x = x0 + i
                if x < MAP_W:
                    self.gput(self.gh + 1, i * bw, str(x).ljust(bw)[:bw] if bw >= 2 or x % 5 == 0 else " ",
                              curses.A_REVERSE if x == you.get("x") else curses.A_DIM)
            self.gput(self.gh + 1, MAP_W + 1, f"you: x={you['x']} y={you.get('y')}  zoom {bw}x".ljust(24), curses.A_BOLD)
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

    def draw_panel(self):
        """Status, location and inventory beside the map, unless the game has a menu there."""
        self.panel_items = {}
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
        lines = [(f"{st.get('race', '').capitalize()} {st.get('role', '')}, {st.get('alignment', '')}", curses.A_BOLD, None),
                 (f"HP {hp}/{hpmax}", self.color(hp_col, "default", True) | curses.A_BOLD, None),
                 (f"Pw {st.get('pw')}/{st.get('pwmax')}   AC {st.get('ac')}", 0, None),
                 (f"Xp {st.get('xlvl')}/{st.get('exp')}   $ {st.get('gold')}   T {st.get('turn')}", 0, None),
                 (f"Dlvl {st.get('dlvl')}  {st.get('dungeon', '')}", 0, None),
                 (f"Location x={you.get('x')} y={you.get('y')}", curses.A_BOLD, None),
                 (f"St {strength} Dx {st.get('dex')} Co {st.get('con')} In {st.get('int')} "
                  f"Wi {st.get('wis')} Ch {st.get('cha')}", 0, None),
                 (" ".join(flags), self.color("yellow", "default", True) | curses.A_BOLD, None),
                 ("Inventory (click an item)", curses.A_DIM, None)]
        asked = guard.asked_letters(self.watcher.state)
        if asked:  # the game wants an item: say so, and pick out the ones that fit
            lines[-1] = (f"{asked[0]} Click one:", self.color("yellow", "default", True) | curses.A_BOLD, None)
        for i in self.watcher.state.get("inventory", []):
            worn = guard.WORN.search(i["text"]) or "weapon in hand" in i["text"]
            attr = self.color("cyan", "default", False) if worn else 0
            mark = ""
            if asked:
                fits = i["letter"] in asked[1]
                attr = curses.A_BOLD if fits else curses.A_DIM
                mark = "> " if fits else "  "
            lines.append((f"{mark}{i['letter']}) {i['text']}", attr, i["letter"]))
        lines.append(("", 0, None))
        status = "  ".join(re.sub(r"  +", "  ", self.row_text(r)).strip() for r in self.status_rows())
        lines += [(l, 0, None) for l in textwrap.wrap(status, w)]  # the game's status lines, as one
        for r in range(PANEL_TOP, self.gh):
            self.gput(r, MAP_W, "|")  # map | panel
        for n, r in enumerate(range(PANEL_TOP, self.gh)):
            text, attr, letter = lines[n] if n < len(lines) else ("", 0, None)
            if r == self.gh - 1 and len(lines) > n + 1:
                text, letter = "...", None
            self.gput(r, MAP_W + 1, text[:w].ljust(w), attr)
            if letter:
                self.panel_items[r] = letter

    def draw_helper(self):
        rows, cols = self.scr.getmaxyx()
        x0, w = GX + self.gw + 1, cols - GX - self.gw - 1
        if w < 10:
            return
        for y in range(rows - 1):
            self.put(y, GX + self.gw, "|")  # game | helper, drag to resize
        top = 0
        entries = legend(self.watcher.state)
        if entries:  # the map legend, packed into lines across the pane
            lines, cur = [], ""
            for e in entries:
                if cur and len(cur) + 2 + len(e) > w - 1:
                    lines.append(cur)
                    cur = ""
                cur = f"{cur}  {e}" if cur else e
            lines.append(cur)
            lines = lines[:self.legend_max or max(3, rows // 3)]
            if self.legend_max:  # the height it was dragged to
                lines += [""] * (self.legend_max - len(lines))
            for y, l in enumerate(lines):
                self.put(y, x0, l.ljust(w - 1)[:w - 1], curses.A_BOLD)
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
        self.put(rows - 1, 0, f" ^]/F1 switch focus  F2 fog of war  F3/F4 stairs dn/up  F5 what now?  F6 snapshot  F7 rewind  F8 search  F9 copy  F10 select  F11/F12 zoom  |  typing goes to: {where} ".ljust(cols - 1)[:cols - 1],
                 curses.A_REVERSE)

    def redraw(self):
        if self.selecting:  # frozen while a rectangle is being selected
            return
        self.paint()

    SELECT_BAR = " SELECT: drag a rectangle, let go to copy it.  F10 or Esc: back to the game "

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
            self.paint(bar=f" Copied {right - left + 1}x{bot - top + 1} to the clipboard. Drag again, or F10/Esc: back to the game ")
            return
        else:
            return
        self.paint(bar=self.SELECT_BAR)
        y0, x0, y1, x1 = self.sel
        for r in range(min(y0, y1), max(y0, y1) + 1):
            self.scr.chgat(r, min(x0, x1), abs(x1 - x0) + 1, curses.A_REVERSE)
        self.scr.refresh()

    def paint(self, bar=None):
        with self.lock:
            self.draw_game()
            self.draw_zoom()
            self.draw_axes()
            self.draw_panel()
            if self.popup:
                self.draw_popup()
            if self.search:
                self.draw_search()
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
            if self.focus == "game" and self.zoom_view:
                x0, y0, bw, bh, top, _ = self.zoom_view
                you = self.watcher.state["player"]
                self.scr.move(min(top + (you["y"] - y0) * bh, self.gh - 1), GX + (you["x"] - x0) * bw)
            elif self.focus == "game":
                self.scr.move(min(self.screen.cursor.y, self.gh - 1), GX + min(self.screen.cursor.x, self.gw - 1))
            else:
                rows, _ = self.scr.getmaxyx()
                self.scr.move(rows - 2, min(GX + self.gw + 3 + len(self.helper.input), self.scr.getmaxyx()[1] - 2))
            self.scr.refresh()
            if KITTY and self.zoom_view and self.big != self.big_sent:
                # after curses: save cursor and colors, draw the big characters, restore
                sys.stdout.write("\x1b7" + self.big + "\x1b8")
                sys.stdout.flush()
            self.big_sent = self.big if self.zoom_view else None

    def helper_key(self, data):
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
            x0, y0, bw, bh, top, _ = self.zoom_view
            tx, ty = x0 + x // bw, y0 + (y - top) // bh
            if (self.watcher.state.get("context") or {}).get("kind") == "command" and tx < MAP_W and ty < MAP_H:
                self.send(f"#goto\r{tx} {ty}\r".encode())  # travel to the square clicked
            return
        letter = self.panel_items.get(y) if x >= MAP_W else None
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
        elif (1000 << 5) in self.screen.mode:  # the game asked for xterm mouse reports
            pos = bytes([32 + x + 1, 32 + y + 1])
            self.send(b"\x1b[M " + pos + b"\x1b[M#" + pos)  # press, release

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
            self.helper.ask(question, snapshot(self.screen, self.watcher.state), self.redraw)

    def game_key(self, data):
        """Send a key to the game, unless the guard holds it (then a second press sends it)."""
        if data == self.held:
            self.held = None
        elif data:
            why = guard.check(self.watcher.state, data)
            if why:
                self.held = data
                self.helper.scroll = 0
                self.helper.lines.append(("err", f"HELD: {why} Press the same key again to do it anyway."))
                return
            self.held = None
        self.send(data)

    def check_warnings(self):
        state = self.watcher.state
        if state.get("seq", 0) == self.seq:
            return
        self.seq = state.get("seq", 0)
        you, cur = state.get("player") or {}, self.screen.cursor
        if (state.get("context") or {}).get("kind") == "command" and cur.x == you.get("x", 0) - 1:
            self.map_top = cur.y - you.get("y", 0)  # curses parks the cursor on you
        now = guard.warnings(state)
        for w in sorted(now - self.warned):
            self.helper.scroll = 0
            self.helper.lines.append(("warn", "! " + w))
        self.warned = now
        dlvl = (state.get("status") or {}).get("dlvl")
        if dlvl and dlvl != self.snap_dlvl and self.save_game("snapshot"):
            self.snap_dlvl = dlvl  # one automatic snapshot per level reached

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
        if self.selecting or data == SELECT:  # F10 in, F10 or Esc out; other keys wait
            if self.selecting and data not in (SELECT, b"\x1b"):
                return
            self.selecting, self.sel = not self.selecting, None
            self.paint(bar=self.SELECT_BAR if self.selecting else None)
            return
        if self.over:  # dead: F7 rewinds, q quits, other keys are ignored
            if data == b"q":
                return False
            if data != REWIND:
                return
            self.over = False
            self.restore_snapshot()
            self.spawn()
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
            if not self.save_game("snapshot"):
                self.say("dim", "Snapshots happen at the command prompt; finish this first.")
        elif data == REWIND:
            if not snapshots(self.save_name):
                self.say("dim", "No snapshot yet (one is made on each new level, or press F6).")
            elif not self.save_game("rewind"):
                self.say("dim", "Rewind works at the command prompt; finish this first.")
        elif self.focus == "game":
            self.game_key(data)
        else:
            self.helper_key(data)

    def close(self):
        sys.stdout.write(MOUSE_OFF)
        sys.stdout.flush()
        self.watcher.close()
        try:
            os.kill(self.pid, signal.SIGHUP)  # NetHack saves on hangup
        except ProcessLookupError:
            pass


def main(scr):
    signal.signal(signal.SIGHUP, lambda *_: sys.exit())  # closed terminal: still save and clean up
    app = App(scr, sys.argv[1:])
    try:
        app.run()
    finally:
        app.close()


if __name__ == "__main__":
    os.environ.setdefault("ESCDELAY", "25")
    curses.wrapper(main)
