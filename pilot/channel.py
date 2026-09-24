"""The controller end of the aipipe socket (see doc/aipipe.md).

Listens on a Unix socket, hands each JSON state line to a callback on a
reader thread, and sends keys back.
"""

from __future__ import annotations

import json
import os
import socket
import threading
from typing import Callable


class Channel:
    def __init__(self, path: str, on_state: Callable[[dict], None]) -> None:
        self.path = path
        self.on_state = on_state
        self._conn: socket.socket | None = None
        self._lock = threading.Lock()
        self.connected = threading.Event()

    def serve(self) -> None:
        """Accept one game connection and read states until it closes.
        Run on a thread; returns when the game exits."""
        if os.path.exists(self.path):
            os.unlink(self.path)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(self.path)
        srv.listen(1)
        conn, _ = srv.accept()
        srv.close()
        self._conn = conn
        self.connected.set()
        with conn.makefile("r", encoding="utf-8", errors="replace") as lines:
            for line in lines:
                if line.strip():
                    self.on_state(json.loads(line))
        self._conn = None
        self.connected.clear()

    def send(self, keys: str) -> None:
        if not keys or self._conn is None:
            return
        with self._lock:
            self._conn.sendall((json.dumps({"keys": keys}) + "\n").encode())
