"""Saved chats. Each conversation is one JSON file in data/conversations/.

A conversation keeps two histories:
- `messages`: what the chat screen shows (your messages, Corvis's replies, his work steps)
- `llm_history`: what the model saw (including tool calls), so a chat can pick up
  where it left off after Corvis restarts
"""
from __future__ import annotations

import json
import os
import threading
import time
import uuid
from pathlib import Path

TITLE_LIMIT = 48


def make_title(text: str) -> str:
    line = " ".join(text.strip().split())
    return line if len(line) <= TITLE_LIMIT else line[: TITLE_LIMIT - 1].rstrip() + "…"


class ConversationStore:
    def __init__(self, folder: str | Path):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, conv_id: str) -> Path:
        if not conv_id or not all(c.isalnum() or c == "-" for c in conv_id):
            raise KeyError(conv_id)
        return self.folder / f"{conv_id}.json"

    def create(self, workspace: str, mode: str = "project", bot: str = "corvis", project: str | None = None,
               kind: str = "chat") -> dict:
        now = time.time()
        conv = {
            "id": uuid.uuid4().hex[:12],
            "title": "New chat",
            "created": now,
            "updated": now,
            "workspace": workspace,
            "mode": mode,  # "project" or "self"
            "bot": bot,    # the bot this chat is with (others can join with @Name)
            "project": project,  # the project this chat (thread) belongs to, if any
            "kind": kind,  # "chat", or "code" for a code session (see web/code_sessions.py)
            "messages": [],
            "llm_history": [],
        }
        self.save(conv)
        return conv

    def get(self, conv_id: str) -> dict:
        path = self._path(conv_id)
        if not path.is_file():
            raise KeyError(conv_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def save(self, conv: dict) -> None:
        conv["updated"] = time.time()
        path = self._path(conv["id"])
        tmp = path.with_suffix(".tmp")
        with self._lock:
            tmp.write_text(json.dumps(conv, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, path)  # atomic: a crash never leaves half a file

    def delete(self, conv_id: str) -> None:
        path = self._path(conv_id)
        if path.is_file():
            path.unlink()

    def list(self) -> list[dict]:
        out = []
        for path in self.folder.glob("*.json"):
            try:
                c = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            item = {k: c[k] for k in ("id", "title", "updated", "workspace", "mode")}
            item.update(bot=c.get("bot", "corvis"), unread=bool(c.get("unread")), routine=c.get("routine"),
                        project=c.get("project"), kind=c.get("kind", "chat"), code=c.get("code"),
                        messages=len(c.get("messages", [])))
            out.append(item)
        return sorted(out, key=lambda c: c["updated"], reverse=True)
