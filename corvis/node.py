"""Corvis Node: runs on the owner's PC and lends the hub its hands.

python -m corvis node

The node connects OUT to the hub (over Tailscale), says which tools it offers, then waits
for work. It runs PC file, app and install tools right here, with all of this PC's
guardrails. When a tool needs the owner's OK, the node asks the hub, which shows the
Allow/Deny card in the chat.
"""
from __future__ import annotations

import base64
import platform
import time
from pathlib import Path

import requests

from . import __version__, pc
from .config import CORVIS_HOME, data_dir
from .safety import CommandPolicy, Workspace
from .tools import app_tools, pc_tools
from .tools.base import ToolContext, ToolRegistry

MAX_FILE_BYTES = 15 * 1024 * 1024


def token_path(cfg: dict) -> Path:
    # The pairing token is a secret: it lives in data/ (never in config.yaml or Git).
    return data_dir(cfg) / "node_token"


def node_cfg(cfg: dict) -> dict:
    n = cfg.get("node", {}) or {}
    try:
        token = token_path(cfg).read_text(encoding="utf-8").strip()
    except OSError:
        token = ""
    return {"hub_url": str(n.get("hub_url") or "").rstrip("/"), "token": token,
            "name": str(n.get("name") or platform.node() or "My PC")}


class Node:
    def __init__(self, cfg: dict, session: requests.Session | None = None, log=print):
        self.cfg = cfg
        self.n = node_cfg(cfg)
        self.http = session or requests.Session()
        self.http.headers.update({"Authorization": f"Bearer {self.n['token']}", "X-Corvis": "1"})
        self.log = log
        self.current_job: str | None = None
        self.policy = pc.PCPolicy(cfg, CORVIS_HOME, data_dir(cfg))
        project = Path((cfg.get("web") or {}).get("default_workspace", "~/CorvisProjects")).expanduser()
        project.mkdir(parents=True, exist_ok=True)
        ctx = ToolContext(workspace=Workspace(project), policy=CommandPolicy(approver=self.ask),
                          approver=self.ask, config=cfg)
        ctx.state.update(pc_policy=self.policy, data_dir=str(data_dir(cfg)))
        self.registry = ToolRegistry(ctx)
        pc_tools.register(self.registry, ctx)
        app_tools.register(self.registry, ctx)

    # --- talking to the hub -------------------------------------------------------------
    def url(self, path: str) -> str:
        return f"{self.n['hub_url']}{path}"

    def hello(self) -> None:
        info = {"os": f"{platform.system()} {platform.release()}", "version": __version__}
        r = self.http.post(self.url("/api/node/hello"), json={
            "name": self.n["name"], "tools": self.registry.schemas(), "info": info}, timeout=20)
        if r.status_code == 401:
            raise PermissionError(r.json().get("error", "The hub doesn't recognise this PC. Link it again."))
        r.raise_for_status()

    def ask(self, prompt: str) -> bool:
        """A tool needs the owner's OK: ask through the hub (shows up in the chat)."""
        if not self.current_job:
            return False
        try:
            r = self.http.post(self.url("/api/node/ask"), json={"job_id": self.current_job, "prompt": prompt},
                               timeout=900)
            return bool(r.ok and r.json().get("allow"))
        except requests.RequestException:
            return False

    # --- doing the work -------------------------------------------------------------------
    def rpc(self, name: str, args: dict) -> dict:
        """Structured requests for the hub's Files browser."""
        path = str(args.get("path", ""))
        try:
            if name == "list":
                return pc.list_dir(self.policy, path)
            p = self.policy.check(path, "read")
            if not p.is_file():
                return {"error": "That file doesn't exist."}
            info = {"name": p.name, "path": str(p), "size": p.stat().st_size, "modified": p.stat().st_mtime}
            if name == "preview":
                if p.suffix.lower() in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"):
                    return {**info, "kind": "image"}
                text = pc.read_text(p, 0, 200_000)
                if " has no text to read." in text.splitlines()[0]:
                    return {**info, "kind": "other", "note": text}
                cut = text.find("\n\n")
                return {**info, "kind": "text", "text": text[cut + 2:] if cut >= 0 else text}
            if name == "file":
                if info["size"] > MAX_FILE_BYTES:
                    return {"error": "That file is too big to send through the hub (over 15 MB)."}
                return {"name": p.name, "b64": base64.b64encode(p.read_bytes()).decode()}
            return {"error": f"Unknown request {name}."}
        except (PermissionError, NotADirectoryError, FileNotFoundError, ValueError, OSError) as e:
            return {"error": str(e)}

    def handle(self, job: dict) -> object:
        self.current_job = job["id"]
        try:
            if job["kind"] == "rpc":
                return self.rpc(job["name"], job.get("args") or {})
            self.log(f"  → {job['name']} {str(job.get('args'))[:100]}")
            return self.registry.run(job["name"], job.get("args") or {})
        finally:
            self.current_job = None

    def step(self) -> bool:
        """Wait for one job and do it. Returns True if there was a job."""
        r = self.http.get(self.url("/api/node/poll"), timeout=40)
        if r.status_code == 401:
            raise PermissionError(r.json().get("error", "Unlinked."))
        r.raise_for_status()
        data = r.json()
        if data.get("hello"):
            return None  # type: ignore[return-value]
        job = data.get("job")
        if not job:
            return False
        output = self.handle(job)
        self.http.post(self.url("/api/node/result"), json={"job_id": job["id"], "output": output}, timeout=60)
        return True

    def run_forever(self) -> int:
        if not self.n["hub_url"] or not self.n["token"]:
            self.log("This PC isn't linked to a hub yet. Run Link_PC_To_Hub.bat first.")
            return 1
        delay = 2
        connected = False
        while True:
            try:
                if not connected:
                    self.hello()
                    connected, delay = True, 2
                    self.log(f"Connected to {self.n['hub_url']} as \"{self.n['name']}\". "
                             "Corvis can use this PC while this window is open.")
                if self.step() is None:  # the hub restarted and forgot us: introduce ourselves again
                    connected = False
            except PermissionError as e:
                self.log(f"Stopped: {e}")
                return 1
            except requests.RequestException as e:
                if connected:
                    self.log(f"Lost the hub ({type(e).__name__}). Reconnecting...")
                connected = False
                time.sleep(delay)
                delay = min(delay * 2, 60)
            except KeyboardInterrupt:
                return 0


def link(cfg: dict, config_path: Path, hub_url: str, code: str, name: str = "") -> str:
    """Save the hub address and pairing code into this PC's config.yaml."""
    from .config_edit import replace_block
    hub_url = hub_url.strip().rstrip("/")
    if not hub_url.startswith(("https://", "http://")):
        hub_url = "https://" + hub_url
    r = requests.post(f"{hub_url}/api/node/hello", headers={"Authorization": f"Bearer {code.strip()}",
                                                         "X-Corvis": "1"},
                      json={"name": name or platform.node(), "tools": [], "info": {}}, timeout=20)
    if r.status_code == 401:
        raise PermissionError("The hub didn't accept that code. Check it, or make a new one on the hub.")
    r.raise_for_status()
    text = config_path.read_text(encoding="utf-8") if config_path.is_file() else ""
    if text:
        config_path.with_suffix(".yaml.bak").write_text(text, encoding="utf-8")
    block = ["node:", "  # This PC lends its files and apps to the Corvis hub (Start_Corvis_Node.bat).",
             f"  hub_url: {hub_url}", f"  name: \"{(name or platform.node())[:60].replace(chr(34), '')}\""]
    config_path.write_text(replace_block(text, "node", block), encoding="utf-8")
    tp = token_path(cfg)
    tp.parent.mkdir(parents=True, exist_ok=True)
    tp.write_text(code.strip(), encoding="utf-8")
    return hub_url
