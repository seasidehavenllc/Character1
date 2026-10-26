"""Shell tool: run builds, tests, and scripts — gated by the command policy."""
from __future__ import annotations

import subprocess

from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    ws = ctx.workspace

    def run_command(command: str, cwd: str = ".", timeout: int = 300, reason: str = "") -> str:
        ok, why = ctx.policy.check(command, reason)
        if not ok:
            return f"Command not run: {why}"
        workdir = ws.resolve(cwd)
        try:
            proc = subprocess.run(
                command, shell=True, cwd=workdir, capture_output=True,
                text=True, errors="replace", timeout=timeout,
            )
        except subprocess.TimeoutExpired as e:
            partial = (e.stdout or "") if isinstance(e.stdout, str) else ""
            return f"TIMEOUT after {timeout}s.\n{partial[-4000:]}"
        out = (proc.stdout or "") + (("\n[stderr]\n" + proc.stderr) if proc.stderr else "")
        return f"exit code {proc.returncode}\n{out.strip() or '(no output)'}"

    reg.register(Tool(
        "run_command",
        "Run a shell command in the workspace (build, test, run scripts, package managers). "
        "Returns exit code and output. Give a short reason for anything unusual.",
        params(["command"], command={"type": "string"}, cwd={"type": "string"},
               timeout={"type": "integer"}, reason={"type": "string"}),
        run_command))
