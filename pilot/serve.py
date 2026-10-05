"""Local server for the pilot's pages, so the tactics page can change standing orders mid-run.

    python3 -m pilot.serve            # http://127.0.0.1:3067/tactics.html   (PORT=... to change)

Serves playground/batch and accepts POST /orders with {"orders": {...}, "say": "free text"}.
The orders are checked against the engine's standing orders and written to orders.json; games
in flight pick them up within a turn (pilot/batch.py, _live_orders). Loopback only, no login:
do not expose it. Opened as a file instead, the pages work but cannot send orders.
"""

from __future__ import annotations

import functools
import http.server
import json
import os

from .engine import DEFAULT_ORDERS
from .ledger import BATCH


def check(body: bytes) -> dict:
    """The orders file to write, or ValueError naming what is wrong."""
    o = json.loads(body or b"{}")
    orders, say = o.get("orders", {}), str(o.get("say") or "")[:300]
    if not isinstance(orders, dict):
        raise ValueError("orders must be an object")
    bad = [k for k in orders if k not in DEFAULT_ORDERS]
    if bad:
        raise ValueError(f"unknown orders: {', '.join(bad)}")
    wrong = [k for k, v in orders.items() if DEFAULT_ORDERS[k] is not None and v is not None
             and not isinstance(v, type(DEFAULT_ORDERS[k])) and not (isinstance(v, int) and isinstance(DEFAULT_ORDERS[k], float))]
    if wrong:
        raise ValueError(f"wrong type for: {', '.join(wrong)}")
    return {"orders": orders, "say": say}


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/orders":
            return self.send_error(404)
        try:
            o = check(self.rfile.read(min(int(self.headers.get("Content-Length") or 0), 10000)))
        except ValueError as e:
            return self._reply(400, {"error": str(e)})
        tmp = os.path.join(BATCH, "orders.json.tmp")
        with open(tmp, "w") as f:
            json.dump(o, f)
        os.replace(tmp, os.path.join(BATCH, "orders.json"))
        self._reply(200, {"applied": o})

    def _reply(self, code: int, obj: dict) -> None:
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a) -> None:
        pass


if __name__ == "__main__":
    assert check(b'{"orders": {"retreat_below": 0.5}, "say": "be careful"}')["say"] == "be careful"
    for bad in (b'{"orders": {"nope": 1}}', b'{"orders": {"descend": "yes"}}', b'{"orders": []}'):
        try:
            check(bad)
            raise SystemExit(f"accepted {bad!r}")
        except ValueError:
            pass
    port = int(os.environ.get("PORT", 3067))
    print(f"http://127.0.0.1:{port}/tactics.html  (dashboard: /dashboard.html)  Ctrl-C to stop")
    http.server.ThreadingHTTPServer(("127.0.0.1", port), functools.partial(Handler, directory=BATCH)).serve_forever()
