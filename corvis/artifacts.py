"""Artifacts: things Corvis makes that live outside the chat, like Claude's artifacts.

An artifact is a web page (HTML with its own CSS/JS), a document (Markdown), code, or an
SVG drawing. It opens in a panel beside the chat, keeps every version, and shows up in the
Artifacts gallery. Corvis creates and edits them with tools; the owner can view, flip
between versions, copy, download or delete them.

Web pages and SVGs are written by a model, so they're treated as untrusted: the app shows
them in a sandboxed frame that can't reach Corvis's API, the owner's files or the network
(see the /artifact-view route in web/server.py).

Stored in data/artifacts/<id>.json.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
import uuid
from pathlib import Path

TYPES = {
    "html": "Web page (HTML, CSS and JavaScript in one file)",
    "markdown": "Document (Markdown)",
    "code": "Code in any language",
    "svg": "Vector drawing (SVG)",
}
MAX_CHARS = 400_000
MAX_VERSIONS = 50
EXTENSIONS = {"html": "html", "markdown": "md", "svg": "svg"}
CODE_EXT = {"python": "py", "javascript": "js", "typescript": "ts", "rust": "rs", "go": "go", "java": "java",
            "c": "c", "cpp": "cpp", "c++": "cpp", "csharp": "cs", "c#": "cs", "ruby": "rb", "php": "php",
            "swift": "swift", "kotlin": "kt", "bash": "sh", "shell": "sh", "sql": "sql", "json": "json",
            "yaml": "yaml", "css": "css", "lua": "lua", "gdscript": "gd", "arduino": "ino"}


class ArtifactStore:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "artifacts"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    def _path(self, aid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{10}", aid or ""):
            raise KeyError(aid)
        return self.root / f"{aid}.json"

    def _write(self, a: dict) -> None:
        tmp = self._path(a["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(a, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self._path(a["id"]))

    def get(self, aid: str) -> dict:
        try:
            return json.loads(self._path(aid).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise KeyError(aid) from None

    def list(self, conversation_id: str | None = None, project: str | None = None) -> list[dict]:
        out = []
        for path in self.root.glob("*.json"):
            try:
                a = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            if conversation_id and a.get("conversation_id") != conversation_id:
                continue
            if project and a.get("project") != project:
                continue
            out.append(self.summary(a))
        return sorted(out, key=lambda a: a["updated"], reverse=True)

    @staticmethod
    def summary(a: dict) -> dict:
        latest = a["versions"][-1]["content"]
        return {k: a.get(k) for k in ("id", "title", "type", "language", "created", "updated", "conversation_id",
                                      "project")} | {"versions": len(a["versions"]), "chars": len(latest),
                                                     "preview": latest[:240]}

    def find(self, ref: str, conversation_id: str | None = None) -> dict:
        """By id, or by title (the newest match, preferring this chat's artifacts)."""
        ref = str(ref or "").strip()
        try:
            return self.get(ref)
        except KeyError:
            pass
        items = self.list()
        low = ref.lower()
        matches = [a for a in items if a["title"].lower() == low] or [a for a in items if low and low in a["title"].lower()]
        if conversation_id:
            matches.sort(key=lambda a: a["conversation_id"] != conversation_id)
        if not matches:
            raise KeyError(f"No artifact called '{ref}'. Use list_artifacts to see them.")
        return self.get(matches[0]["id"])

    @staticmethod
    def _check(type_: str, content: str) -> None:
        if type_ not in TYPES:
            raise ValueError(f"Unknown artifact type '{type_}'. Use one of: {', '.join(TYPES)}.")
        if not str(content).strip():
            raise ValueError("An artifact needs content.")
        if len(content) > MAX_CHARS:
            raise ValueError(f"That's too long for one artifact ({len(content)} characters; the limit is {MAX_CHARS}).")

    def create(self, title: str, type_: str, content: str, language: str = "", conversation_id: str | None = None,
               project: str | None = None) -> dict:
        title = " ".join(str(title or "").split())[:100] or "Untitled"
        self._check(type_, content)
        now = time.time()
        a = {"id": uuid.uuid4().hex[:10], "title": title, "type": type_,
             "language": str(language or "").strip().lower()[:30] if type_ == "code" else "",
             "created": now, "updated": now, "conversation_id": conversation_id, "project": project,
             "versions": [{"content": content, "ts": now, "note": "First version", "conversation_id": conversation_id}]}
        with self._lock:
            self._write(a)
        return a

    def add_version(self, aid: str, content: str, note: str = "", conversation_id: str | None = None,
                    title: str | None = None) -> dict:
        with self._lock:
            a = self.get(aid)
            self._check(a["type"], content)
            if content == a["versions"][-1]["content"] and not title:
                return a
            now = time.time()
            a["versions"].append({"content": content, "ts": now, "note": str(note or "").strip()[:200] or "Updated",
                                  "conversation_id": conversation_id})
            a["versions"] = a["versions"][-MAX_VERSIONS:]
            if title:
                a["title"] = " ".join(str(title).split())[:100] or a["title"]
            a["updated"] = now
            self._write(a)
            return a

    def edit(self, aid: str, old: str, new: str, note: str = "", conversation_id: str | None = None) -> dict:
        """Change one exact piece of the latest version (small edits without resending everything)."""
        latest = self.get(aid)["versions"][-1]["content"]
        count = latest.count(old) if old else 0
        if count != 1:
            raise ValueError("The text to replace must appear exactly once in the artifact "
                             f"(found {count} times). Copy a longer, exact piece, or rewrite the whole artifact.")
        return self.add_version(aid, latest.replace(old, new), note, conversation_id)

    def rename(self, aid: str, title: str) -> dict:
        with self._lock:
            a = self.get(aid)
            a["title"] = " ".join(str(title).split())[:100] or a["title"]
            self._write(a)
            return a

    def delete(self, aid: str) -> None:
        with self._lock:
            path = self._path(aid)
            if not path.exists():
                raise KeyError(aid)
            path.unlink()

    @staticmethod
    def filename(a: dict) -> str:
        ext = EXTENSIONS.get(a["type"]) or CODE_EXT.get(a.get("language") or "", "txt")
        stem = re.sub(r"[^\w-]+", "-", a["title"].lower()).strip("-")[:50] or "artifact"
        return f"{stem}.{ext}"
