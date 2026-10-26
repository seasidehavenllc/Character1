"""Tool system: every capability Corvis has is a Tool in a registry.

A tool = name + description + JSON-schema inputs + a Python function that
returns a string. Add new tools (Blender, Unreal, smart home...) by writing a
module with a `register(registry, ctx)` function — nothing else changes.
"""
from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

from ..safety import CommandPolicy, Workspace


@dataclass
class ToolContext:
    workspace: Workspace
    policy: CommandPolicy
    approver: Callable[[str], bool]
    output_limit: int = 12000
    config: dict = field(default_factory=dict)  # the loaded config.yaml
    state: dict = field(default_factory=dict)  # shared scratch space (e.g. the plan)


@dataclass
class Tool:
    name: str
    description: str
    parameters: dict
    func: Callable[..., str]
    needs_approval: bool = False

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }


def params(required: list[str] | None = None, **props: Any) -> dict:
    """Shorthand for a JSON schema: params(['path'], path={'type':'string', ...})."""
    return {"type": "object", "properties": props, "required": required or []}


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = text[: limit // 3]
    tail = text[-(limit * 2 // 3):]
    return f"{head}\n\n... [{len(text) - limit} characters trimmed] ...\n\n{tail}"


class ToolRegistry:
    def __init__(self, ctx: ToolContext):
        self.ctx = ctx
        self.tools: dict[str, Tool] = {}
        # Providers add tools that can come and go while Corvis runs (e.g. the owner's PC
        # tools, available only while the PC node is connected). Checked on every step.
        self.providers: list[Callable[[], dict[str, Tool]]] = []
        # Which tools this agent may use (a bot only gets the abilities its owner gave it).
        self.allow: Callable[[str], bool] | None = None

    def register(self, tool: Tool) -> None:
        self.tools[tool.name] = tool

    def all_tools(self) -> dict[str, Tool]:
        merged = dict(self.tools)
        for provide in self.providers:
            try:
                for name, tool in provide().items():
                    merged.setdefault(name, tool)
            except Exception:
                continue  # a broken provider must never take the built-in tools down
        if self.allow is not None:
            merged = {k: v for k, v in merged.items() if self.allow(k)}
        return merged

    def schemas(self) -> list[dict]:
        return [t.schema() for t in self.all_tools().values()]

    def run(self, name: str, args: dict) -> str:
        tools = self.all_tools()
        tool = tools.get(name)
        if tool is None:
            return f"ERROR: unknown tool '{name}'. Available: {', '.join(tools)}"
        if "_raw" in args:
            return f"ERROR: tool arguments were not valid JSON: {args['_raw'][:300]}"
        if tool.needs_approval and not self.ctx.approver(f"Allow {name}({args})?"):
            return "The owner declined this action."
        try:
            out = tool.func(**args)
        except TypeError as e:
            return f"ERROR: bad arguments for {name}: {e}"
        except PermissionError as e:
            return f"ERROR: permission denied: {e}"
        except FileNotFoundError as e:
            return f"ERROR: not found: {e}"
        except Exception as e:  # tools must never crash the agent
            tb = traceback.format_exc(limit=3)
            return f"ERROR: {type(e).__name__}: {e}\n{tb}"
        return truncate(str(out), self.ctx.output_limit)
