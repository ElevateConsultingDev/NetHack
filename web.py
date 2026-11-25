#!/usr/bin/env python3
"""NetHack with the Claude helper, in a browser: ./web, then open http://127.0.0.1:8220.

The game runs in a pty here, exactly as under ./play; the browser shows its curses
screen in a real terminal (xterm.js) and builds the panels (character, fight,
inventory, helper chat, saves) from the aipipe state. All the game handling
(guard, checkpoints, saves, the helper, the log) is helper.App's, reused as is.
"""
import base64
import json
import os
import queue
import select
import signal
import sys
import threading
import time
import urllib.parse
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler

import pyte

import guard
import helper
import saves
from helper import App, ctrl_opt, SAVES, SNAPS

PORT = int(os.environ.get("NH_WEB_PORT", "8220"))  # platform-spec/ports.yaml
PAGE = os.path.join(helper.HERE, "web.html")
COMMANDS = {"fog": ctrl_opt("F"), "down": ctrl_opt("D"), "up": ctrl_opt("U"), "whatnow": ctrl_opt("W"),
            "checkpoint": ctrl_opt("S"), "rewind": ctrl_opt("R")}
SORTS = {"newest": lambda i: -i["mtime"],
         "deepest": lambda i: (-(i["dlvl"] or 0), -(i["turn"] or 0)),
         "turns": lambda i: -(i["turn"] or 0),
         "level": lambda i: (-(i["xlvl"] or 0), -(i["turn"] or 0))}
SGR = {"black": 0, "red": 1, "green": 2, "brown": 3, "blue": 4, "magenta": 5, "cyan": 6, "white": 7}


def ansi(screen):
    """The pyte screen as escape codes, so a browser that connects mid-game sees it."""
    out = ["\x1b[0m\x1b[2J"]
    for y in range(screen.lines):
        out.append(f"\x1b[{y + 1};1H")
        for x in range(screen.columns):
            c = screen.buffer[y][x]
            sgr = ["0"]
            if c.bold:
                sgr.append("1")
            if c.reverse:
                sgr.append("7")
            if c.underscore:
                sgr.append("4")
            if c.fg.removeprefix("bright") in SGR:
                sgr.append(str(SGR[c.fg.removeprefix("bright")] + (90 if c.fg.startswith("bright") else 30)))
            if c.bg in SGR:
                sgr.append(str(SGR[c.bg] + 40))
            out.append(f"\x1b[{';'.join(sgr)}m{c.data or ' '}")
    out.append(f"\x1b[0m\x1b[{screen.cursor.y + 1};{screen.cursor.x + 1}H")
    return "".join(out)


class Web(App):
    """helper.App without curses: the same game, saves and helper, shown in a browser."""

    def __init__(self, argv):  # App.__init__ minus the curses setup
        self.watcher, self.helper = helper.Watcher(), helper.Helper()
        self.helper.lines = [("dim", "Ask anything about the game.")]
        self.log = helper.gamelog.GameLog(helper.LOGS)
        self.hist_for, self.held, self.warned, self.fight, self.seq = None, None, set(), [], 0
        self.helper.on_answer = lambda: self.helper.save(self.hist_path())
        self.leader, self.focus, self.lock = False, "game", threading.RLock()
        self.map_top, self.zoom_view, self.under_drawn = 1, None, set()
        self.gw, self.gh = 132, 40  # until the browser says its size
        self.screen = pyte.Screen(self.gw, self.gh)
        self.stream = pyte.ByteStream(self.screen)
        self.stream.use_utf8 = False
        self.argv, self.saving, self.over, self.snap_dlvl, self.load_target = argv, None, False, None, None
        self.holding, self.new_name, self.saves_ui, self.save_name = False, None, None, None
        self.clients = []  # one queue per browser (server-sent events)
        self.saves_sort = "newest"  # the saves list's order (SORTS)
        self.spawn()

    def redraw(self):  # the helper calls this when an answer arrives
        with self.lock:
            self.push_state()

    def spawn(self, name=None):
        App.spawn(self, name)
        self.emit("out", base64.b64encode(b"\x1bc").decode())  # the browsers' terminals start over too

    def emit(self, kind, data):
        for q in list(self.clients):
            q.put((kind, data))

    def push_state(self):
        st = self.watcher.state
        u = self.saves_ui
        if u and u["items"]:  # in the chosen order, keeping the selected one selected
            cur = u["items"][min(u["sel"], len(u["items"]) - 1)]
            u["items"].sort(key=SORTS[self.saves_sort])
            u["sel"] = u["items"].index(cur)
        self.emit("state", {
            "state": st, "fight": [l for t, l in self.fight
                                   if (st.get("status") or {}).get("turn", 0) - t <= 10],
            "chat": self.helper.lines[-300:], "busy": self.helper.busy,
            "menu": self.inventory_menu(), "asked": (lambda a: a and [a[0], sorted(a[1])])(guard.asked_letters(st)),
            "actions": {i["letter"]: guard.item_actions(i.get("class"), i["text"]) for i in st.get("inventory", [])},
            "legend": self.legend(),
            "msgs": [self.row_text(r) for r in range(self.msg_rows())],
            "cursor": [self.screen.cursor.y, self.screen.cursor.x] if self.screen.cursor.y < self.msg_rows() else None,
            "settings": helper.settings(), "models": helper.MODELS,
            "saves": u and {**{k: u[k] for k in ("items", "sel", "confirm", "naming")}, "sort": self.saves_sort},
            "over": self.over})

    def legend(self):
        """[symbol, what it is, color, bold] for each kind of thing on the map now
        (helper.legend), the color read off the screen where one is."""
        out = []
        for ch, name, y, x in helper.legend(self.watcher.state):
            r = self.map_top + y
            c = self.screen.buffer[r][x - 1] if 0 <= r < self.gh and x > 0 else None
            if c and (c.data or " ").strip():
                ch = c.data  # the symbol as drawn (the state's map can lack it, e.g. doorways)
            out.append([ch, name, c.fg if c else "default", bool(c and c.bold)])
        return out

    def msg_rows(self):
        """The game's message rows at the top (cursinit.c: up to 4, the map right under)."""
        return max(1, min(4, self.gh - 23))

    def resize(self, cols, rows):
        self.gw, self.gh = max(80, cols), max(24, rows)
        self.screen.resize(self.gh, self.gw)
        try:
            self._winsize()
            os.kill(self.pid, signal.SIGWINCH)
        except OSError:  # no game right now (ended, or restarting)
            pass

    def key(self, data):
        """Keys typed into the terminal: ⌃G shortcuts, the saves list, else the game."""
        if self.leader:
            self.leader = False
            letter = {k: v for k, v in helper.LEADER_KEYS.items() if k in "fduwsrl"}.get(data.decode("latin-1").lower())
            if letter:
                self.command(ctrl_opt(letter))
            return
        if data == helper.LEADER:
            self.leader = True
        elif self.saves_ui:
            self.saves_key(data)
        elif self.over:
            self.open_saves()
        else:
            self.game_key(data)

    def command(self, code):
        """A toolbar button or ⌃G letter (the TUI's handle_key, for the codes it shares)."""
        if code == helper.SAVES_KEY:
            self.open_saves()
        elif code in helper.FKEYS:
            self.send(helper.FKEYS[code])
        elif code == helper.WHAT_NOW:
            self.ask("What should I do right now?")
        elif code == helper.SNAPSHOT:
            if not self.save_game("checkpoint"):
                self.say("dim", "Checkpoints happen at the command prompt; finish this first.")
        elif code == helper.REWIND:
            last = saves.snapshots(SNAPS, self.save_name)
            if not self.save_name or not last:
                self.say("dim", "No checkpoint yet (one is made on each new level, or press ⌃G s).")
            else:
                self.request_load(next(i for i in saves.listing(SAVES, SNAPS) if i["path"] == last[-1]))

    def wait_for(self, text, other=None, timeout=3):
        """Wait until the game's screen shows text (or other); which one, or None."""
        end = time.time() + timeout
        while time.time() < end:
            with self.lock:
                screen = "\n".join(self.row_text(r) for r in range(self.gh))
            for t in (text, other):
                if t and t in screen:
                    return t
            time.sleep(0.05)
        return None

    def drop_group(self, sym, letters):
        """D, the class (when D asks for one), then those items, one step at a time
        so a keystroke never lands in the wrong menu."""
        items = "What would you like to drop?"
        with self.lock:
            self.send(b"D")
        got = self.wait_for("Drop what type of items?", items)
        if got and got != items:
            with self.lock:
                self.send(sym.encode() + b"\r")  # a class's symbol picks it in that menu
            got = self.wait_for(items)
        with self.lock:
            if got:
                self.send("".join(letters).encode() + b"\r")
            else:
                self.send(b"\x1b\x1b")
                self.say("err", "Couldn't drop that group: the game didn't show the menus I expected.")
            self.push_state()

    def run(self):
        """Game output to the browsers; the game ending or restarting."""
        while True:
            r = []
            if not self.over:
                try:
                    r, _, _ = select.select([self.fd], [], [], 0.2)
                except (OSError, ValueError):
                    time.sleep(0.2)
            else:
                time.sleep(0.2)
            with self.lock:
                if r:
                    try:
                        data = os.read(self.fd, 65536)
                    except OSError:
                        data = b""
                    if data:
                        self.stream.feed(data)
                        self.emit("out", base64.b64encode(data).decode())
                    elif not self.game_exited():  # saved with S: offer the saves list
                        self.over = True
                        self.open_saves()
                        self.say("dim", "Game saved. Pick a game to play (Enter), or n for a new one.")
                seq = self.seq
                self.check_warnings()
                if self.seq != seq or r:
                    self.push_state()


class Handler(BaseHTTPRequestHandler):
    web = None

    def log_message(self, *a):
        pass

    def body(self):
        return json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")

    def reply(self, code=204, data=b"", kind="text/plain"):
        self.send_response(code)
        self.send_header("Content-Type", kind)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        w = self.web
        if self.path == "/":
            with open(PAGE, "rb") as f:
                return self.reply(200, f.read(), "text/html; charset=utf-8")
        if self.path.startswith("/preview?"):  # a checkpoint's map, for the saves list
            want = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query).get("path", [""])[0]
            if want not in {i["preview"] for i in saves.listing(SAVES, SNAPS) if i["preview"]}:
                return self.reply(404)
            with open(want, "rb") as f:
                return self.reply(200, f.read(), "application/json")
        if self.path != "/events":
            return self.reply(404)
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        q = queue.Queue()
        with w.lock:
            q.put(("out", base64.b64encode(ansi(w.screen).encode()).decode()))
            w.clients.append(q)
            w.push_state()
        try:
            while True:
                try:
                    kind, data = q.get(timeout=15)
                    self.wfile.write(f"event: {kind}\ndata: {json.dumps(data)}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                self.wfile.flush()
        except OSError:
            pass
        finally:
            w.clients.remove(q)

    def do_POST(self):
        w, d = self.web, self.body()
        with w.lock:
            if self.path == "/key":  # what xterm.js typed (Option sends Esc+key)
                w.key(d["data"].encode("latin-1", "ignore"))
            elif self.path == "/resize":
                w.resize(int(d["cols"]), int(d["rows"]))
            elif self.path == "/ask" and d.get("q", "").strip():
                w.ask(d["q"].strip())
            elif self.path == "/command" and d.get("name") in COMMANDS:
                w.command(COMMANDS[d["name"]])
            elif self.path == "/settings" and d.get("model") in helper.MODELS:
                helper.save_settings(model=d["model"])
                w.say("dim", f"The helper now uses {d['model']}.")
            elif self.path == "/saves":  # open the list, or a click on a row then a key
                if not w.saves_ui:
                    w.open_saves()
                if d.get("sort") in SORTS:
                    w.saves_sort = d["sort"]
                if "sel" in d and w.saves_ui:
                    w.saves_ui["sel"] = int(d["sel"])
                if d.get("key") and w.saves_ui:
                    w.saves_key(d["key"].encode("latin-1", "ignore"))
            elif self.path == "/dropgroup":  # D, then every item of that class not in use, then Enter
                loose = [i["letter"] for i in w.watcher.state.get("inventory", [])
                         if i.get("class") == d.get("sym") and not helper.IN_USE.search(i["text"])]
                if (w.watcher.state.get("context") or {}).get("kind") != "command":
                    w.say("dim", "Dropping a group works at the command prompt; finish this first.")
                elif loose:
                    threading.Thread(target=w.drop_group, args=(d["sym"], loose), daemon=True).start()
            elif self.path == "/item":  # an inventory action: command key, then the item
                if d["key"] == "":  # answer the game's question with this item
                    w.send(d["letter"].encode())
                else:
                    text = next((i["text"] for i in w.watcher.state.get("inventory", []) if i["letter"] == d["letter"]), "")
                    w.item_action(d["key"], d["letter"], text)
            w.push_state()
        self.reply()


def main():
    os.environ["NETHACK_WEB"] = "1"  # no window borders; menus keep clear of the rows the page hides
    srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)  # first: a taken port starts no game
    web = Web(saves.default_args(sys.argv[1:], SAVES, SNAPS))
    Handler.web = web
    threading.Thread(target=web.run, daemon=True).start()
    srv.daemon_threads = True
    signal.signal(signal.SIGHUP, lambda *_: sys.exit())
    signal.signal(signal.SIGTERM, lambda *_: sys.exit())
    print(f"NetHack: http://127.0.0.1:{PORT}  (Ctrl-C saves and quits)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        with web.lock:
            web.close()  # the game saves on hangup, and that save becomes a checkpoint


if __name__ == "__main__":
    main()
