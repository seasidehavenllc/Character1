"""Append-only task outcome journal; outcomes are not automatically treated as truth."""
from __future__ import annotations
import json, time, uuid
from pathlib import Path
from threading import RLock

class ExperienceStore:
    def __init__(self, data_dir):
        self.path = Path(data_dir) / "experiences.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True); self._lock = RLock()
        self.path.touch(exist_ok=True)

    def record(self, goal: str, outcome: str, *, plan: str = "", actions: list[str] | None = None,
               verified: bool = False, lesson: str = "", source: str = "agent") -> dict:
        if not goal.strip(): raise ValueError("goal must not be empty")
        item = {"id": uuid.uuid4().hex, "at": time.time(), "goal": goal, "plan": plan,
                "actions": actions or [], "outcome": outcome, "verified": bool(verified),
                "lesson": lesson, "source": source}
        with self._lock:
            with self.path.open("a", encoding="utf-8") as f: f.write(json.dumps(item, ensure_ascii=False) + "\n")
        return item

    def recent(self, limit: int = 20, query: str = "") -> list[dict]:
        try: lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError: return []
        items = []
        for line in lines:
            try: items.append(json.loads(line))
            except json.JSONDecodeError: continue
        terms = query.lower().split()
        if terms:
            items = [x for x in items if any(t in json.dumps(x, ensure_ascii=False).lower() for t in terms)]
        return items[-max(1, limit):]
