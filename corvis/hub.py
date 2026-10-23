"""Corvis Hub — runs on the user's home PC.

  python -m corvis --hub

It does three things for every device signed in to the same Corvis account:
  1. Accounts: register / log in, one session token per device.
  2. Sync: keeps memories and lessons the same on PC, laptop and phone.
  3. Brain: lets those devices think with the PC's local models (Ollama), so a phone
     gets PC-level intelligence while the PC is reachable.

Reaching the hub from outside your home network: install Tailscale (free) on the PC and
the phone and use the PC's Tailscale address. Don't expose the hub's plain-HTTP port
directly to the internet.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .hardware import detect
from .memory import SYNC_FIELDS

DEFAULT_HUB_DB = Path(__file__).resolve().parent.parent / "data" / "hub.db"
MAX_BODY = 20 * 1024 * 1024


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)


class HubStore:
    def __init__(self, path: str | Path = DEFAULT_HUB_DB):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.lock = threading.Lock()
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY, username TEXT UNIQUE NOT NULL,
                salt BLOB NOT NULL, pw_hash BLOB NOT NULL, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS sessions (
                token_hash TEXT PRIMARY KEY, user_id INTEGER NOT NULL, device TEXT, created_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS memories (
                seq INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, uuid TEXT NOT NULL,
                content TEXT, category TEXT, importance INTEGER, created_at REAL, updated_at REAL, deleted INTEGER,
                UNIQUE(user_id, uuid));
            """
        )

    @staticmethod
    def _token_hash(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def register(self, username: str, password: str) -> None:
        username = username.strip().lower()
        if not username or len(password) < 8:
            raise ValueError("Username required and password must be at least 8 characters.")
        salt = secrets.token_bytes(16)
        with self.lock:
            try:
                self.db.execute("INSERT INTO users (username, salt, pw_hash, created_at) VALUES (?, ?, ?, ?)",
                                (username, salt, hash_password(password, salt), time.time()))
                self.db.commit()
            except sqlite3.IntegrityError:
                raise ValueError("That username is taken.") from None

    def login(self, username: str, password: str, device: str = "") -> str:
        with self.lock:
            row = self.db.execute("SELECT id, salt, pw_hash FROM users WHERE username = ?",
                                  (username.strip().lower(),)).fetchone()
        if not row or not hmac.compare_digest(hash_password(password, row[1]), row[2]):
            raise PermissionError("Wrong username or password.")
        token = secrets.token_urlsafe(32)
        with self.lock:
            self.db.execute("INSERT INTO sessions (token_hash, user_id, device, created_at) VALUES (?, ?, ?, ?)",
                            (self._token_hash(token), row[0], device, time.time()))
            self.db.commit()
        return token

    def user_for(self, token: str) -> int | None:
        with self.lock:
            row = self.db.execute("SELECT user_id FROM sessions WHERE token_hash = ?",
                                  (self._token_hash(token),)).fetchone()
        return row[0] if row else None

    def sync(self, user_id: int, since: int, changes: list[dict[str, Any]]) -> dict[str, Any]:
        """Store this device's changes (newest edit wins), then return everything newer than `since`."""
        with self.lock:
            for c in changes:
                row = self.db.execute("SELECT updated_at FROM memories WHERE user_id = ? AND uuid = ?",
                                      (user_id, c["uuid"])).fetchone()
                if row and row[0] >= c["updated_at"]:
                    continue
                # Delete + insert gives the row a new seq, so other devices see it as new.
                self.db.execute("DELETE FROM memories WHERE user_id = ? AND uuid = ?", (user_id, c["uuid"]))
                self.db.execute(
                    f"INSERT INTO memories (user_id, {', '.join(SYNC_FIELDS)}) VALUES (?, {', '.join('?' * len(SYNC_FIELDS))})",
                    (user_id, *(c[f] for f in SYNC_FIELDS)),
                )
            self.db.commit()
            rows = self.db.execute(
                f"SELECT seq, {', '.join(SYNC_FIELDS)} FROM memories WHERE user_id = ? AND seq > ? ORDER BY seq",
                (user_id, since),
            ).fetchall()
            latest = self.db.execute("SELECT COALESCE(MAX(seq), 0) FROM memories WHERE user_id = ?",
                                     (user_id,)).fetchone()[0]
        return {"changes": [dict(zip(SYNC_FIELDS, r[1:])) for r in rows], "cursor": max(latest, since)}


def make_handler(store: HubStore, local_server: str, name: str, allow_register: bool):
    device = detect()

    class Handler(BaseHTTPRequestHandler):
        def _json(self, data: Any, code: int = 200) -> None:
            body = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _body(self) -> bytes:
            length = int(self.headers.get("Content-Length", 0))
            if length > MAX_BODY:
                raise ValueError("Request too large.")
            return self.rfile.read(length)

        def _user(self) -> int | None:
            auth = self.headers.get("Authorization", "")
            return store.user_for(auth[7:]) if auth.startswith("Bearer ") else None

        def _proxy(self, path: str, body: bytes | None) -> None:
            req = urllib.request.Request(local_server.rstrip("/") + path, data=body,
                                         headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=900) as resp:
                    data, code = resp.read(), resp.status
            except urllib.error.HTTPError as e:
                data, code = e.read(), e.code
            except OSError:
                return self._json({"error": "The PC's model server (Ollama) isn't running."}, 503)
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self) -> None:
            if self.path == "/hub/ping":
                return self._json({"hub": "corvis", "name": name})
            if self._user() is None:
                return self._json({"error": "Sign in required."}, 401)
            if self.path == "/hub/info":
                return self._json({"name": name, "device": device.to_dict(), "summary": device.summary()})
            if self.path == "/brain/v1/models":
                return self._proxy("/models", None)
            self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            try:
                data = self._body()
                if self.path == "/auth/register":
                    if not allow_register:
                        return self._json({"error": "New accounts are turned off on this hub."}, 403)
                    req = json.loads(data)
                    store.register(req["username"], req["password"])
                    return self._json({"token": store.login(req["username"], req["password"], req.get("device", ""))})
                if self.path == "/auth/login":
                    req = json.loads(data)
                    time.sleep(0.3)  # slow down password guessing
                    return self._json({"token": store.login(req["username"], req["password"], req.get("device", ""))})
                user = self._user()
                if user is None:
                    return self._json({"error": "Sign in required."}, 401)
                if self.path == "/sync":
                    req = json.loads(data)
                    return self._json(store.sync(user, int(req.get("cursor", 0)), req.get("changes", [])))
                if self.path == "/brain/v1/chat/completions":
                    return self._proxy("/chat/completions", data)
                self._json({"error": "not found"}, 404)
            except PermissionError as e:
                self._json({"error": str(e)}, 401)
            except (ValueError, KeyError) as e:
                self._json({"error": str(e) or "Bad request."}, 400)

        def log_message(self, *args: Any) -> None:
            pass

    return Handler


def make_hub_server(local_server: str, host: str = "0.0.0.0", port: int = 8810, name: str = "",
                    store: HubStore | None = None, allow_register: bool = True) -> ThreadingHTTPServer:
    import platform

    handler = make_handler(store or HubStore(), local_server, name or platform.node() or "Home PC", allow_register)
    return ThreadingHTTPServer((host, port), handler)


def serve_hub(local_server: str, host: str, port: int, allow_register: bool) -> None:
    server = make_hub_server(local_server, host, port, allow_register=allow_register)
    print(f"Corvis Hub running on port {port}. Devices connect with  http://<this PC's address>:{port}")
    print(f"Thinking with the models from {local_server}. Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nHub stopped.")
