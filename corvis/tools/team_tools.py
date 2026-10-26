"""Bots handing work to each other: ask_bot.

The asking bot writes a request; the other bot works on it with its own job, abilities and
memory, and its answer comes back as the tool result. The chat shows "Looping in <bot>"
and the other bot's steps as they happen. Hand-offs can go two levels deep, so bots can't
bounce work around forever.
"""
from __future__ import annotations

from .base import Tool, ToolContext, ToolRegistry, params

MAX_DEPTH = 2


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    bots = ctx.state.get("bots")
    spawn = ctx.state.get("spawn_bot")
    if bots is None or spawn is None or ctx.state.get("depth", 0) >= MAX_DEPTH:
        return
    me = ctx.state.get("bot") or {}
    if len(bots.list()) < 2:
        return

    def ask_bot(bot: str, request: str) -> str:
        target = bots.find(bot)
        if target is None:
            names = ", ".join(b["name"] for b in bots.list() if b["id"] != me.get("id"))
            return f"ERROR: there's no bot called '{bot}'. Your teammates: {names}."
        if target["id"] == me.get("id"):
            return "ERROR: that's you. Do the work yourself, or pick a teammate."
        if not request.strip():
            return "ERROR: say what you need from them."
        return spawn(target, request.strip())

    reg.register(Tool(
        "ask_bot",
        "Hand a piece of work to a teammate bot and get their result back. Use it when the task "
        "fits their job better than yours. They don't see this chat, so include everything they need.",
        params(["bot", "request"], bot={"type": "string", "description": "The teammate's name"},
               request={"type": "string"}),
        ask_bot))
