"""One brain per data folder: the repository, knowledge base, learning jobs and continuity, wired
together, plus the daily upkeep (health scores, re-verifying files that are due)."""
from __future__ import annotations

import datetime as dt
import json
import threading
import time
from pathlib import Path
from typing import Callable

from .continuity import Continuity
from .kb import KnowledgeBase
from .learner import JobManager, Learner
from .repo import BrainRepo

DEFAULTS = {
    "enabled": True,
    "path": "",                       # default: <data>/brain
    "remote": "",                     # e.g. https://github.com/you/corvis-brain.git (private)
    "auto_push": True,
    "auto_approve_confidence": 90,    # updates at or above this apply without review (0 = always ask)
    "review_after_days": 90,
    "auto_maintain": True,
    "maintain_hour": 3,               # local hour for the daily health check and re-verification
    "verify_per_run": 10,
    "summarize_conversations": True,
    "request_delay": 1.5,             # seconds between web requests: search engines throttle bursts
}


def brain_cfg(cfg: dict) -> dict:
    return {**DEFAULTS, **(cfg.get("brain") or {})}


class BrainService:
    def __init__(self, cfg: dict, data_dir: str | Path, conversations=None,
                 llm_factory: Callable[[], object] | None = None, search=None, fetch=None, log=print):
        self.cfg = cfg
        self.bc = brain_cfg(cfg)
        self.data_dir = Path(data_dir)
        self.root = Path(self.bc["path"]).expanduser() if self.bc["path"] else self.data_dir / "brain"
        self.log = log
        self._settings_path = self.root / ".corvis" / "settings.json"
        saved = self._settings()
        self.repo = BrainRepo(self.root, self.data_dir / "secrets", remote=saved.get("remote", self.bc["remote"]),
                              auto_push=saved.get("auto_push", self.bc["auto_push"]), log=log)
        self.auto_threshold = int(saved.get("auto_approve_confidence", self.bc["auto_approve_confidence"]))
        self.kb = KnowledgeBase(self.root, int(self.bc["review_after_days"]), on_change=self._changed)
        self.llm_factory = llm_factory or self._default_llm
        self._search = search or self._default_search
        self._fetch = fetch or self._default_fetch
        self.jobs = JobManager(self.root, self.kb, self.make_learner, on_done=self._job_done)
        self.continuity = None
        if conversations is not None and self.bc["summarize_conversations"]:
            from ..config import agent_name
            self.continuity = Continuity(self.root, conversations, self.llm_factory, self.repo.commit,
                                         name=agent_name(cfg), personality=str(cfg.get("personality") or ""),
                                         jobs=self.jobs, kb=self.kb)
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.started = False

    # --- settings the owner changes from the app (kept out of config.yaml) -------------------
    def _settings(self) -> dict:
        try:
            return json.loads(self._settings_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def update_settings(self, changes: dict) -> dict:
        s = self._settings()
        if "remote" in changes:
            self.repo.set_remote(str(changes["remote"] or ""))
            s["remote"] = self.repo.remote
        if "auto_push" in changes:
            self.repo.auto_push = s["auto_push"] = bool(changes["auto_push"])
        if "auto_approve_confidence" in changes:
            v = int(changes["auto_approve_confidence"])
            if not 0 <= v <= 100:
                raise ValueError("The auto-approve threshold is a confidence from 0 to 100 (0 = always ask).")
            self.auto_threshold = s["auto_approve_confidence"] = v
        if changes.get("token") is not None:
            self.repo.set_token(str(changes["token"]))
        self._settings_path.parent.mkdir(parents=True, exist_ok=True)
        self._settings_path.write_text(json.dumps(s, indent=1), encoding="utf-8")
        return self.settings()

    def settings(self) -> dict:
        return {**self.repo.info(), "auto_approve_confidence": self.auto_threshold,
                "review_after_days": self.kb.review_after, "maintain_hour": self.bc["maintain_hour"],
                "auto_maintain": bool(self.bc["auto_maintain"])}

    # --- the parts -----------------------------------------------------------------------------
    def _default_llm(self):
        from ..config import make_llm
        return make_llm(self.cfg.get("llm", {}))

    def _default_search(self, query: str, n: int) -> list[dict]:
        from .. import internet
        return internet.search(query, self.cfg, n)

    def _default_fetch(self, url: str) -> str:
        from .. import internet
        from .learner import SOURCE_CHARS
        return internet.fetch(url, self.cfg, 0, SOURCE_CHARS)   # check_url refuses private addresses

    def make_learner(self, emit=print, should_stop=lambda: False) -> Learner:
        return Learner(self.kb, self.llm_factory(), self._search, self._fetch, emit=emit, should_stop=should_stop,
                       auto_threshold=self.auto_threshold, delay=float(self.bc["request_delay"]))

    def _changed(self, message: str) -> None:
        self.repo.commit(message)

    def _job_done(self, job: dict) -> None:
        self.kb.write_dashboard()
        self.repo.commit(f"Dashboard after {job['mode']} on {job['topic']}")

    def learn(self, topic: str, mode: str = "learn", by: str = "owner", budget: dict | None = None) -> dict:
        return self.jobs.start(topic, mode, budget=budget, by=by)

    # --- running ---------------------------------------------------------------------------------
    def start(self) -> None:
        if self.started:
            return
        self.started = True
        threading.Thread(target=self._startup, daemon=True, name="corvis-brain-start").start()
        if self.continuity:
            self.continuity.start()
        if self.bc["auto_maintain"]:
            self._thread = threading.Thread(target=self._maintain_loop, daemon=True, name="corvis-brain-upkeep")
            self._thread.start()

    def _startup(self) -> None:
        try:
            if self.repo.remote:
                self.repo.pull()
            if self.continuity:
                self.continuity.recover()
            self.kb.write_dashboard()
            self.repo.commit("Corvis started: dashboard refreshed")
        except Exception as e:   # the brain must never stop the app from starting
            self.log(f"Brain start-up: {type(e).__name__}: {e}")

    def stop(self) -> None:
        self._stop.set()
        if self.continuity:
            self.continuity.stop()
        if self.repo.remote and self.repo.auto_push and self.repo.status.get("last_commit") and (
                (self.repo.status.get("last_push") or 0) < self.repo.status["last_commit"]):
            self.repo.push()

    def _maintain_loop(self) -> None:
        while not self._stop.wait(600):
            now = dt.datetime.now()
            if now.hour >= int(self.bc["maintain_hour"]) and self._last_maintained() != now.date().isoformat():
                try:
                    self.maintain()
                except Exception as e:
                    self.log(f"Brain upkeep: {type(e).__name__}: {e}")

    def _last_maintained(self) -> str:
        try:
            return json.loads((self.root / ".corvis/maintenance.json").read_text(encoding="utf-8")).get("date", "")
        except (OSError, json.JSONDecodeError):
            return ""

    def maintain(self) -> dict:
        """The daily review cycle: refresh scores, flag stale files, queue re-verification."""
        changed = self.kb.refresh_scores()
        self.kb.write_dashboard()
        due = self.kb.due_for_review()
        job = None
        from ..internet import internet_cfg
        if due and internet_cfg(self.cfg)["enabled"]:
            job = self.jobs.start("knowledge upkeep", "verify", ids=[d["id"] for d in due[: int(self.bc["verify_per_run"])]],
                                  by="schedule")
        self.repo.commit("Daily health check")
        out = {"date": dt.date.today().isoformat(), "rescored": changed, "due": len(due), "job": job["id"] if job else None,
               "ts": time.time()}
        (self.root / ".corvis").mkdir(exist_ok=True)
        (self.root / ".corvis/maintenance.json").write_text(json.dumps(out), encoding="utf-8")
        return out


_shared: dict[str, BrainService] = {}
_lock = threading.Lock()


def shared(cfg: dict, data_dir: str | Path, conversations=None, **kwargs) -> BrainService | None:
    """The brain for this data folder (one per process), or None when it's turned off."""
    if not brain_cfg(cfg)["enabled"]:
        return None
    key = str(Path(data_dir).resolve())
    with _lock:
        if key not in _shared:
            _shared[key] = BrainService(cfg, data_dir, conversations, **kwargs)
        return _shared[key]
