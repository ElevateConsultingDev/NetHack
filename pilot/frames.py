"""Record every frame of a game as it is played, and write its step-by-step replay page.

The batch keeps a Recorder on each Game; at the end it writes
playground/batch/replay-<name>.html (self-contained: data embedded), which
the dashboard links to. Older games can be backfilled by replaying them:

    python3 -m pilot.frames <run>/<name>      # rules games only (Jev and Haiku answers are not replayable)
"""

from __future__ import annotations

import json
import os
import sys

from .brain import _brief

HERE = os.path.dirname(__file__)
TEMPLATE = os.path.join(HERE, "replay_template.html")
NAMES = {"\r": "Enter", "\x1b": "Esc", "\n": "Enter", "\x04": "kick "}


def keyname(k: str) -> str:
    return "".join(NAMES.get(ch, ch) for ch in k or "")


class Recorder:
    def __init__(self) -> None:
        self.rows: list[str] = []
        self.row_ix: dict[str, int] = {}
        self.frames: list[list] = []
        self.invs: list[list[str]] = []
        self.inv_ix: dict[tuple, int] = {}
        self.escs: list[dict] = []
        self.truths: list = []  # the real level, on arrival and every 50 turns
        self.seen_escalations = 0
        self.seen_jev = 0

    def _rid(self, r: str) -> int:
        if r not in self.row_ix:
            self.row_ix[r] = len(self.rows)
            self.rows.append(r)
        return self.row_ix[r]

    def see_truth(self, t: dict, s: dict) -> None:
        """The level as it really is (src/aipipe.c put_truth): kept beside the frames so the replay
        can show what the pilot had not seen."""
        self.truths.append({"t": (s.get("status") or {}).get("turn", 0), "m": [self._rid(r.rstrip()) for r in t["map"]],
                            "o": [[o["x"], o["y"], o["class"], o["name"]] for o in t["objects"]],
                            "s": t.get("secrets") or [],  # [x, y, 1 for a secret door / 0 for a secret corridor]
                            "n": [[m["x"], m["y"], m["sym"], m["name"], m["peaceful"]] for m in t["monsters"]]})

    def record(self, g, s: dict) -> None:
        """Call after the engine has handled snapshot s (g.engine.note and g.keys are current)."""
        if "map" not in s:
            return
        st = s.get("status", {})
        p = s.get("player") or {}
        c = g.engine.last_checks or {}
        m = [self._rid(r.rstrip()) for r in s["map"]]
        while m and self.rows[m[-1]] == "":
            m.pop()
        msgs = [x for x in (s.get("messages") or []) if x and not x.startswith("Count:")]
        inv = tuple(f"{i['letter']} - {i['text']}" for i in s.get("inventory", []))
        if inv not in self.inv_ix:
            self.inv_ix[inv] = len(self.invs)
            self.invs.append(list(inv))
        host = ", ".join(f"{h['name']} ({h['distance']} away, difficulty {h['difficulty']})"
                         for h in (c.get("visible_hostiles") or [])[:5])
        chk = [c.get("wounded") or "", 1 if c.get("prayer_safe") else 0, c.get("prayer_opens_in"),
               1 if c.get("level_explored") else 0, 1 if c.get("stairs_down") else 0,
               ", ".join(c.get("major_trouble") or []), host]
        turn = st.get("turn", 0)
        key = keyname(g.keys[-1][1]) if g.keys and g.keys[-1][0] == turn else ""
        stats = g.engine.memory.stats
        f = [turn, st.get("dlvl", 0), st.get("hp", 0), st.get("hpmax", 0), st.get("xlvl", 0), st.get("ac", 0),
             st.get("gold", 0), (st.get("hunger") or "").strip(), p.get("x", 0), p.get("y", 0),
             (g.engine.note or "")[:110], " ".join(msgs).split(" Do you want")[0][:220], m, key,
             st.get("pw", 0), st.get("pwmax", 0), chk, self.inv_ix[inv], g.engine.routine or "",
             stats.get("kills", 0), len(g.escalations) + self.seen_jev, len(self.truths) - 1]
        if self.frames and self.frames[-1][12] == m and self.frames[-1][0] == f[0]:
            prev = self.frames[-1]
            if f[11]:
                prev[11] = (prev[11] + " " + f[11]).strip()[:260]
            for k in (2, 10, 13, 16, 17, 18, 19, 20):
                if f[k] not in ("", None):
                    prev[k] = f[k]
        else:
            self.frames.append(f)
        here = len(self.frames) - 1
        while self.seen_escalations < len(g.escalations):
            turn_e, ev, routine = g.escalations[self.seen_escalations]
            ans = g.answers[self.seen_escalations] if self.seen_escalations < len(g.answers) else {}
            self.escs.append({"i": here, "t": turn_e, "ask": ev, "routine": routine or "(no answer)",
                              "say": ans.get("say", ""), "brief": _brief(c, ev.split("; "), s, None, g.engine.orders)})
            self.seen_escalations += 1
        jev = getattr(g.engine, "last_ask", None)  # Jev mode: (turn, state, answer) for this turn
        if jev and jev[0] == turn and self.seen_jev < getattr(g.engine, "calls", 0):
            self.seen_jev = g.engine.calls
            top = sorted(jev[2]["probabilities"].items(), key=lambda kv: -kv[1])[:5]
            self.escs.append({"i": here, "t": turn, "ask": "which action now? (state below)", "routine": jev[2]["choice"],
                              "say": ", ".join(f"{a} {p:.2f}" for a, p in top), "p": jev[2]["probabilities"],
                              "brief": json.dumps(jev[1], indent=1)})
            self.frames[-1][20] = self.seen_jev

    def data(self, g, run: str) -> dict:
        st = g.engine.memory.stats
        turns = sorted(((k[7:], v) for k, v in st.items() if k.startswith("turns: ")), key=lambda kv: -kv[1])[:12]
        r = g.result or {}
        return {"name": g.name, "run": run, "brain": g.brain.name, "seed": g.seed, "death": r.get("death") or "",
                "stall": g.stall or "", "deepest": g.deepest, "rows": self.rows, "frames": self.frames, "truths": self.truths,
                "invs": self.invs, "escs": self.escs, "orders": g.engine.orders, "turns": turns,
                "totals": {"kills": st.get("kills", 0), "corpses eaten": st.get("corpses_eaten", 0),
                           "prayers": len(g.engine.memory.prayer_log), "keys sent": len(g.keys),
                           "questions to the brain": len(self.escs)}}

    def write_page(self, path: str, g, run: str) -> None:
        if not self.frames:
            return
        payload = json.dumps(self.data(g, run), separators=(",", ":")).replace("</", "<\\/")
        with open(TEMPLATE) as f:
            page = f.read().replace("__DATA__", payload)
        tmp = f"{path}.{os.getpid()}.tmp"
        with open(tmp, "w") as f:
            f.write(page)
        os.replace(tmp, path)


def backfill(which: str) -> str:
    """Replay a recorded rules game and write its replay page."""
    from .batch import PLAYGROUND, Game, RuleBrain, prepare_playground
    run, name = which.split("/")
    with open(os.path.join(PLAYGROUND, "batch", f"{run}.json")) as f:
        rec = next(g for g in json.load(f)["games"] if g["name"] == name)
    prepare_playground()
    g = Game(f"D{name[1:]}", rec.get("role", "Valkyrie"), RuleBrain(), int(rec["turn"]) + 50, 900, save_on_stall=False,
             out_dir=os.path.join(PLAYGROUND, "replays"), seed=rec["seed"])
    g.name = name
    g.play()
    path = os.path.join(PLAYGROUND, "batch", f"replay-{name}.html")
    g.frames.write_page(path, g, run)
    return path


if __name__ == "__main__":
    print(backfill(sys.argv[1]))
