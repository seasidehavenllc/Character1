"""Keeps Corvis running: python -m corvis serve

- Restarts him when he asks (exit code 3, e.g. after updating himself).
- If he crashes within the first 90 seconds after a self-update, the update is undone
  (git reset to the version before it) and he starts again on the last working code.
  He tells the owner what happened the next time they open the app.
- Any other crash: wait a moment, start again.
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

from .config import CORVIS_HOME, data_dir
from .tools.git_tools import git

RESTART = 3
SETTLE_SECONDS = 90


def marker(cfg: dict) -> Path:
    return data_dir(cfg) / "update_pending.json"


def notice_file(cfg: dict) -> Path:
    return data_dir(cfg) / "notice.json"


def record_update(cfg: dict, previous: str, branch: str) -> None:
    """Called by self-edit right after a merge: remember what to go back to."""
    m = marker(cfg)
    m.parent.mkdir(parents=True, exist_ok=True)
    m.write_text(json.dumps({"previous": previous, "branch": branch, "at": time.time()}), encoding="utf-8")


def rollback(cfg: dict, log=print) -> bool:
    m = marker(cfg)
    try:
        info = json.loads(m.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    code, out = git(CORVIS_HOME, "reset", "--hard", info["previous"])
    m.unlink(missing_ok=True)
    if code != 0:
        log(f"Couldn't roll back: {out}")
        return False
    notice_file(cfg).write_text(json.dumps({
        "text": "My last update stopped me from starting, so I undid it and I'm back on the previous "
                f"version. The change is still saved on branch {info.get('branch', '?')} if you want to "
                "look at it.", "at": time.time()}), encoding="utf-8")
    log(f"Rolled back the last self-update (back to {info['previous'][:8]}).")
    return True


def serve(cfg: dict, config_path: str | None = None, open_browser: bool = True,
          popen=subprocess.Popen, log=print, max_restarts: int | None = None) -> int:
    first, restarts = True, 0
    while True:
        cmd = [sys.executable, "-m", "corvis"] + (["--config", config_path] if config_path else []) + ["web"]
        if not (first and open_browser):
            cmd.append("--no-browser")
        first = False
        started = time.monotonic()
        proc = popen(cmd, cwd=str(CORVIS_HOME))
        try:
            while True:
                try:
                    code = proc.wait(timeout=5)
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() - started > SETTLE_SECONDS and marker(cfg).exists():
                        marker(cfg).unlink(missing_ok=True)  # the update survived: keep it
        except KeyboardInterrupt:
            proc.wait()
            return 0
        ran = time.monotonic() - started
        restarts += 1
        if max_restarts is not None and restarts > max_restarts:
            return code
        if code == 0:
            return 0
        if code == RESTART:
            log("Restarting Corvis...")
            continue
        if marker(cfg).exists() and ran < SETTLE_SECONDS:
            log("Corvis crashed right after updating himself.")
            if rollback(cfg, log):
                continue
        log(f"Corvis stopped unexpectedly (exit code {code}). Starting him again...")
        time.sleep(10 if ran < 15 else 2)
