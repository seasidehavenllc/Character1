"""Long-term memory for Corvis, stored in a local SQLite database with full-text search."""

from __future__ import annotations

import sqlite3
import time
from dataclasses import dataclass
from pathlib import Path

DEFAULT_DB = Path(__file__).resolve().parent.parent / "data" / "memory.db"


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
        self.db = sqlite3.connect(str(path))
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
            CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content, category)
                VALUES (new.id, new.content, new.category);
            END;
            CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content, category)
                VALUES ('delete', old.id, old.content, old.category);
            END;
            """
        )

    def add(self, content: str, category: str = "general", importance: int = 3) -> int:
        importance = max(1, min(5, int(importance)))
        cur = self.db.execute(
            "INSERT INTO memories (content, category, importance, created_at) VALUES (?, ?, ?, ?)",
            (content, category, importance, time.time()),
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
            WHERE memories_fts MATCH ?
            ORDER BY bm25(memories_fts) - m.importance * 0.5
            LIMIT ?
            """,
            (fts_query, limit),
        ).fetchall()
        return [Memory(*r) for r in rows]

    def top(self, limit: int = 15) -> list[Memory]:
        rows = self.db.execute(
            "SELECT id, content, category, importance, created_at FROM memories "
            "ORDER BY importance DESC, created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [Memory(*r) for r in rows]

    def forget(self, memory_id: int) -> bool:
        cur = self.db.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        self.db.commit()
        return cur.rowcount > 0

    @staticmethod
    def format(memories: list[Memory]) -> str:
        return "\n".join(f"- [#{m.id} {m.category}] {m.content}" for m in memories)
