"""Keeping the brain in Git, backed up to GitHub.

Every change Corvis makes (new knowledge, approved updates, reports, session summaries) is a
commit, so the whole history of what he knew and when is preserved. When a remote is set (a
private GitHub repository is ideal), commits are pushed a few seconds after the last change and
pulled back in on start, so edits made on GitHub land in Corvis's brain too.

The GitHub token never goes in config.yaml or Git: it's kept in data/secrets/ (only the owner can
read it) and handed to git for each push or pull only.
"""
from __future__ import annotations

import base64
import os
import re
import threading
import time
from pathlib import Path

from ..code_sessions import git

AUTHOR = ["-c", "user.name=Corvis", "-c", "user.email=corvis@localhost"]
PUSH_DELAY = 20
README = """# Corvis's second brain

This repository is maintained by Corvis. It holds what he has learned, how sure he is about it,
and the memory of your work together. Everything is plain markdown, so you can read and edit it
here; your edits are pulled back into Corvis.

- `Knowledge/Current/` — what Corvis knows, one file per topic, by category
- `Knowledge/PendingReview/` — proposed updates waiting for your approval
- `Knowledge/Archive/` — every replaced version, and why it changed
- `Reports/` — daily, weekly and monthly learning reports
- `Memory/SessionSummaries/` — a summary of each day you talked
- `Conversations/` — digests of important conversations, by topic
- `Projects/` — long-term project memory: status, goals, tasks, notes, ideas
- `Dashboard.md` — the health of the knowledge base right now
"""


class BrainRepo:
    def __init__(self, root: str | Path, secrets_dir: str | Path, remote: str = "", auto_push: bool = True, log=print):
        self.root = Path(root)
        self.secrets = Path(secrets_dir)
        self.remote = (remote or "").strip()
        self.auto_push = auto_push
        self.log = log
        self._lock = threading.Lock()
        self._push_timer: threading.Timer | None = None
        self.status = {"last_commit": None, "last_push": None, "last_pull": None, "error": None}
        self.init()

    # --- the token, kept out of config and Git ------------------------------------------
    @property
    def token_path(self) -> Path:
        return self.secrets / "brain_github_token"

    def set_token(self, token: str) -> None:
        self.secrets.mkdir(parents=True, exist_ok=True)
        token = token.strip()
        if not token:
            self.token_path.unlink(missing_ok=True)
            return
        if not re.fullmatch(r"[A-Za-z0-9_\-]{20,255}", token):
            raise ValueError("That doesn't look like a GitHub token.")
        self.token_path.write_text(token, encoding="utf-8")
        try:
            os.chmod(self.token_path, 0o600)
        except OSError:
            pass

    def has_token(self) -> bool:
        return self.token_path.is_file() and bool(self.token_path.read_text(encoding="utf-8").strip())

    def _auth(self) -> list[str]:
        if not self.has_token() or not self.remote.startswith("https://"):
            return []
        token = self.token_path.read_text(encoding="utf-8").strip()
        basic = base64.b64encode(f"x-access-token:{token}".encode()).decode()
        return ["-c", f"http.extraHeader=Authorization: Basic {basic}"]

    # --- the repository --------------------------------------------------------------------
    def init(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        if not (self.root / ".git").exists():
            code, out = git(self.root, "init", "-q", "-b", "main")
            if code != 0:
                self.status["error"] = f"Git isn't available, so the brain isn't versioned: {out}"
                return
        readme = self.root / "README.md"
        if not readme.exists():
            readme.write_text(README, encoding="utf-8")
        ignore = self.root / ".gitignore"
        if not ignore.exists():
            ignore.write_text(".corvis/\n*.tmp\n", encoding="utf-8")
        self.set_remote(self.remote)

    def set_remote(self, url: str) -> None:
        url = (url or "").strip()
        if url and not re.fullmatch(r"(https://[\w.-]+/[\w./-]+?(\.git)?|git@[\w.-]+:[\w./-]+?(\.git)?)", url):
            raise ValueError("Use a repository address like https://github.com/you/corvis-brain.git")
        self.remote = url
        if not (self.root / ".git").exists():
            return
        code, current = git(self.root, "remote", "get-url", "origin")
        if not url:
            if code == 0:
                git(self.root, "remote", "remove", "origin")
        elif code != 0:
            git(self.root, "remote", "add", "origin", url)
        elif current.strip() != url:
            git(self.root, "remote", "set-url", "origin", url)

    def commit(self, message: str) -> bool:
        if not (self.root / ".git").exists():
            return False
        with self._lock:
            git(self.root, "add", "-A")
            code, out = git(self.root, *AUTHOR, "commit", "-q", "-m", message[:200])
            if code != 0:
                return False   # nothing to commit
            self.status["last_commit"] = time.time()
        if self.remote and self.auto_push:
            self._schedule_push()
        return True

    def _schedule_push(self) -> None:
        if self._push_timer:
            self._push_timer.cancel()
        self._push_timer = threading.Timer(PUSH_DELAY, self.push)
        self._push_timer.daemon = True
        self._push_timer.start()

    def pull(self) -> str:
        if not self.remote:
            return "No GitHub repository set."
        with self._lock:
            code, out = git(self.root, *self._auth(), *AUTHOR, "pull", "--rebase", "--autostash", "-q", "origin", "main",
                            timeout=90)
        if code != 0 and "couldn't find remote ref" not in out.lower():
            self.status["error"] = f"Pull failed: {out[-300:]}"
            return self.status["error"]
        self.status["last_pull"], self.status["error"] = time.time(), None
        return "Pulled the latest from GitHub."

    def push(self) -> str:
        if not self.remote:
            return "No GitHub repository set."
        self.pull()
        with self._lock:
            code, out = git(self.root, *self._auth(), "push", "-q", "-u", "origin", "main", timeout=120)
        if code != 0:
            hint = " (add a GitHub token in Knowledge → Sync)" if "auth" in out.lower() or "403" in out or "401" in out else ""
            self.status["error"] = f"Push failed{hint}: {out[-300:]}"
            self.log(self.status["error"])
            return self.status["error"]
        self.status["last_push"], self.status["error"] = time.time(), None
        return "Pushed to GitHub."

    def info(self) -> dict:
        code, log = git(self.root, "log", "--oneline", "-n", "12") if (self.root / ".git").exists() else (1, "")
        code2, count = git(self.root, "rev-list", "--count", "HEAD") if (self.root / ".git").exists() else (1, "0")
        return {"path": str(self.root), "remote": self.remote, "has_token": self.has_token(), "auto_push": self.auto_push,
                "commits": int(count) if code2 == 0 and count.strip().isdigit() else 0,
                "recent": log.splitlines() if code == 0 else [], **self.status}
