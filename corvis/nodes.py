"""The hub side of PC nodes.

A node is a computer (your PC) running `python -m corvis node`. It connects OUT to the hub,
so nothing on the PC is opened to the internet:

  1. hello   - "I'm Kody's PC, here are the tools I offer" (file, app and install tools)
  2. poll    - waits for work (long-poll, ~25 s at a time)
  3. result  - sends back what a tool returned
  4. ask     - while a tool runs, asks the owner for approval through the hub's chat

Nodes authenticate with a pairing token (stored here only as a hash). The node's own
guardrails still apply on the PC: the hub can only ask, never bypass them.
"""
from __future__ import annotations

import hashlib
import json
import os
import queue
import secrets
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

ONLINE_GRACE = 45        # seconds since the last poll before a node counts as offline
JOB_TIMEOUT = 900        # a single tool call (including waiting for approval) can take this long


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Job:
    id: str
    node_id: str
    kind: str                 # "tool" or "rpc"
    name: str
    args: dict
    approver: Callable[[str], bool] | None = None
    done: threading.Event = field(default_factory=threading.Event)
    output: object = None


@dataclass
class NodeState:
    id: str
    name: str
    tools: list[dict] = field(default_factory=list)
    info: dict = field(default_factory=dict)
    last_seen: float = 0.0
    jobs: "queue.Queue[Job]" = field(default_factory=queue.Queue)


class NodeHub:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "nodes.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.nodes: dict[str, NodeState] = {}
        self.jobs: dict[str, Job] = {}

    # --- pairing ----------------------------------------------------------------------
    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {"nodes": {}}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def pair(self, name: str) -> tuple[str, str]:
        """Create a node login. Returns (node_id, token). The token is shown once."""
        token = "cvn_" + secrets.token_urlsafe(32)
        node_id = uuid.uuid4().hex[:10]
        with self._lock:
            data = self._read()
            data["nodes"][node_id] = {"name": name[:60] or "PC", "token": _hash(token), "created": time.time()}
            self._write(data)
        return node_id, token

    def authenticate(self, token: str | None) -> str | None:
        if not token:
            return None
        h = _hash(token)
        for node_id, n in self._read().get("nodes", {}).items():
            if secrets.compare_digest(n["token"], h):
                return node_id
        return None

    def unpair(self, node_id: str) -> bool:
        with self._lock:
            data = self._read()
            removed = data["nodes"].pop(node_id, None)
            self._write(data)
            self.nodes.pop(node_id, None)
        return removed is not None

    def paired(self) -> list[dict]:
        out = []
        for node_id, n in self._read().get("nodes", {}).items():
            st = self.nodes.get(node_id)
            out.append({"id": node_id, "name": (st.name if st else n["name"]),
                        "online": self.is_online(node_id),
                        "last_seen": st.last_seen if st else n.get("last_seen")})
        return out

    # --- connection -------------------------------------------------------------------
    def hello(self, node_id: str, name: str, tools: list[dict], info: dict) -> None:
        with self._lock:
            st = self.nodes.get(node_id) or NodeState(node_id, name)
            st.name, st.tools, st.info, st.last_seen = name[:60] or st.name, tools, info, time.time()
            self.nodes[node_id] = st
            data = self._read()  # remember the PC's own name and when it was last here
            if node_id in data["nodes"]:
                data["nodes"][node_id].update(name=st.name, last_seen=st.last_seen)
                self._write(data)

    def is_online(self, node_id: str) -> bool:
        st = self.nodes.get(node_id)
        return bool(st) and time.time() - st.last_seen < ONLINE_GRACE

    def online(self) -> list[NodeState]:
        return [st for st in self.nodes.values() if self.is_online(st.id)]

    def poll(self, node_id: str, wait: float = 25.0) -> Job | None:
        st = self.nodes.get(node_id)
        if st is None:
            return None
        st.last_seen = time.time()
        try:
            job = st.jobs.get(timeout=wait)
        except queue.Empty:
            st.last_seen = time.time()
            return None
        st.last_seen = time.time()
        return job

    def result(self, node_id: str, job_id: str, output: object) -> bool:
        job = self.jobs.get(job_id)
        if not job or job.node_id != node_id:
            return False
        job.output = output
        job.done.set()
        return True

    def ask(self, node_id: str, job_id: str, prompt: str) -> bool:
        """The node needs the owner's OK in the middle of a tool call."""
        job = self.jobs.get(job_id)
        if not job or job.node_id != node_id:
            return False
        if job.approver is None:
            return False
        return bool(job.approver(f"On your PC ({self.nodes[node_id].name}): {prompt}"))

    # --- calling a node ---------------------------------------------------------------
    def call(self, node_id: str, kind: str, name: str, args: dict,
             approver: Callable[[str], bool] | None = None, timeout: float = JOB_TIMEOUT) -> object:
        st = self.nodes.get(node_id)
        if st is None or not self.is_online(node_id):
            raise ConnectionError("The PC is offline. Turn it on and start Corvis Node.")
        job = Job(uuid.uuid4().hex[:12], node_id, kind, name, args, approver)
        self.jobs[job.id] = job
        st.jobs.put(job)
        try:
            deadline = time.monotonic() + timeout
            while not job.done.wait(1.0):
                if time.monotonic() > deadline:
                    raise TimeoutError(f"The PC didn't finish {name} in time.")
                if not self.is_online(node_id):
                    raise ConnectionError("The PC went offline while working on it.")
            return job.output
        finally:
            self.jobs.pop(job.id, None)

    # --- what the agent sees -----------------------------------------------------------
    def status_line(self) -> str:
        paired = self.paired()
        if not paired:
            return ("\nThe owner's PC: not linked yet. PC files, apps and games aren't available; "
                    "if the owner asks, tell them to run Link_PC_To_Hub.bat on their PC.\n")
        live = [n["name"] for n in paired if n["online"]]
        if live:
            return (f"\nThe owner's PC ({', '.join(live)}) is online: the pc_* and app tools act on it.\n")
        return ("\nThe owner's PC is OFFLINE right now: you can't touch its files, apps or games. "
                "Say so if asked, and offer to do it when the PC is on. Everything else works.\n")
