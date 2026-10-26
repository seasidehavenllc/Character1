"""On the hub: the owner's PC tools, forwarded to the PC node while it's connected.

The tools appear when the PC comes online and disappear when it goes offline (the
registry asks this provider on every step). Running one sends a job to the PC; any
approval the PC needs shows up in the hub's chat as usual.
"""
from __future__ import annotations

from ..nodes import NodeHub
from .base import Tool, ToolContext, ToolRegistry


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    hub: NodeHub | None = ctx.state.get("node_hub")
    if hub is None:
        return

    def make(node_id: str, schema: dict) -> Tool:
        fn = schema["function"]
        name = fn["name"]

        def forward(**args) -> str:
            try:
                return str(hub.call(node_id, "tool", name, args, approver=ctx.approver))
            except (ConnectionError, TimeoutError) as e:
                return f"ERROR: {e}"

        desc = fn.get("description", "")
        return Tool(name, f"On the owner's PC: {desc}", fn.get("parameters", {"type": "object",
                    "properties": {}}), forward)

    def provide() -> dict[str, Tool]:
        live = hub.online()
        if not live:
            return {}
        node = live[0]  # one PC for now; more devices can be told apart later
        return {s["function"]["name"]: make(node.id, s) for s in node.tools}

    reg.providers.append(provide)
