"""Git tools: status, diff, log, commit. Every change Corvis makes is reviewable."""
from __future__ import annotations

import subprocess

from .base import Tool, ToolContext, ToolRegistry, params


def git(root, *args: str) -> tuple[int, str]:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True,
                          text=True, errors="replace")
    return proc.returncode, (proc.stdout + proc.stderr).strip()


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    root = ctx.workspace.root

    def git_status() -> str:
        code, out = git(root, "status", "--short", "--branch")
        return out if code == 0 else f"ERROR: {out}"

    def git_diff(path: str = "", staged: bool = False) -> str:
        args = ["diff"] + (["--staged"] if staged else []) + ([path] if path else [])
        code, out = git(root, *args)
        return (out or "(no changes)") if code == 0 else f"ERROR: {out}"

    def git_log(count: int = 10) -> str:
        code, out = git(root, "log", f"-{count}", "--oneline", "--decorate")
        return out if code == 0 else f"ERROR: {out}"

    def git_commit(message: str) -> str:
        git(root, "add", "-A")
        code, out = git(root, "commit", "-m", message)
        return out if code == 0 else f"ERROR: {out}"

    reg.register(Tool("git_status", "Show changed files and current branch.",
                      params([]), git_status))
    reg.register(Tool("git_diff", "Show uncommitted changes, optionally for one path.",
                      params([], path={"type": "string"}, staged={"type": "boolean"}),
                      git_diff))
    reg.register(Tool("git_log", "Show recent commits.",
                      params([], count={"type": "integer"}), git_log))
    reg.register(Tool("git_commit", "Stage all changes and commit with a clear message.",
                      params(["message"], message={"type": "string"}), git_commit))
