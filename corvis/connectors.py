"""Connectors: link outside apps and services to Corvis, like Claude's connectors.

A connector is an MCP server (see mcp_client.py). Its tools become Corvis tools, named
`mcp_<connector>__<tool>`, so every bot that's allowed to use connectors can call them.

- Stored in data/connectors.json. Tokens and environment values are kept there (data/ is
  never synced to Git) and are never sent back to the app; the app only sees that one is set.
- Actions that change something ask the owner first. A tool the server marks read-only
  runs without asking, unless the owner set the connector to "always ask".
- Plugins can bring their own connectors; those come and go with the plugin.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Callable

from .mcp_client import HttpTransport, MCPClient, MCPError, StdioTransport

APPROVAL_MODES = {
    "ask": "Ask before actions that change things",
    "always": "Ask before every use",
    "never": "Never ask (only for connectors you fully trust)",
}

# Ready-made connectors (Claude's "directory"). Programs run with Node.js (npx) or uv (uvx).
CATALOG = [
    {"id": "github", "name": "GitHub", "kind": "http", "url": "https://api.githubcopilot.com/mcp/",
     "token_label": "GitHub personal access token",
     "about": "Repositories, issues, pull requests and code search on GitHub.",
     "setup": "Create a token at github.com → Settings → Developer settings → Personal access tokens."},
    {"id": "filesystem", "name": "Filesystem", "kind": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-filesystem", "{folder}"],
     "about": "Read and edit files in one folder you choose.", "needs": "Node.js", "asks": ["folder"]},
    {"id": "fetch", "name": "Fetch", "kind": "stdio", "command": "uvx", "args": ["mcp-server-fetch"],
     "about": "Fetch web pages and turn them into readable text.", "needs": "uv (astral.sh/uv)"},
    {"id": "git", "name": "Git", "kind": "stdio", "command": "uvx",
     "args": ["mcp-server-git", "--repository", "{folder}"],
     "about": "Read history, diffs and branches of a local Git repository.", "needs": "uv (astral.sh/uv)",
     "asks": ["folder"]},
    {"id": "memory", "name": "Knowledge graph memory", "kind": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-memory"],
     "about": "A notebook of people, projects and how they connect.", "needs": "Node.js"},
    {"id": "everything", "name": "MCP test server", "kind": "stdio", "command": "npx",
     "args": ["-y", "@modelcontextprotocol/server-everything"],
     "about": "Sample tools for checking that connectors work.", "needs": "Node.js"},
]

RETRY_AFTER = 60  # seconds before retrying a connector that failed to connect
_SLUG = re.compile(r"[^a-z0-9]+")


def slug(text: str) -> str:
    return _SLUG.sub("_", text.lower()).strip("_")[:24] or "connector"


def tool_name(conn_slug: str, name: str) -> str:
    """Model-safe, unique tool names (letters, digits, _ and -, at most 64 characters)."""
    clean = re.sub(r"[^A-Za-z0-9_-]", "_", name)
    full = f"mcp_{conn_slug}__{clean}"
    if len(full) <= 64:
        return full
    digest = hashlib.sha1(full.encode()).hexdigest()[:6]
    return full[:57] + "_" + digest


class ConnectorStore:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "connectors.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _read(self) -> list[dict]:
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, items: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)  # holds tokens
        except OSError:
            pass
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        return self._read()

    def get(self, cid: str) -> dict:
        for c in self._read():
            if c["id"] == cid:
                return c
        raise KeyError(cid)

    def add(self, data: dict) -> dict:
        conn = validate(data)
        with self._lock:
            items = self._read()
            taken = {c["slug"] for c in items}
            base, n = conn["slug"], 2
            while conn["slug"] in taken:
                conn["slug"] = f"{base[:21]}_{n}"
                n += 1
            items.append(conn)
            self._write(items)
        return conn

    def update(self, cid: str, changes: dict) -> dict:
        with self._lock:
            items = self._read()
            for c in items:
                if c["id"] != cid:
                    continue
                if "enabled" in changes:
                    c["enabled"] = bool(changes["enabled"])
                if changes.get("approval") in APPROVAL_MODES:
                    c["approval"] = changes["approval"]
                if changes.get("token"):
                    c["token"] = str(changes["token"]).strip()
                if isinstance(changes.get("env"), dict):
                    c["env"] = {**c.get("env", {}), **_clean_env(changes["env"])}
                self._write(items)
                return c
        raise KeyError(cid)

    def remove(self, cid: str) -> None:
        with self._lock:
            items = [c for c in self._read() if c["id"] != cid]
            self._write(items)


def _clean_env(env: dict) -> dict[str, str]:
    out = {}
    for k, v in env.items():
        k = str(k).strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,63}", k):
            raise ValueError(f"'{k}' isn't a valid environment variable name.")
        out[k] = str(v)
    return out


def validate(data: dict, source: str = "you") -> dict:
    name = str(data.get("name") or "").strip()[:60]
    if not name:
        raise ValueError("Give the connector a name.")
    kind = data.get("kind")
    conn = {"id": uuid.uuid4().hex[:10], "name": name, "slug": slug(data.get("slug") or name), "kind": kind,
            "enabled": data.get("enabled", True) is not False, "source": source,
            "approval": data.get("approval") if data.get("approval") in APPROVAL_MODES else "ask",
            "added": time.time()}
    if kind == "http":
        url = str(data.get("url") or "").strip()
        if not re.match(r"^https?://", url):
            raise ValueError("A remote connector needs a web address starting with https://")
        if url.startswith("http://") and not re.match(r"^http://(localhost|127\.0\.0\.1)(:|/)", url):
            raise ValueError("Use https:// for remote connectors (plain http only for this computer).")
        conn["url"] = url
        conn["token"] = str(data.get("token") or "").strip()
        conn["headers"] = {str(k): str(v) for k, v in (data.get("headers") or {}).items()}
    elif kind == "stdio":
        command = str(data.get("command") or "").strip()
        if not command:
            raise ValueError("A local connector needs the program to run (for example npx or uvx).")
        args = data.get("args") or []
        if isinstance(args, str):
            args = args.split()
        conn["command"] = command
        conn["args"] = [str(a) for a in args][:40]
        conn["env"] = _clean_env(data.get("env") or {})
        conn["cwd"] = str(data.get("cwd") or "") or None
    else:
        raise ValueError("Choose a remote (web address) or local (program) connector.")
    return conn


def public(conn: dict) -> dict:
    """What the app may see: never the token or env values."""
    out = {k: v for k, v in conn.items() if k not in ("token", "env", "headers")}
    out["has_token"] = bool(conn.get("token"))
    out["env_names"] = sorted((conn.get("env") or {}).keys())
    out["header_names"] = sorted((conn.get("headers") or {}).keys())
    return out


def _expand(value: str) -> str:
    """${NAME} in a value is replaced by that environment variable on this machine."""
    return re.sub(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}", lambda m: os.environ.get(m.group(1), ""), value)


def open_client(conn: dict) -> MCPClient:
    if conn["kind"] == "http":
        headers = {k: _expand(v) for k, v in (conn.get("headers") or {}).items()}
        if conn.get("token"):
            headers.setdefault("Authorization", f"Bearer {_expand(conn['token'])}")
        transport = HttpTransport(conn["url"], headers)
    else:
        env = {k: _expand(v) for k, v in (conn.get("env") or {}).items()}
        transport = StdioTransport(conn["command"], conn.get("args"), env, conn.get("cwd"))
    client = MCPClient(transport)
    try:
        client.connect()
    except Exception:
        client.close()
        raise
    return client


class ConnectorManager:
    """Keeps one live connection per connector and remembers its tools and status."""

    def __init__(self, store: ConnectorStore, extra: Callable[[], list[dict]] | None = None):
        self.store = store
        self.extra = extra or (lambda: [])   # connectors that plugins bring
        self._clients: dict[str, MCPClient] = {}
        self._tools: dict[str, list[dict]] = {}
        self._status: dict[str, dict] = {}
        self._locks: dict[str, threading.Lock] = {}
        self._guard = threading.Lock()

    def all(self) -> list[dict]:
        return self.store.list() + self.extra()

    def find(self, cid: str) -> dict:
        for c in self.all():
            if c["id"] == cid:
                return c
        raise KeyError(cid)

    def _lock_for(self, cid: str) -> threading.Lock:
        with self._guard:
            return self._locks.setdefault(cid, threading.Lock())

    def status(self, cid: str) -> dict:
        return self._status.get(cid, {"state": "idle"})

    def connect(self, conn: dict, force: bool = False) -> list[dict]:
        """Connect if needed and return the connector's tools (cached)."""
        cid = conn["id"]
        with self._lock_for(cid):
            if cid in self._clients and not force:
                return self._tools[cid]
            last = self._status.get(cid, {})
            if not force and last.get("state") == "error" and time.time() - last.get("at", 0) < RETRY_AFTER:
                raise MCPError(last["error"])  # failed moments ago; don't stall every step retrying
            self._drop(cid)
            self._status[cid] = {"state": "connecting"}
            try:
                client = open_client(conn)
                tools = client.list_tools()
            except Exception as e:
                self._status[cid] = {"state": "error", "error": str(e)[:600], "at": time.time()}
                raise
            self._clients[cid], self._tools[cid] = client, tools
            info = client.server_info
            self._status[cid] = {"state": "connected", "tools": len(tools), "at": time.time(),
                                 "server": f"{info.get('name', '')} {info.get('version', '')}".strip()}
            return tools

    def call(self, conn: dict, name: str, args: dict) -> str:
        cid = conn["id"]
        for attempt in (1, 2):
            if cid not in self._clients:
                self.connect(conn)
            try:
                return self._clients[cid].call_tool(name, args)
            except MCPError as e:
                # One reconnect if the server went away; a real tool error goes back to the agent.
                if attempt == 2 or not _looks_disconnected(str(e)):
                    raise
                self.disconnect(cid)
        raise MCPError("unreachable")

    def tools_for_agent(self, approver: Callable[[str], bool]) -> dict:
        """Corvis tools for every enabled connector that connects."""
        from .tools.base import Tool

        out: dict = {}
        for conn in self.all():
            if not conn.get("enabled", True):
                continue
            try:
                tools = self.connect(conn)
            except Exception:
                continue  # shown as an error in the Connectors panel; the agent carries on
            for t in tools:
                name = tool_name(conn["slug"], t.get("name", "tool"))
                out[name] = Tool(
                    name,
                    f"[{conn['name']} connector] {(t.get('description') or t.get('title') or t['name'])[:900]}",
                    _schema(t.get("inputSchema")),
                    _caller(self, conn, t, approver),
                )
        return out

    def disconnect(self, cid: str) -> None:
        with self._lock_for(cid):
            self._drop(cid)
            self._status.pop(cid, None)

    def _drop(self, cid: str) -> None:
        client = self._clients.pop(cid, None)
        self._tools.pop(cid, None)
        if client:
            try:
                client.close()
            except Exception:
                pass

    def close_all(self) -> None:
        for cid in list(self._clients):
            self.disconnect(cid)


def _looks_disconnected(msg: str) -> bool:
    return any(s in msg for s in ("exited", "stopped", "Lost the connector", "session expired", "Couldn't reach"))


def _schema(schema) -> dict:
    if not isinstance(schema, dict) or schema.get("type") != "object":
        return {"type": "object", "properties": {}}
    return {"type": "object", "properties": schema.get("properties") or {},
            "required": schema.get("required") or []}


def needs_ok(conn: dict, tool: dict) -> bool:
    mode = conn.get("approval", "ask")
    if mode == "never":
        return False
    if mode == "always":
        return True
    hints = tool.get("annotations") or {}
    return hints.get("readOnlyHint") is not True


def _caller(manager: ConnectorManager, conn: dict, tool: dict, approver: Callable[[str], bool]):
    def call(**args) -> str:
        if needs_ok(conn, tool):
            shown = json.dumps(args, ensure_ascii=False)
            shown = shown if len(shown) < 600 else shown[:600] + "…"
            if not approver(f"Use {conn['name']} → {tool['name']}?\n{shown}"):
                return "The owner declined this connector action."
        return manager.call(conn, tool["name"], args)
    return call


_shared: dict[str, ConnectorManager] = {}
_shared_lock = threading.Lock()


def shared(data_dir: str | Path, extra: Callable[[], list[dict]] | None = None) -> ConnectorManager:
    """One manager per data folder, so connections are reused across chats."""
    key = str(Path(data_dir).resolve())
    with _shared_lock:
        if key not in _shared:
            _shared[key] = ConnectorManager(ConnectorStore(data_dir), extra)
        elif extra is not None:
            _shared[key].extra = extra
        return _shared[key]
