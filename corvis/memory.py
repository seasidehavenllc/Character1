"""Long-term memory for Corvis, stored in a local SQLite database with full-text search.

Each memory has a global `uuid` so it can sync between devices on the same account.
Deleting marks a memory as deleted (instead of removing the row) so the deletion syncs too.
"""

from __future__ import annotations

import sqlite3
import time
import uuid as uuidlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "memory.db"
SYNC_FIELDS = ("uuid", "content", "category", "importance", "created_at", "updated_at", "deleted")


@dataclass
class Memory:
    id: int
    content: str
    category: str
    importance: int
    created_at: float


class MemoryStore:
    def __init__(self, path: str | Path = DEFAULT_DB):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        # The web app calls in from worker threads; it serializes access with its own lock.
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.executescript(
            """
            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY,
                content TEXT NOT NULL,
                category TEXT NOT NULL DEFAULT 'general',
                importance INTEGER NOT NULL DEFAULT 3,
                created_at REAL NOT NULL
            );
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
                USING fts5(content, category, content='memories', content_rowid='id');
            """
        )
        self._migrate()

    def _migrate(self) -> None:
        cols = {r[1] for r in self.db.execute("PRAGMA table_info(memories)")}
        for name, ddl in [("uuid", "TEXT"), ("updated_at", "REAL"), ("deleted", "INTEGER NOT NULL DEFAULT 0"),
                          ("dirty", "INTEGER NOT NULL DEFAULT 1")]:
            if name not in cols:
                self.db.execute(f"ALTER TABLE memories ADD COLUMN {name} {ddl}")
        self.db.execute("UPDATE memories SET uuid = lower(hex(randomblob(16))) WHERE uuid IS NULL")
        self.db.execute("UPDATE memories SET updated_at = created_at WHERE updated_at IS NULL")
        # Only live (non-deleted) memories are in the search index.
        self.db.executescript(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS memories_uuid ON memories(uuid);
            DROP TRIGGER IF EXISTS memories_ai;
            DROP TRIGGER IF EXISTS memories_ad;
            DROP TRIGGER IF EXISTS memories_au_old;
            DROP TRIGGER IF EXISTS memories_au_new;
            CREATE TRIGGER memories_ai AFTER INSERT ON memories WHEN new.deleted = 0 BEGIN
                INSERT INTO memories_fts(rowid, content, category) VALUES (new.id, new.content, new.category);
            END;
            CREATE TRIGGER memories_ad AFTER DELETE ON memories WHEN old.deleted = 0 BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
            END;
            CREATE TRIGGER memories_au_old AFTER UPDATE ON memories WHEN old.deleted = 0 BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
            END;
            CREATE TRIGGER memories_au_new AFTER UPDATE ON memories WHEN new.deleted = 0 BEGIN
                INSERT INTO memories_fts(rowid, content, category) VALUES (new.id, new.content, new.category);
            END;
            """
        )
        self.db.commit()

    def add(self, content: str, category: str = "general", importance: int = 3) -> int:
        importance = max(1, min(5, int(importance)))
        now = time.time()
        cur = self.db.execute(
            "INSERT INTO memories (uuid, content, category, importance, created_at, updated_at, deleted, dirty) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 1)",
            (uuidlib.uuid4().hex, content, category, importance, now, now),
        )
        self.db.commit()
        return cur.lastrowid

    def search(self, query: str, limit: int = 8) -> list[Memory]:
        # Quote each word so user text can't break FTS5 query syntax; OR them for recall.
        terms = [w.replace('"', "") for w in query.split() if w.strip('"')]
        if not terms:
            return []
        fts_query = " OR ".join(f'"{t}"' for t in terms)
        rows = self.db.execute(
            """
            SELECT m.id, m.content, m.category, m.importance, m.created_at
            FROM memories_fts JOIN memories m ON m.id = memories_fts.rowid
            WHERE memories_fts MATCH ? AND m.deleted = 0
            ORDER BY bm25(memories_fts) - m.importance * 0.5
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        return [Memory(*r) for r in rows]

    def top(self, limit: int = 15) -> list[Memory]:
        rows = self.db.execute(
            "SELECT id, content, category, importance, created_at FROM memories WHERE deleted = 0 "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Memory(*r) for r in rows]

    def forget(self, memory_id: int) -> bool:
        cur = self.db.execute(
            "UPDATE memories SET deleted = 1, dirty = 1, updated_at = ? WHERE id = ? AND deleted = 0",
            (time.time(), memory_id),
        )
        self.db.commit()
        return cur.rowcount > 0

    # --- sync ------------------------------------------------------------------------

    def pending_changes(self) -> list[dict[str, Any]]:
        rows = self.db.execute(f"SELECT {', '.join(SYNC_FIELDS)} FROM memories WHERE dirty = 1").fetchall()
        return [dict(zip(SYNC_FIELDS, r)) for r in rows]

    def mark_synced(self, uuids: list[str]) -> None:
        self.db.executemany("UPDATE memories SET dirty = 0 WHERE uuid = ?", [(u,) for u in uuids])
        self.db.commit()

    def apply_remote(self, changes: list[dict[str, Any]]) -> int:
        """Merge changes from another device. Newest edit wins. Returns how many were applied."""
        applied = 0
        for c in changes:
            row = self.db.execute("SELECT updated_at FROM memories WHERE uuid = ?", (c["uuid"],)).fetchone()
            if row is None:
                self.db.execute(
                    "INSERT INTO memories (uuid, content, category, importance, created_at, updated_at, deleted, dirty) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
                    tuple(c[f] for f in SYNC_FIELDS),
                )
                applied += 1
            elif c["updated_at"] > row[0]:
                self.db.execute(
                    "UPDATE memories SET content = ?, category = ?, importance = ?, updated_at = ?, deleted = ?, "
                    "dirty = 0 WHERE uuid = ?",
                    (c["content"], c["category"], c["importance"], c["updated_at"], c["deleted"], c["uuid"]),
                )
                applied += 1
        self.db.commit()
        return applied

    @staticmethod
    def format(memories: list[Memory]) -> str:
        return "\n".join(f"- [#{m.id} {m.category}] {m.content}" for m in memories)
