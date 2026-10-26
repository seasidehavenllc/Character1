"""Native Corvis productivity workspace: notes, tasks, calendar, documents and email drafts.

This deliberately implements Corvis-owned data models rather than copying another project's code.
All user content is stored locally as JSON with atomic replacement.
"""
from __future__ import annotations
import json, os, re, threading, uuid
from datetime import datetime, timezone
from pathlib import Path

_ID = re.compile(r"^[a-zA-Z0-9_-]{1,80}$")

def _now(): return datetime.now(timezone.utc).isoformat()

def _clean(value, limit=20000):
    if not isinstance(value, str): raise ValueError("Text fields must be strings.")
    value = value.strip()
    if len(value) > limit: raise ValueError(f"Text exceeds {limit} characters.")
    return value

class WorkspaceStore:
    COLLECTIONS = {"notes", "tasks", "events", "documents", "email_drafts"}
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "workspace"
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "workspace.json"
        self.lock = threading.RLock()
        self.data = {"notes": [], "tasks": [], "events": [], "documents": [], "email_drafts": [], "updated_at": _now()}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                for name in self.COLLECTIONS:
                    if isinstance(loaded.get(name), list): self.data[name] = loaded[name]
        except (OSError, ValueError): pass

    def _save(self):
        self.data["updated_at"] = _now()
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def list(self, collection):
        self._check_collection(collection)
        with self.lock: return list(self.data[collection])

    def _check_collection(self, collection):
        if collection not in self.COLLECTIONS: raise ValueError("Unsupported workspace collection.")

    def create(self, collection, payload):
        self._check_collection(collection)
        if not isinstance(payload, dict): raise ValueError("Expected an object.")
        title = _clean(payload.get("title", ""), 240)
        if not title: raise ValueError("A title is required.")
        item = {"id": uuid.uuid4().hex[:16], "title": title, "created_at": _now(), "updated_at": _now()}
        limits = {"notes": {"content": 50000, "tags": 1000}, "tasks": {"description": 8000, "due_at": 100},
                  "events": {"description": 8000, "start_at": 100, "end_at": 100, "timezone": 80},
                  "documents": {"content": 1000000, "format": 20},
                  "email_drafts": {"to": 1000, "cc": 1000, "subject": 500, "body": 50000}}
        for field, limit in limits[collection].items():
            value = payload.get(field, "")
            if field == "tags" and isinstance(value, list): value = ", ".join(str(x) for x in value[:30])
            item[field] = _clean(value if isinstance(value, str) else str(value), limit)
        if collection == "tasks":
            status = payload.get("status", "open")
            if status not in {"open", "in_progress", "done", "cancelled"}: raise ValueError("Invalid task status.")
            item["status"] = status
            item["priority"] = payload.get("priority", "normal") if payload.get("priority", "normal") in {"low", "normal", "high"} else "normal"
        if collection == "events":
            if not item.get("start_at"): raise ValueError("Calendar event start_at is required.")
            item["all_day"] = bool(payload.get("all_day", False))
        if collection == "documents": item["format"] = item.get("format") or "markdown"
        with self.lock:
            self.data[collection].insert(0, item); self._save()
        return item

    def update(self, collection, item_id, payload):
        self._check_collection(collection)
        if not _ID.fullmatch(item_id): raise ValueError("Invalid item ID.")
        if not isinstance(payload, dict): raise ValueError("Expected an object.")
        with self.lock:
            item = next((x for x in self.data[collection] if x.get("id") == item_id), None)
            if item is None: return None
            allowed = {"title": 240, "content": 1000000 if collection == "documents" else 50000,
                       "description": 8000, "tags": 1000, "due_at": 100, "start_at": 100, "end_at": 100,
                       "timezone": 80, "to": 1000, "cc": 1000, "subject": 500, "body": 50000,
                       "format": 20, "status": 20, "priority": 20, "all_day": 0}
            for key, value in payload.items():
                if key not in allowed: continue
                if key == "all_day" and collection == "events": item[key] = bool(value); continue
                if key == "status" and collection == "tasks" and value not in {"open", "in_progress", "done", "cancelled"}: raise ValueError("Invalid task status.")
                if key == "priority" and collection == "tasks" and value not in {"low", "normal", "high"}: raise ValueError("Invalid priority.")
                if key in {"title", "content", "description", "tags", "due_at", "start_at", "end_at", "timezone", "to", "cc", "subject", "body", "format", "status", "priority"}:
                    item[key] = _clean(str(value), allowed[key])
            item["updated_at"] = _now(); self._save(); return item

    def delete(self, collection, item_id):
        self._check_collection(collection)
        with self.lock:
            before = len(self.data[collection])
            self.data[collection] = [x for x in self.data[collection] if x.get("id") != item_id]
            if len(self.data[collection]) == before: return False
            self._save(); return True

    def summary(self):
        with self.lock:
            return {"counts": {k: len(self.data[k]) for k in sorted(self.COLLECTIONS)},
                    "open_tasks": sum(1 for x in self.data["tasks"] if x.get("status") not in {"done", "cancelled"}),
                    "updated_at": self.data["updated_at"], "storage": "local-json"}
