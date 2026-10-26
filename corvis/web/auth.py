"""Owner login for using Corvis from your phone or another device.

- The owner password is stored only as a scrypt hash (data/auth.json).
- Signing in gives the device a random session cookie (stored hashed, 30 days).
- The PC launcher signs the PC in automatically with a one-time token, so you only
  type the password on other devices.
- Failed sign-ins are rate limited.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
from pathlib import Path

SESSION_DAYS = 30
MIN_PASSWORD = 10
MAX_FAILURES = 5          # per window
FAILURE_WINDOW = 300      # seconds
LAUNCH_TOKEN_SECONDS = 120


def _hash_password(password: str, salt: bytes) -> str:
    return hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


class Auth:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "auth.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._failures: list[float] = []
        self._launch: dict[str, float] = {}

    # --- storage ------------------------------------------------------------------
    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    # --- password -----------------------------------------------------------------
    def has_password(self) -> bool:
        return "password" in self._read()

    def set_password(self, password: str) -> None:
        if len(password) < MIN_PASSWORD:
            raise ValueError(f"Use at least {MIN_PASSWORD} characters.")
        salt = secrets.token_bytes(16)
        with self._lock:
            data = self._read()
            data["password"] = {"salt": salt.hex(), "hash": _hash_password(password, salt),
                                "set": time.time()}
            data["sessions"] = {}  # a new password signs every device out
            self._write(data)

    def check_password(self, password: str) -> bool:
        stored = self._read().get("password")
        if not stored:
            return False
        candidate = _hash_password(password, bytes.fromhex(stored["salt"]))
        return hmac.compare_digest(candidate, stored["hash"])

    # --- rate limiting ------------------------------------------------------------
    def locked_for(self) -> int:
        """Seconds until another sign-in attempt is allowed (0 = allowed now)."""
        now = time.time()
        self._failures = [t for t in self._failures if now - t < FAILURE_WINDOW]
        if len(self._failures) < MAX_FAILURES:
            return 0
        return int(FAILURE_WINDOW - (now - self._failures[0])) + 1

    def login(self, password: str, device: str = "") -> str | None:
        """Returns a new session token, or None if the password is wrong."""
        if self.locked_for():
            return None
        if not self.check_password(password):
            self._failures.append(time.time())
            time.sleep(0.4)  # slows down guessing a little more
            return None
        self._failures.clear()
        return self.new_session(device)

    # --- sessions -----------------------------------------------------------------
    def new_session(self, device: str = "") -> str:
        token = secrets.token_urlsafe(32)
        with self._lock:
            data = self._read()
            sessions = data.setdefault("sessions", {})
            now = time.time()
            for key in [k for k, s in sessions.items() if s["expires"] < now]:
                del sessions[key]
            sessions[_hash_token(token)] = {"created": now, "expires": now + SESSION_DAYS * 86400,
                                            "device": device[:120]}
            self._write(data)
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        s = self._read().get("sessions", {}).get(_hash_token(token))
        return bool(s) and s["expires"] > time.time()

    def logout(self, token: str | None) -> None:
        if not token:
            return
        with self._lock:
            data = self._read()
            data.get("sessions", {}).pop(_hash_token(token), None)
            self._write(data)

    def logout_everywhere(self) -> None:
        with self._lock:
            data = self._read()
            data["sessions"] = {}
            self._write(data)

    def session_count(self) -> int:
        now = time.time()
        return sum(1 for s in self._read().get("sessions", {}).values() if s["expires"] > now)

    # --- one-time token so the PC's own browser is signed in automatically ---------
    def launch_token(self) -> str:
        token = secrets.token_urlsafe(24)
        self._launch[token] = time.time() + LAUNCH_TOKEN_SECONDS
        return token

    def use_launch_token(self, token: str) -> bool:
        expires = self._launch.pop(token, 0)
        return expires > time.time()
