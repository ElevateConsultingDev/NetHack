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

HERE = os.path.dirname(os.path.abspath(__file__))
GAME = os.path.join(HERE, "playground")
MODEL = os.environ.get("NH_HELPER_MODEL", "sonnet")
HELPER_W = int(os.environ.get("NH_HELPER_WIDTH", "40"))
TOGGLE = (b"\x1d", b"\x1bOP", b"\x1b[11~")  # ^], F1 (two encodings)
MOUSE = re.compile(rb"\x1b\[<(\d+);(\d+);(\d+)([Mm])")  # SGR mouse report (mode 1006)
MENU_ITEM = re.compile(r"(?:^|[ \u2502])([a-zA-Z$#*-])\) ")  # " a) a +1 long sword"
MENU_PAGE = re.compile(r"\(Page \d+ of \d+\)")  # footer of a curses menu with more pages

SYSTEM = """You are a friendly NetHack 3.6 expert sitting next to the player, \
who plays in a terminal with the standard keyboard commands (curses interface). \
Each message gives the current screen, the inventory, and any question the game \
is asking, then the player's question.

Answer briefly and practically: a few sentences or a short list, under about \
120 words, about what is on screen now. Name the exact keys to press. Warn about \
real dangers (low HP, hunger, cursed or unknown items, peaceful monsters, \
shopkeepers, floating eyes, cockatrices). Do not spoil more than the player asks for. \
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
        conn, _ = self.srv.accept()
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
    return "\n\n".join(parts)


def term_size():
    rows, cols = struct.unpack("hh", fcntl.ioctl(1, termios.TIOCGWINSZ, b"\0" * 4))
    return rows, cols


def layout(rows, cols):
    """Game pane width and height; the helper gets the rest of the columns."""
    game_w = max(80, cols - HELPER_W - 1)
    return game_w, rows - 1


class App:
    def __init__(self, scr, argv):
        self.scr = scr
        self.watcher = Watcher()
        self.helper = Helper()
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

        pid, self.fd = pty.fork()
        if pid == 0:
            os.chdir(GAME)
            os.environ["TERM"] = "xterm"
            os.environ["NETHACK_CONTROL"] = self.watcher.path
            os.environ.setdefault("NETHACKOPTIONS", "@" + os.path.join(HERE, "nethackrc"))
            os.execv("./nethack", ["nethack"] + argv)
        self.pid = pid
        self._winsize()
        self.resized = False
        signal.signal(signal.SIGWINCH, lambda *_: setattr(self, "resized", True))

    def _winsize(self):
        fcntl.ioctl(self.fd, termios.TIOCSWINSZ, struct.pack("hhhh", self.gh, self.gw, 0, 0))

    def _resize(self):
        self.resized = False
        rows, cols = term_size()
        curses.resizeterm(rows, cols)
        self.gw, self.gh = layout(rows, cols)
        self.screen.resize(self.gh, self.gw)
        self._winsize()
        os.kill(self.pid, signal.SIGWINCH)
        self.scr.clear()
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

    def draw_game(self):
        buf = self.screen.buffer
        for y in sorted(self.screen.dirty):
            if y >= self.gh:
                continue
            line = buf[y]
            for x in range(self.gw):
                c = line[x]
                attr = self.color(c.fg, c.bg, c.bold)
                if c.bold:
                    attr |= curses.A_BOLD
                if c.reverse:
                    attr |= curses.A_REVERSE
                if c.underscore:
                    attr |= curses.A_UNDERLINE
                self.put(y, x, (c.data or " ").translate(ASCII), attr)
        self.screen.dirty.clear()

    def draw_helper(self):
        rows, cols = self.scr.getmaxyx()
        x0, w = self.gw + 1, cols - self.gw - 1
        if w < 10:
            return
        for y in range(rows - 1):
            self.put(y, self.gw, "|", curses.A_DIM)
        body = []
        for kind, text in self.helper.lines:
            attr = {"you": curses.A_BOLD, "dim": curses.A_DIM,
                    "err": self.color("red", "default", False)}.get(kind, 0)
            for para in text.split("\n"):
                body += [(attr, l) for l in (textwrap.wrap(para, w - 1) or [""])]
            body.append((0, ""))
        if self.helper.busy:
            body.append((curses.A_DIM, "thinking..."))
        h = rows - 3
        self.helper.scroll = max(0, min(self.helper.scroll, len(body) - h))
        body = body[max(0, len(body) - h - self.helper.scroll):len(body) - self.helper.scroll]
        for y in range(h):
            attr, l = body[y] if y < len(body) else (0, "")
            self.put(y, x0, l.ljust(w - 1)[:w - 1], attr)
        mark = curses.A_REVERSE if self.focus == "helper" else curses.A_DIM
        self.put(rows - 2, x0, ("> " + self.helper.input)[-(w - 1):].ljust(w - 1), mark)

    def draw_bar(self):
        rows, cols = self.scr.getmaxyx()
        where = "HELPER (Enter asks, Esc back)" if self.focus == "helper" else "GAME"
        self.put(rows - 1, 0, f" ^]/F1 switch focus  |  typing goes to: {where} ".ljust(cols - 1)[:cols - 1],
                 curses.A_REVERSE)

    def redraw(self):
        with self.lock:
            self.draw_game()
            self.draw_helper()
            self.draw_bar()
            if self.focus == "game":
                self.scr.move(min(self.screen.cursor.y, self.gh - 1), min(self.screen.cursor.x, self.gw - 1))
            else:
                rows, _ = self.scr.getmaxyx()
                self.scr.move(rows - 2, min(self.gw + 3 + len(self.helper.input), self.scr.getmaxyx()[1] - 2))
            self.scr.refresh()

    def helper_key(self, data):
        for b in data:
            ch = chr(b)
            if b == 27:
                self.focus = "game"
                return
            if ch in "\r\n":
                q = self.helper.input.strip()
                self.helper.input = ""
                if q and not self.helper.busy:
                    self.helper.scroll = 0
                    self.helper.ask(q, snapshot(self.screen, self.watcher.state), self.redraw)
            elif b in (8, 127):
                self.helper.input = self.helper.input[:-1]
            elif b == 21:  # ^U clears the line
                self.helper.input = ""
            elif ch.isprintable():
                self.helper.input += ch

    def click(self, x, y):
        """A left click: menu lines send their letter, the map gets the click, the pane takes focus."""
        if x >= self.gw:
            self.focus = "helper"
            return
        self.focus = "game"
        row = "".join(self.screen.buffer[y][i].data for i in range(self.gw))
        if "--More--" in row:
            os.write(self.fd, b"\r")
            return
        hits = [m for m in MENU_ITEM.finditer(row) if m.start() <= x]
        if hits:
            os.write(self.fd, hits[-1].group(1).encode())
        elif (1000 << 5) in self.screen.mode:  # the game asked for xterm mouse reports
            pos = bytes([32 + x + 1, 32 + y + 1])
            os.write(self.fd, b"\x1b[M " + pos + b"\x1b[M#" + pos)  # press, release

    def wheel(self, x, down):
        """Wheel: scrolls the helper transcript, or pages a multi-page game menu."""
        if x >= self.gw:
            self.helper.scroll += -3 if down else 3
        elif any(MENU_PAGE.search(line) for line in self.screen.display):
            os.write(self.fd, b">" if down else b"<")  # only in a menu: on the map > goes downstairs

    def run(self):
        sys.stdout.write("\x1b[?1000h\x1b[?1006h")  # mouse clicks, SGR coordinates
        sys.stdout.flush()
        self.redraw()
        while True:
            if self.resized:
                self._resize()
            try:
                r, _, _ = select.select([self.fd, 0], [], [], 0.2)
            except InterruptedError:
                continue
            if self.fd in r:
                try:
                    data = os.read(self.fd, 65536)
                except OSError:
                    data = b""
                if not data:
                    return
                self.stream.feed(data)
            if 0 in r:
                data = os.read(0, 1024)
                for m in MOUSE.finditer(data):
                    b, x, y = int(m.group(1)), int(m.group(2)) - 1, int(m.group(3)) - 1
                    if m.group(4) == b"M" and b == 0:  # left press
                        self.click(x, y)
                    elif b in (64, 65):  # wheel up, down
                        self.wheel(x, b == 65)
                data = MOUSE.sub(b"", data)
                if any(t == data or data.startswith(t) for t in TOGGLE):
                    self.focus = "helper" if self.focus == "game" else "game"
                elif self.focus == "game":
                    os.write(self.fd, data)
                else:
                    self.helper_key(data)
            self.redraw()

    def close(self):
        sys.stdout.write("\x1b[?1006l\x1b[?1000l")
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
