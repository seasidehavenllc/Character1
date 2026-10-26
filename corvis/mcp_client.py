"""A small, synchronous client for MCP (Model Context Protocol) servers.

MCP is the open standard behind Claude's connectors: a server exposes tools (and more)
that an AI can call. Corvis speaks the two standard transports:

- stdio: Corvis starts the server as a program on this machine and talks to it over
  stdin/stdout, one JSON-RPC message per line (e.g. `npx @modelcontextprotocol/server-filesystem`).
- Streamable HTTP: a remote server at a URL; each message is a POST, and the answer comes
  back as JSON or as a short server-sent event stream.

Only the tool features are used (initialize, tools/list, tools/call), which is all Corvis
needs to give connector tools to the agent.
"""
from __future__ import annotations

import collections
import itertools
import json
import os
import queue
import shutil
import subprocess
import threading
from typing import Any

import requests

PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "corvis", "version": "1.2"}
CONNECT_TIMEOUT = 30
CALL_TIMEOUT = 180


class MCPError(RuntimeError):
    pass


class StdioTransport:
    """Runs the server as a child process. Messages are newline-delimited JSON."""

    def __init__(self, command: str, args: list[str] | None = None, env: dict[str, str] | None = None,
                 cwd: str | None = None):
        exe = shutil.which(command) or command
        try:
            self.proc = subprocess.Popen(
                [exe, *(args or [])], stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                env={**os.environ, **(env or {})}, cwd=cwd, text=True, encoding="utf-8", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except OSError as e:
            raise MCPError(f"Couldn't start '{command}': {e}. Is it installed?") from e
        self.inbox: "queue.Queue[dict | None]" = queue.Queue()
        self.stderr_tail: collections.deque[str] = collections.deque(maxlen=20)
        self._write_lock = threading.Lock()
        threading.Thread(target=self._read_stdout, daemon=True, name="mcp-stdout").start()
        threading.Thread(target=self._read_stderr, daemon=True, name="mcp-stderr").start()

    def _read_stdout(self) -> None:
        for line in self.proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                self.inbox.put(json.loads(line))
            except json.JSONDecodeError:
                self.stderr_tail.append(f"(non-JSON output) {line[:200]}")
        self.inbox.put(None)  # the server exited

    def _read_stderr(self) -> None:
        for line in self.proc.stderr:
            self.stderr_tail.append(line.rstrip()[:300])

    def send(self, message: dict) -> None:
        if self.proc.poll() is not None:
            raise MCPError("The connector program has stopped." + self._why())
        with self._write_lock:
            try:
                self.proc.stdin.write(json.dumps(message) + "\n")
                self.proc.stdin.flush()
            except OSError as e:
                raise MCPError(f"Lost the connector program: {e}{self._why()}") from e

    def request(self, message: dict, timeout: float) -> dict:
        self.send(message)
        while True:
            try:
                msg = self.inbox.get(timeout=timeout)
            except queue.Empty:
                raise MCPError(f"The connector didn't answer within {int(timeout)} seconds.") from None
            if msg is None:
                raise MCPError("The connector program exited." + self._why())
            if "method" in msg and "id" in msg:      # the server asks us something
                self._answer_server(msg)
                continue
            if msg.get("id") == message["id"]:
                return msg
            # notifications and stale replies are ignored

    def _answer_server(self, msg: dict) -> None:
        if msg["method"] == "ping":
            self.send({"jsonrpc": "2.0", "id": msg["id"], "result": {}})
        else:  # sampling, elicitation, roots: not offered by Corvis
            self.send({"jsonrpc": "2.0", "id": msg["id"],
                       "error": {"code": -32601, "message": f"Corvis doesn't support {msg['method']}"}})

    def _why(self) -> str:
        tail = "\n".join(list(self.stderr_tail)[-5:])
        return f"\nIts last output:\n{tail}" if tail else ""

    def close(self) -> None:
        if self.proc.poll() is None:
            try:
                self.proc.stdin.close()
                self.proc.wait(timeout=3)
            except (OSError, subprocess.TimeoutExpired):
                self.proc.kill()


class HttpTransport:
    """A remote server over Streamable HTTP."""

    def __init__(self, url: str, headers: dict[str, str] | None = None):
        self.url = url
        self.headers = dict(headers or {})
        self.session_id: str | None = None
        self.protocol: str | None = None
        self.http = requests.Session()

    def _headers(self) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream", **self.headers}
        if self.session_id:
            h["Mcp-Session-Id"] = self.session_id
        if self.protocol:
            h["MCP-Protocol-Version"] = self.protocol
        return h

    def _post(self, message: dict, timeout: float) -> requests.Response:
        try:
            r = self.http.post(self.url, json=message, headers=self._headers(), timeout=timeout, stream=True)
        except requests.RequestException as e:
            raise MCPError(f"Couldn't reach {self.url}: {e}") from e
        if r.status_code in (401, 403):
            raise MCPError("The connector refused access (sign-in or token needed, or the token is wrong).")
        if r.status_code == 404 and self.session_id:
            raise MCPError("The connector's session expired. Reconnect it.")
        if r.status_code >= 400:
            raise MCPError(f"The connector answered with an error ({r.status_code}): {r.text[:300]}")
        sid = r.headers.get("Mcp-Session-Id")
        if sid:
            self.session_id = sid
        return r

    def send(self, message: dict) -> None:
        self._post(message, CONNECT_TIMEOUT).close()

    def request(self, message: dict, timeout: float) -> dict:
        r = self._post(message, timeout)
        ctype = r.headers.get("Content-Type", "")
        if "text/event-stream" in ctype:
            data: list[str] = []
            for raw in r.iter_lines(decode_unicode=True):
                if raw is None:
                    continue
                if raw.startswith("data:"):
                    data.append(raw[5:].lstrip())
                elif raw == "" and data:        # end of one event
                    try:
                        msg = json.loads("\n".join(data))
                    except json.JSONDecodeError:
                        msg = {}
                    data = []
                    if isinstance(msg, dict) and msg.get("id") == message["id"] and "method" not in msg:
                        r.close()
                        return msg
            if data:  # the stream ended without a final blank line
                try:
                    msg = json.loads("\n".join(data))
                    if msg.get("id") == message["id"]:
                        return msg
                except (json.JSONDecodeError, AttributeError):
                    pass
            raise MCPError("The connector closed the stream without answering.")
        try:
            msg = r.json()
        except ValueError as e:
            raise MCPError(f"The connector sent something that isn't JSON: {r.text[:200]}") from e
        if isinstance(msg, list):  # a batch: find our answer
            msg = next((m for m in msg if m.get("id") == message["id"]), {})
        return msg

    def close(self) -> None:
        if self.session_id:
            try:
                self.http.delete(self.url, headers=self._headers(), timeout=5)
            except requests.RequestException:
                pass
        self.http.close()


class MCPClient:
    def __init__(self, transport):
        self.transport = transport
        self._ids = itertools.count(1)
        self._lock = threading.Lock()
        self.server_info: dict = {}
        self.instructions = ""

    def _call(self, method: str, params: dict | None = None, timeout: float = CALL_TIMEOUT) -> Any:
        message = {"jsonrpc": "2.0", "id": next(self._ids), "method": method}
        if params is not None:
            message["params"] = params
        with self._lock:
            reply = self.transport.request(message, timeout)
        if "error" in reply:
            err = reply["error"] or {}
            raise MCPError(f"{err.get('message', 'Unknown error')} (code {err.get('code')})")
        return reply.get("result", {})

    def connect(self) -> None:
        result = self._call("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                           "clientInfo": CLIENT_INFO}, timeout=CONNECT_TIMEOUT)
        self.server_info = result.get("serverInfo") or {}
        self.instructions = str(result.get("instructions") or "")[:4000]
        if isinstance(self.transport, HttpTransport):
            self.transport.protocol = result.get("protocolVersion") or PROTOCOL_VERSION
        self.transport.send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def list_tools(self) -> list[dict]:
        tools, cursor = [], None
        for _ in range(50):  # pages
            result = self._call("tools/list", {"cursor": cursor} if cursor else {}, timeout=CONNECT_TIMEOUT)
            tools += result.get("tools") or []
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    def call_tool(self, name: str, arguments: dict) -> str:
        result = self._call("tools/call", {"name": name, "arguments": arguments or {}})
        return format_result(result)

    def close(self) -> None:
        self.transport.close()


def format_result(result: dict) -> str:
    """Turn a tools/call result into text for the model."""
    parts = []
    for item in result.get("content") or []:
        kind = item.get("type")
        if kind == "text":
            parts.append(item.get("text", ""))
        elif kind == "resource":
            res = item.get("resource") or {}
            parts.append(res.get("text") or f"[resource {res.get('uri', '')}]")
        elif kind == "resource_link":
            parts.append(f"[link: {item.get('name') or ''} {item.get('uri', '')}]")
        elif kind in ("image", "audio"):
            parts.append(f"[{kind} returned ({item.get('mimeType', '')}); not shown]")
    if not parts and result.get("structuredContent") is not None:
        parts.append(json.dumps(result["structuredContent"], ensure_ascii=False, indent=1))
    text = "\n".join(p for p in parts if p) or "(the connector returned nothing)"
    return f"ERROR: {text}" if result.get("isError") else text
