"""Routines from chat: "every weekday at 8, check my inbox for new leads"."""
from __future__ import annotations

import datetime as dt

from ..routines import describe, zone
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    store = ctx.state.get("routines")
    bots = ctx.state.get("bots")
    if store is None or bots is None:
        return
    me = ctx.state.get("bot") or {}

    def tz() -> str:
        get = ctx.state.get("owner_tz")
        return (get() if callable(get) else get) or "UTC"

    def when(ts: float | None, z: str) -> str:
        if not ts:
            return "never"
        return dt.datetime.fromtimestamp(ts, zone(z)).strftime("%a %b %d, %H:%M")

    def create_routine(name: str, request: str, every: str, at: str = "09:00", day: str = "mon",
                       hours: int = 0, bot: str = "") -> str:
        target = bots.find(bot) if bot else me
        if target is None:
            return f"ERROR: there's no bot called '{bot}'."
        schedule = {"every": every, "at": at, "day": day, "hours": hours}
        from ..routines import check_schedule
        try:
            sched = check_schedule(schedule)
        except ValueError as e:
            return f"ERROR: {e}"
        prompt = (f"Set up a routine?\n  {name}: {describe(sched)} ({tz()})\n  Bot: {target['name']}\n"
                  f"  Request: {request}")
        if not ctx.approver(prompt):
            return "The owner declined this routine."
        r = store.create(name, target["id"], request, sched, tz())
        return f"Routine '{r['name']}' set: {r['when']} ({r['tz']}), next run {when(r['next_run'], r['tz'])}."

    def list_routines() -> str:
        items = store.list()
        if not items:
            return "No routines yet."
        lines = []
        for r in items:
            try:
                who = bots.get(r["bot"])["name"]
            except KeyError:
                who = "(deleted bot)"
            state = "" if r["enabled"] else " [paused]"
            lines.append(f"- [{r['id']}] {r['name']}{state}: {r['when']} ({r['tz']}), bot {who}, "
                         f"next {when(r['next_run'], r['tz'])}, last {when(r['last_run'], r['tz'])}"
                         f"{' (' + r['last_status'] + ')' if r.get('last_status') else ''}\n  {r['prompt'][:200]}")
        return "\n".join(lines)

    def delete_routine(routine_id: str) -> str:
        try:
            r = store.get(routine_id.strip())
        except KeyError:
            return "ERROR: no routine with that id. Use list_routines."
        if not ctx.approver(f"Delete the routine '{r['name']}' ({r['when']})?"):
            return "The owner declined."
        store.delete(r["id"])
        return f"Deleted routine '{r['name']}'."

    reg.register(Tool(
        "create_routine",
        "Schedule recurring work. every: day | weekday | week | hours. at: 24-hour time like 08:00 "
        "(for day/weekday/week). day: mon..sun (for week). hours: N (for every N hours). bot: which "
        "bot does it (default: you). request: what to do each time, written to make sense on its own. "
        "The owner approves it.",
        params(["name", "request", "every"], name={"type": "string"}, request={"type": "string"},
               every={"type": "string", "enum": ["day", "weekday", "week", "hours"]},
               at={"type": "string"}, day={"type": "string"}, hours={"type": "integer"},
               bot={"type": "string"}),
        create_routine))
    reg.register(Tool("list_routines", "List scheduled routines with their ids and next run times.",
                      params([]), list_routines))
    reg.register(Tool("delete_routine", "Delete a routine by id (the owner approves).",
                      params(["routine_id"], routine_id={"type": "string"}), delete_routine))
