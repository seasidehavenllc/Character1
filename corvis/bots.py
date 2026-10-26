"""Bots: AI teammates with their own job.

Corvis is the lead bot. The owner can add more ("Sales Outbound", "Bug Reproduction",
"Chief of Staff"...), each with:
- a job: plain-language instructions for what it does and how
- abilities: which groups of tools it may use (code, web, the owner's PC, its computer)
- its own memory: what it learns doing its job (plus what every bot knows about the owner)

Bots can hand work to each other (ask_bot), share a chat thread (@Name), and run routines
on a schedule. Stored in data/bots.json.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

LEAD_ID = "corvis"
COLORS = ["#4fb3a9", "#e8a33d", "#7c6cf0", "#e5534b", "#3d8be8", "#c35bd6", "#58a55c", "#d9774a"]

# Ability groups. Tools not listed in any group (planning, memory, files the owner sent,
# talking to other bots) are always available.
ABILITIES = {
    "code": "Write and run code in its project folder (files, search, terminal, Git)",
    "web": "Search the internet and read pages",
    "computer": "Use its own computer: a web browser that stays signed in to your tools",
    "pc": "Your PC's files, apps and games (when your PC is on)",
    "connectors": "Connectors you've added (GitHub, Slack, your own apps...)",
}
CODE_TOOLS = {"read_file", "write_file", "edit_file", "list_dir", "delete_file", "find_files", "grep",
              "run_command", "git_status", "git_diff", "git_log", "git_commit", "save_attachment"}
WEB_TOOLS = {"web_search", "fetch_page", "learn_topic"}
APP_TOOLS = {"find_app", "open_app", "close_app", "list_open_apps", "open_path", "open_url",
             "search_installable", "install_app", "download_file"}


def ability_of(tool_name: str) -> str | None:
    if tool_name.startswith("mcp_"):
        return "connectors"
    if tool_name.startswith("browser_"):
        return "computer"
    if tool_name.startswith("pc_") or tool_name in APP_TOOLS:
        return "pc"
    if tool_name in WEB_TOOLS:
        return "web"
    if tool_name in CODE_TOOLS:
        return "code"
    return None


def tool_filter(bot: dict):
    allowed = set(bot.get("abilities") or [])
    return lambda name: (ability_of(name) is None) or (ability_of(name) in allowed)


class BotStore:
    def __init__(self, data_dir: str | Path, lead_name: str = "Corvis"):
        self.path = Path(data_dir) / "bots.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.lead_name = lead_name
        self._lock = threading.Lock()

    def lead(self) -> dict:
        saved = self._read().get(LEAD_ID, {})
        return {"id": LEAD_ID, "name": self.lead_name, "lead": True,
                "job": saved.get("job", ""), "color": saved.get("color", "#6f8cff"),
                "abilities": list(ABILITIES), "created": 0}

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}

    def _write(self, data: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self) -> list[dict]:
        others = [b for k, b in self._read().items() if k != LEAD_ID]
        return [self.lead()] + sorted(others, key=lambda b: b.get("created", 0))

    def get(self, bot_id: str | None) -> dict:
        if not bot_id or bot_id == LEAD_ID:
            return self.lead()
        bot = self._read().get(bot_id)
        if bot is None:
            raise KeyError(bot_id)
        return bot

    def find(self, name: str) -> dict | None:
        want = name.strip().lstrip("@").lower()
        for b in self.list():
            if b["name"].lower() == want or b["id"] == want:
                return b
        return None

    @staticmethod
    def _clean(data: dict, existing: dict | None = None) -> dict:
        out = dict(existing or {})
        if "name" in data:
            name = " ".join(str(data["name"]).split())[:40]
            if not name:
                raise ValueError("Give the bot a name.")
            if "@" in name:
                raise ValueError("Bot names can't contain @.")
            out["name"] = name
        if "job" in data:
            out["job"] = str(data["job"]).strip()[:4000]
        if "color" in data:
            c = str(data["color"])
            if not re.fullmatch(r"#[0-9a-fA-F]{6}", c):
                raise ValueError("Color must look like #4fb3a9.")
            out["color"] = c
        if "abilities" in data:
            out["abilities"] = [a for a in data["abilities"] if a in ABILITIES]
        return out

    def create(self, data: dict) -> dict:
        with self._lock:
            all_ = self._read()
            bot = self._clean({"job": "", "abilities": ["web"], **data})
            if "name" not in bot:
                raise ValueError("Give the bot a name.")
            if any(b["name"].lower() == bot["name"].lower() for b in self.list()):
                raise ValueError(f"There's already a bot called {bot['name']}.")
            used = {b.get("color") for b in all_.values()}
            bot.setdefault("color", next((c for c in COLORS if c not in used), COLORS[len(all_) % len(COLORS)]))
            bot.update(id=uuid.uuid4().hex[:8], created=time.time(), lead=False)
            all_[bot["id"]] = bot
            self._write(all_)
            return bot

    def update(self, bot_id: str, data: dict) -> dict:
        with self._lock:
            all_ = self._read()
            if bot_id == LEAD_ID:  # the lead keeps its name (config.yaml) and every ability
                saved = self._clean({k: v for k, v in data.items() if k in ("job", "color")},
                                    all_.get(LEAD_ID, {}))
                all_[LEAD_ID] = saved
                self._write(all_)
                return self.lead()
            if bot_id not in all_:
                raise KeyError(bot_id)
            if "name" in data and any(b["name"].lower() == str(data["name"]).strip().lower()
                                      and b["id"] != bot_id for b in self.list()):
                raise ValueError(f"There's already a bot called {data['name']}.")
            all_[bot_id] = self._clean(data, all_[bot_id])
            self._write(all_)
            return all_[bot_id]

    def delete(self, bot_id: str) -> bool:
        if bot_id == LEAD_ID:
            raise ValueError("The lead bot can't be deleted.")
        with self._lock:
            all_ = self._read()
            gone = all_.pop(bot_id, None)
            self._write(all_)
        return gone is not None

    def mentioned(self, text: str) -> dict | None:
        """The bot a message is addressed to with @Name (longest name wins), if any."""
        low = text.lower()
        best = None
        for b in self.list():
            tag = "@" + b["name"].lower()
            i = low.find(tag)
            if i >= 0 and (i == 0 or not low[i - 1].isalnum()):
                end = i + len(tag)
                if end == len(low) or not low[end].isalnum():
                    if best is None or len(b["name"]) > len(best["name"]):
                        best = b
        return best
