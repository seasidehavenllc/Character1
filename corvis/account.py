"""This device's Corvis account: signs in to the home PC's hub and keeps memories in sync."""

from __future__ import annotations

import json
import platform
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from .memory import MemoryStore

DEFAULT_ACCOUNT_FILE = Path(__file__).resolve().parent.parent / "data" / "account.json"


class HubError(Exception):
    pass


class Account:
    def __init__(self, path: str | Path = DEFAULT_ACCOUNT_FILE):
        self.path = Path(path)
        self.data: dict[str, Any] = {}
        if self.path.exists():
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
        self.last_sync: float | None = None
        self.hub_online = False

    @property
    def signed_in(self) -> bool:
        return bool(self.data.get("token"))

    @property
    def hub_url(self) -> str:
        return self.data.get("hub_url", "")

    @property
    def username(self) -> str:
        return self.data.get("username", "")

    @property
    def token(self) -> str:
        return self.data.get("token", "")

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(self.data, indent=2), encoding="utf-8")
        try:
            self.path.chmod(0o600)  # the token is a password-equivalent
        except OSError:
            pass

    def _request(self, path: str, body: dict | None = None, timeout: float = 5.0,
                 hub_url: str | None = None) -> dict[str, Any]:
        url = (hub_url or self.hub_url).rstrip("/") + path
        headers = {"Content-Type": "application/json"}
        if self.token and hub_url is None:
            headers["Authorization"] = f"Bearer {self.token}"
        req = urllib.request.Request(url, data=json.dumps(body).encode() if body is not None else None,
                                     headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            try:
                msg = json.load(e).get("error", str(e))
            except ValueError:
                msg = str(e)
            raise HubError(msg) from None
        except OSError as e:
            raise HubError(f"Can't reach the hub at {url.rsplit('/', 2)[0]} ({e})") from None

    def sign_in(self, hub_url: str, username: str, password: str, register: bool = False) -> None:
        hub_url = hub_url.strip().rstrip("/")
        if "://" not in hub_url:
            hub_url = "http://" + hub_url
        path = "/auth/register" if register else "/auth/login"
        res = self._request(path, {"username": username, "password": password, "device": platform.node()},
                            hub_url=hub_url)
        self.data = {"hub_url": hub_url, "username": username.strip().lower(), "token": res["token"],
                     "cursor": 0}
        self._save()
        self.hub_online = True

    def sign_out(self) -> None:
        self.data = {}
        self.hub_online = False
        if self.path.exists():
            self.path.unlink()

    def check_hub(self, timeout: float = 1.5) -> bool:
        """Is the home PC reachable right now?"""
        if not self.signed_in:
            self.hub_online = False
            return False
        try:
            self._request("/hub/info", timeout=timeout)
            self.hub_online = True
        except HubError:
            self.hub_online = False
        return self.hub_online

    def hub_models(self) -> list[str]:
        try:
            return [m["id"] for m in self._request("/brain/v1/models", timeout=3).get("data", [])]
        except HubError:
            return []

    def sync(self, memory: MemoryStore) -> int:
        """Two-way memory sync with the hub. Returns how many changes came in from other devices."""
        if not self.signed_in:
            return 0
        outgoing = memory.pending_changes()
        res = self._request("/sync", {"cursor": self.data.get("cursor", 0), "changes": outgoing}, timeout=10)
        memory.mark_synced([c["uuid"] for c in outgoing])
        applied = memory.apply_remote(res["changes"])
        self.data["cursor"] = res["cursor"]
        self._save()
        self.last_sync = time.time()
        self.hub_online = True
        return applied

    def try_sync(self, memory: MemoryStore) -> int | None:
        """Sync if the hub is reachable; None when offline (changes wait for next time)."""
        try:
            return self.sync(memory)
        except HubError:
            self.hub_online = False
            return None
