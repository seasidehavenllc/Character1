"""Search tools: find files by name and search inside them."""
from __future__ import annotations

import fnmatch
import os
import re

from ..safety import IGNORED_DIRS
from .base import Tool, ToolContext, ToolRegistry, params


def _walk_files(root):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS]
        for f in filenames:
            yield os.path.join(dirpath, f)


def _is_binary(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            return b"\0" in fh.read(2048)
    except OSError:
        return True


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    ws = ctx.workspace

    def find_files(pattern: str, path: str = ".") -> str:
        root = ws.resolve(path)
        hits = []
        for f in _walk_files(root):
            rel = os.path.relpath(f, ws.root).replace("\\", "/")
            if fnmatch.fnmatch(rel, pattern) or fnmatch.fnmatch(os.path.basename(f), pattern):
                hits.append(rel)
                if len(hits) >= 300:
                    hits.append("... (more results trimmed)")
                    break
        return "\n".join(hits) if hits else f"No files match '{pattern}'"

    def grep(pattern: str, path: str = ".", file_pattern: str = "*",
             ignore_case: bool = False, context: int = 0) -> str:
        root = ws.resolve(path)
        try:
            rx = re.compile(pattern, re.I if ignore_case else 0)
        except re.error as e:
            return f"ERROR: bad regex: {e}"
        files = [str(root)] if root.is_file() else _walk_files(root)
        out, matches = [], 0
        for f in files:
            if not fnmatch.fnmatch(os.path.basename(f), file_pattern) or _is_binary(f):
                continue
            try:
                with open(f, encoding="utf-8", errors="replace") as fh:
                    lines = fh.read().splitlines()
            except OSError:
                continue
            rel = os.path.relpath(f, ws.root).replace("\\", "/")
            for i, line in enumerate(lines):
                if rx.search(line):
                    matches += 1
                    lo, hi = max(0, i - context), min(len(lines), i + context + 1)
                    for j in range(lo, hi):
                        sep = ":" if j == i else "-"
                        out.append(f"{rel}{sep}{j + 1}{sep} {lines[j][:300]}")
                    if context:
                        out.append("--")
                    if matches >= 200:
                        out.append("... (stopped at 200 matches; narrow the search)")
                        return "\n".join(out)
        return "\n".join(out) if out else f"No matches for /{pattern}/"

    reg.register(Tool(
        "find_files",
        "Find files by glob pattern, e.g. '**/*.cs', '*Player*', 'Source/*.cpp'.",
        params(["pattern"], pattern={"type": "string"}, path={"type": "string"}),
        find_files))
    reg.register(Tool(
        "grep",
        "Search file contents with a regex. Returns file:line: text. "
        "Use file_pattern like '*.py' to narrow, context for surrounding lines.",
        params(["pattern"], pattern={"type": "string"}, path={"type": "string"},
               file_pattern={"type": "string"}, ignore_case={"type": "boolean"},
               context={"type": "integer"}),
        grep))
