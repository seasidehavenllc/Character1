"""The shape library: every shape Corvis has met, ready to reuse in any blueprint.

When a model is imported (from a file the owner gives him, or one he finds online), each of
its components is filed here with its name, where it came from and its licence. Parts the
owner or Corvis like can be saved by hand too. Corvis searches the library before designing
from scratch ("a wheel", "spoiler", "lattice beam") and drops shapes straight into a blueprint.

Stored in data/shapes/library.json; mesh shapes point at the model files in
data/blueprints/assets/ (shared, never copied).
"""
from __future__ import annotations

import copy
import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

from .blueprints import clean_part

MAX_SHAPES = 5000
TEMPLATE_KEYS = ("shape", "size", "rotation", "material", "infill", "profile", "mesh", "color", "power_w", "battery_wh")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 1]


class ShapeLibrary:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "shapes" / "library.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def list(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, items: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(items[-MAX_SHAPES:], ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.path)

    def get(self, sid: str) -> dict:
        for s in self.list():
            if s["id"] == sid:
                return s
        raise KeyError(f"No shape '{sid}' in the library.")

    def add(self, part: dict, name: str = "", tags: list[str] | str | None = None, source: dict | None = None,
            learned_from: str = "") -> dict:
        """File a part's shape (not its position) in the library."""
        part = clean_part(part)
        if isinstance(tags, str):
            tags = [t for t in re.split(r"[,;]\s*|\s+", tags) if t]
        entry = {"id": uuid.uuid4().hex[:10], "name": (" ".join(str(name or part["name"]).split()) or "Shape")[:60],
                 "tags": sorted({t.lower()[:24] for t in (tags or []) if t})[:12],
                 "part": {k: copy.deepcopy(part[k]) for k in TEMPLATE_KEYS if k in part},
                 "source": source or {}, "learned_from": learned_from[:80], "added": time.time(), "uses": 0}
        with self._lock:
            items = self.list()
            key = (entry["part"].get("mesh") or {}).get("id")
            for old in items:   # the same model piece is only filed once
                if key and (old["part"].get("mesh") or {}).get("id") == key:
                    return old
            items.append(entry)
            self._write(items)
        return entry

    def learn(self, parts: list[dict], model_name: str, source: dict | None = None) -> int:
        """File every component of an imported model. Returns how many were new."""
        before = len(self.list())
        tag = _words(model_name)[:4]
        for p in parts:
            try:
                self.add(p, p.get("name", ""), tags=tag + _words(p.get("name", ""))[:4], source=source,
                         learned_from=model_name)
            except ValueError:
                continue
        return len(self.list()) - before

    def search(self, query: str = "", limit: int = 20) -> list[dict]:
        items = self.list()
        words = _words(query)
        if not words:
            return sorted(items, key=lambda s: s["added"], reverse=True)[:limit]
        scored = []
        for s in items:
            hay = " ".join([s["name"], " ".join(s["tags"]), s.get("learned_from", "")]).lower()
            score = sum(3 if w in _words(s["name"]) else 1 for w in words if w in hay)
            if score:
                scored.append((score, s.get("uses", 0), s))
        scored.sort(key=lambda t: (t[0], t[1]), reverse=True)
        return [s for *_, s in scored[:limit]]

    def to_part(self, sid: str, overrides: dict | None = None) -> dict:
        """A new blueprint part built from a library shape (position, name etc. from overrides)."""
        with self._lock:
            items = self.list()
            entry = next((s for s in items if s["id"] == sid), None)
            if entry is None:
                raise KeyError(f"No shape '{sid}' in the library. Use find_shapes to see what's there.")
            entry["uses"] = entry.get("uses", 0) + 1
            self._write(items)
        part = {**copy.deepcopy(entry["part"]), "name": entry["name"]}
        for k, v in (overrides or {}).items():
            if k not in ("from_library", "id"):
                part[k] = v
        return part

    def delete(self, sid: str) -> None:
        with self._lock:
            items = self.list()
            kept = [s for s in items if s["id"] != sid]
            if len(kept) == len(items):
                raise KeyError(sid)
            self._write(kept)
