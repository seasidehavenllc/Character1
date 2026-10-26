"""Saved conversations (the chat history list in the app)."""

from __future__ import annotations

import json
import sqlite3
import time
import uuid
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "conversations.db"


class ConversationStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The web app calls in from worker threads; it serializes access with its own lock.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS conversations (
                id TEXT PRIMARY KEY, title TEXT NOT NULL, pinned INTEGER NOT NULL DEFAULT 0,
                created_at REAL NOT NULL, updated_at REAL NOT NULL);
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY, conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                role TEXT NOT NULL, text TEXT NOT NULL, model_text TEXT, attachments TEXT, model TEXT,
                created_at REAL NOT NULL);
            CREATE INDEX IF NOT EXISTS messages_conv ON messages(conversation_id, id);
            """
        )
        self.db.execute("PRAGMA foreign_keys = ON")

    def create(self, title: str) -> str:
        cid = uuid.uuid4().hex
        now = time.time()
        self.db.execute("INSERT INTO conversations VALUES (?, ?, 0, ?, ?)", (cid, title, now, now))
        self.db.commit()
        return cid

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT id, title, pinned, updated_at FROM conversations ORDER BY pinned DESC, updated_at DESC"
        ).fetchall()
        return [{"id": r[0], "title": r[1], "pinned": bool(r[2]), "updated_at": r[3]} for r in rows]

    def exists(self, cid: str) -> bool:
        return self.db.execute("SELECT 1 FROM conversations WHERE id = ?", (cid,)).fetchone() is not None

    def messages(self, cid: str) -> list[dict[str, Any]]:
        rows = self.db.execute(
            "SELECT role, text, model_text, attachments, model FROM messages WHERE conversation_id = ? ORDER BY id",
            (cid,),
        ).fetchall()
        return [{"role": r[0], "text": r[1], "model_text": r[2] or r[1],
                 "attachments": json.loads(r[3] or "[]"), "model": r[4]} for r in rows]

    def add_message(self, cid: str, role: str, text: str, model_text: str | None = None,
                    attachments: list[dict[str, Any]] | None = None, model: str | None = None) -> None:
        now = time.time()
        self.db.execute(
            "INSERT INTO messages (conversation_id, role, text, model_text, attachments, model, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (cid, role, text, model_text, json.dumps(attachments or []), model, now),
        )
        self.db.execute("UPDATE conversations SET updated_at = ? WHERE id = ?", (now, cid))
        self.db.commit()

    def rename(self, cid: str, title: str) -> None:
        self.db.execute("UPDATE conversations SET title = ? WHERE id = ?", (title.strip()[:120] or "Untitled", cid))
        self.db.commit()

    def set_pinned(self, cid: str, pinned: bool) -> None:
        self.db.execute("UPDATE conversations SET pinned = ? WHERE id = ?", (int(pinned), cid))
        self.db.commit()

    def delete(self, cid: str) -> None:
        self.db.execute("DELETE FROM messages WHERE conversation_id = ?", (cid,))
        self.db.execute("DELETE FROM conversations WHERE id = ?", (cid,))
        self.db.commit()


def title_from(message: str) -> str:
    first = " ".join(message.split())
    return (first[:48].rsplit(" ", 1)[0] + "…") if len(first) > 50 else (first or "New chat")
