"""Sandboxing: keep file access inside the workspace and gate shell commands."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Callable

# Folders that are huge, generated, or never worth reading.
IGNORED_DIRS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".mypy_cache",
    ".pytest_cache", "dist", "build", "target", ".idea", ".vs",
    # Unreal
    "Intermediate", "Binaries", "DerivedDataCache", "Saved",
    # Unity
    "Library", "Temp", "Logs", "obj",
    # Godot
    ".godot", ".import",
}


class Workspace:
    """All file tools resolve paths through here, so Corvis can't wander off."""

    def __init__(self, root: str | Path):
        self.root = Path(root).expanduser().resolve()

    def resolve(self, path: str | Path) -> Path:
        p = Path(path).expanduser()
        p = (p if p.is_absolute() else self.root / p).resolve()
        if p != self.root and not p.is_relative_to(self.root):
            raise PermissionError(f"'{path}' is outside the workspace ({self.root})")
        return p

    def rel(self, path: Path) -> str:
        try:
            return str(path.relative_to(self.root)) or "."
        except ValueError:
            return str(path)


DEFAULT_AUTO_ALLOW = [
    r"^git (status|diff|log|show|branch|add|commit|checkout -b|stash)\b",
    r"^(python|python3|py) -m (pytest|unittest|py_compile|compileall)\b",
    r"^(pytest|ruff|black --check|mypy|flake8)\b",
    r"^(npm|pnpm|yarn) (test|run (build|lint|test)|install)\b",
    r"^(npx )?(tsc|eslint|jest|vitest)\b",
    r"^cargo (build|test|check|clippy|fmt)\b",
    r"^go (build|test|vet|fmt)\b",
    r"^dotnet (build|test|restore)\b",
    r"^(cmake|make|ninja|msbuild)\b",
    r"^(mvn|gradle|\./gradlew|gradlew) (compile|test|build)\b",
    r"^(ls|dir|pwd|echo|cat|type|where|which)\b",
]

DEFAULT_ALWAYS_BLOCK = [
    r"rm\s+-rf\s+[/~]",            # wipe root/home
    r"\bformat\s+[a-z]:",          # format a drive
    r"\b(shutdown|reboot)\b",
    r"\bdel\s+/[sq].*\s[a-z]:\\",  # recursive delete on a drive
    r"\bmkfs\b",
    r"(curl|wget|iwr|Invoke-WebRequest).*\|\s*(sh|bash|iex|python)",  # pipe-to-shell
    r"\bgit push\b.*--force",
]


class CommandPolicy:
    """Decides whether a shell command runs automatically, needs your OK, or is refused."""

    def __init__(
        self,
        mode: str = "ask",  # "ask" or "auto"
        auto_allow: list[str] | None = None,
        always_block: list[str] | None = None,
        approver: Callable[[str], bool] | None = None,
    ):
        self.mode = mode
        self.auto_allow = [re.compile(p, re.I) for p in (auto_allow or DEFAULT_AUTO_ALLOW)]
        self.always_block = [re.compile(p, re.I) for p in (always_block or DEFAULT_ALWAYS_BLOCK)]
        self.approver = approver or (lambda _: False)

    def check(self, command: str, reason: str = "") -> tuple[bool, str]:
        cmd = command.strip()
        for p in self.always_block:
            if p.search(cmd):
                return False, "Blocked by safety policy."
        if self.mode == "auto":
            return True, ""
        # Chained commands always need a human look.
        chained = bool(re.search(r"(&&|\|\||;|\|)", cmd))
        if not chained and any(p.search(cmd) for p in self.auto_allow):
            return True, ""
        prompt = f"{reason}\n$ {cmd}" if reason else f"$ {cmd}"
        if self.approver(prompt):
            return True, ""
        return False, "The owner declined this command."
