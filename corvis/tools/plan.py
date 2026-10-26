"""Planning tool: a checklist the model keeps up to date.

Local models stay on track much better on long tasks when they write the
plan down and tick items off, so this is cheap but worth a lot.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry, params

MARKS = {"done": "[x]", "in_progress": "[>]", "pending": "[ ]"}


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    def update_plan(steps: list) -> str:
        clean = []
        for s in steps:
            if isinstance(s, str):
                s = {"step": s, "status": "pending"}
            clean.append({"step": str(s.get("step", "")),
                          "status": s.get("status", "pending")})
        ctx.state["plan"] = clean
        return "Plan:\n" + "\n".join(f"{MARKS.get(s['status'], '[ ]')} {s['step']}" for s in clean)

    reg.register(Tool(
        "update_plan",
        "Write or update your step-by-step plan for the task. Call it at the start of any "
        "multi-step task and again as steps finish. Status: pending, in_progress, done.",
        params(["steps"], steps={
            "type": "array",
            "items": {"type": "object", "properties": {
                "step": {"type": "string"},
                "status": {"type": "string", "enum": ["pending", "in_progress", "done"]}},
                "required": ["step"]}}),
        update_plan))
