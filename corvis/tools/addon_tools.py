"""Connectors and plugins as tools: connector tools (mcp_*), plugin tools, and use_skill."""
from __future__ import annotations

from .. import connectors as connectors_mod
from ..plugin_store import PluginStore
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    cfg = ctx.config or {}
    data_dir = ctx.state.get("data_dir")
    if not data_dir:
        return
    plugins_on = (cfg.get("plugins") or {}).get("enabled", True) is not False
    connectors_on = (cfg.get("connectors") or {}).get("enabled", True) is not False
    store = PluginStore(data_dir) if plugins_on else None
    ctx.state["addon_errors"] = []

    if store is not None:
        ctx.state["addon_errors"] += store.load_tools(reg, ctx)
        skills = store.skills()
        ctx.state["skills"] = [{"name": s["name"], "plugin": s["plugin"], "description": s["description"]}
                               for s in skills]
        if skills:
            by_name = {s["name"].lower(): s for s in skills}

            def use_skill(name: str) -> str:
                skill = by_name.get(name.strip().lower())
                if skill is None:
                    return f"ERROR: no skill '{name}'. Available: {', '.join(s['name'] for s in skills)}"
                extra = sorted(str(p.relative_to(skill["folder"])) for p in skill["folder"].rglob("*")
                               if p.is_file() and p.name != "SKILL.md")
                files = ("\n\nOther files in this skill (ask the owner or use your file tools to read them):\n"
                         + "\n".join(f"- {f}" for f in extra[:40])) if extra else ""
                return f"Skill '{skill['name']}' from the {skill['plugin']} plugin:\n\n{skill['body']}{files}"

            reg.register(Tool(
                "use_skill",
                "Load a skill: expert instructions from an installed plugin. Load one whenever the task "
                "matches its description, then follow it.",
                params(["name"], name={"type": "string", "enum": [s["name"] for s in skills]}),
                use_skill))

    if connectors_on:
        manager = connectors_mod.shared(data_dir, extra=store.connectors if store else None)
        approver = ctx.approver
        reg.providers.append(lambda: manager.tools_for_agent(approver))
