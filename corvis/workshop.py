"""Corvis's workshop: the project folder where he reads, writes, edits and runs code.

Every file path is confined to the workspace folder. Shell commands run with the
workspace as their working directory, but they are NOT sandboxed, so each one goes
through an approval callback first (the terminal asks you; the web UI has a switch).
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable

MAX_READ_CHARS = 100_000
MAX_OUTPUT_CHARS = 20_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", ".next"}

Approver = Callable[[str], bool]


def deny_all(command: str) -> bool:
    return False


class Workshop:
    def __init__(self, root: str | Path, approve: Approver = deny_all):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.approve = approve

    def _path(self, rel: str) -> Path:
        p = (self.root / rel).resolve()
        if p != self.root and self.root not in p.parents:
            raise PermissionError(f"{rel!r} is outside the workspace ({self.root})")
        return p

    def tools(self) -> list[dict[str, Any]]:
        s = {"type": "string"}
        return [
            {
                "name": "list_files",
                "description": "List files in the workspace (recursively) under a folder. Use '.' for the whole project.",
                "input_schema": {"type": "object", "properties": {"path": s}, "required": ["path"]},
            },
            {
                "name": "read_file",
                "description": "Read a text file from the workspace.",
                "input_schema": {"type": "object", "properties": {"path": s}, "required": ["path"]},
            },
            {
                "name": "write_file",
                "description": "Create or overwrite a file in the workspace with the full content given. "
                "Creates parent folders as needed.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": s, "content": s},
                    "required": ["path", "content"],
                },
            },
            {
                "name": "edit_file",
                "description": "Replace one exact, unique snippet of text in a workspace file. Prefer this over "
                "write_file for small changes to existing files.",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": s, "old_text": s, "new_text": s},
                    "required": ["path", "old_text", "new_text"],
                },
            },
            {
                "name": "run_command",
                "description": "Run a shell command in the workspace folder (install packages, run code, run tests, "
                "use git...). The user must approve each command. Returns exit code, stdout and stderr.",
                "input_schema": {
                    "type": "object",
                    "properties": {"command": s, "timeout_s": {"type": "integer", "minimum": 1, "maximum": 600}},
                    "required": ["command"],
                },
            },
        ]

    def execute(self, name: str, args: dict[str, Any]) -> str:
        if name == "list_files":
            base = self._path(args.get("path", "."))
            if not base.exists():
                return "No such folder."
            files = []
            for p in sorted(base.rglob("*")):
                if p.is_file() and not SKIP_DIRS.intersection(p.relative_to(self.root).parts):
                    files.append(str(p.relative_to(self.root)))
                if len(files) >= 500:
                    files.append("... (truncated)")
                    break
            return "\n".join(files) or "(empty)"
        if name == "read_file":
            text = self._path(args["path"]).read_text(encoding="utf-8", errors="replace")
            return text if len(text) <= MAX_READ_CHARS else text[:MAX_READ_CHARS] + "\n... (truncated)"
        if name == "write_file":
            p = self._path(args["path"])
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(args["content"], encoding="utf-8")
            return f"Wrote {len(args['content'])} characters to {args['path']}."
        if name == "edit_file":
            p = self._path(args["path"])
            text = p.read_text(encoding="utf-8")
            count = text.count(args["old_text"])
            if count != 1:
                raise ValueError(f"old_text must appear exactly once in {args['path']} (found {count} times)")
            p.write_text(text.replace(args["old_text"], args["new_text"]), encoding="utf-8")
            return f"Edited {args['path']}."
        if name == "run_command":
            return self.run(args["command"], int(args.get("timeout_s", 120)))
        raise KeyError(name)

    def run(self, command: str, timeout_s: int = 120) -> str:
        if not self.approve(command):
            return "The user did not approve this command. Ask them, or find another way."
        try:
            proc = subprocess.run(command, shell=True, cwd=self.root, capture_output=True,
                                  text=True, timeout=timeout_s)
        except subprocess.TimeoutExpired:
            return f"Command timed out after {timeout_s}s."
        out = f"exit code {proc.returncode}\n--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
        return out if len(out) <= MAX_OUTPUT_CHARS else out[:MAX_OUTPUT_CHARS] + "\n... (truncated)"
