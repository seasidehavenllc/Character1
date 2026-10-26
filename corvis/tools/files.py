"""File tools: read, write, precise edits, list, delete."""
from __future__ import annotations

from pathlib import Path

from ..safety import IGNORED_DIRS
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    ws = ctx.workspace

    def read_file(path: str, start_line: int = 1, end_line: int | None = None) -> str:
        p = ws.resolve(path)
        text = p.read_text(encoding="utf-8", errors="replace")
        lines = text.splitlines()
        total = len(lines)
        start = max(1, start_line)
        end = min(total, end_line or total)
        width = len(str(end))
        body = "\n".join(f"{i:>{width}}| {lines[i - 1]}" for i in range(start, end + 1))
        return f"{ws.rel(p)} (lines {start}-{end} of {total})\n{body}"

    def write_file(path: str, content: str) -> str:
        p = ws.resolve(path)
        existed = p.exists()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        n = content.count("\n") + (0 if content.endswith("\n") or not content else 1)
        return f"{'Overwrote' if existed else 'Created'} {ws.rel(p)} ({n} lines)"

    def edit_file(path: str, old_text: str, new_text: str, replace_all: bool = False) -> str:
        p = ws.resolve(path)
        text = p.read_text(encoding="utf-8")
        count = text.count(old_text)
        if count == 0:
            # Help the model recover: whitespace mismatch is the usual cause.
            hint = ""
            first = old_text.strip().splitlines()[0].strip() if old_text.strip() else ""
            if first:
                for i, line in enumerate(text.splitlines(), 1):
                    if first in line:
                        hint = f" A similar line exists at line {i}; re-read the file and copy the text exactly."
                        break
            return f"ERROR: old_text not found in {ws.rel(p)}.{hint}"
        if count > 1 and not replace_all:
            return (f"ERROR: old_text appears {count} times in {ws.rel(p)}. "
                    "Include more surrounding lines to make it unique, or set replace_all=true.")
        text = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
        p.write_text(text, encoding="utf-8")
        return f"Edited {ws.rel(p)} ({count if replace_all else 1} replacement)"

    def list_dir(path: str = ".", depth: int = 2) -> str:
        root = ws.resolve(path)
        out: list[str] = []

        def walk(d: Path, level: int) -> None:
            try:
                entries = sorted(d.iterdir(), key=lambda e: (e.is_file(), e.name.lower()))
            except PermissionError:
                return
            for e in entries:
                if e.name in IGNORED_DIRS:
                    continue
                indent = "  " * level
                if e.is_dir():
                    out.append(f"{indent}{e.name}/")
                    if level + 1 < depth:
                        walk(e, level + 1)
                else:
                    out.append(f"{indent}{e.name}")
                if len(out) > 800:
                    return

        walk(root, 0)
        return f"{ws.rel(root)}/\n" + "\n".join(out) if out else f"{ws.rel(root)}/ is empty"

    def delete_file(path: str) -> str:
        p = ws.resolve(path)
        if p.is_dir():
            return "ERROR: delete_file only removes files, not folders."
        p.unlink()
        return f"Deleted {ws.rel(p)}"

    reg.register(Tool(
        "read_file",
        "Read a text file with line numbers. Use start_line/end_line for large files.",
        params(["path"],
               path={"type": "string", "description": "Path relative to the workspace"},
               start_line={"type": "integer"},
               end_line={"type": "integer"}),
        read_file))
    reg.register(Tool(
        "write_file",
        "Create a new file or fully replace one. Prefer edit_file for changes to existing files.",
        params(["path", "content"],
               path={"type": "string"}, content={"type": "string"}),
        write_file))
    reg.register(Tool(
        "edit_file",
        "Replace an exact block of text in a file. old_text must match the file exactly "
        "(including indentation) and be unique unless replace_all is true.",
        params(["path", "old_text", "new_text"],
               path={"type": "string"}, old_text={"type": "string"},
               new_text={"type": "string"}, replace_all={"type": "boolean"}),
        edit_file))
    reg.register(Tool(
        "list_dir",
        "Show the folder tree (skips build/cache folders like node_modules, Intermediate, Library).",
        params([], path={"type": "string"}, depth={"type": "integer"}),
        list_dir))
    reg.register(Tool(
        "delete_file",
        "Delete one file. The owner must approve.",
        params(["path"], path={"type": "string"}),
        delete_file, needs_approval=True))
