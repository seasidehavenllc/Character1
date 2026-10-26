"""Tool loading. To add a capability, write a module with register(reg, ctx)
and add it to TOOL_MODULES (or drop it in corvis/plugins/, loaded automatically)."""
from __future__ import annotations

import importlib
import pkgutil
import traceback

from . import (addon_tools, app_tools, attachment_tools, browser_tools, files, git_tools, graphify_tools, memory_tools, node_tools, pc_tools, plan,
               routine_tools, search, shell, team_tools, web_tools)
from .base import Tool, ToolContext, ToolRegistry, params

TOOL_MODULES = [plan, files, search, shell, git_tools, graphify_tools, memory_tools, web_tools, attachment_tools,
                pc_tools, app_tools, node_tools, team_tools, routine_tools,
                browser_tools, addon_tools]


def load_plugins(reg: ToolRegistry, ctx: ToolContext) -> list[str]:
    """Load every module in corvis/plugins that has a register() function.

    Each plugin loads on its own: a broken plugin is reported and skipped,
    and never stops the others from loading.
    """
    errors: list[str] = []
    plugins = importlib.import_module("corvis.plugins")
    for info in pkgutil.iter_modules(plugins.__path__):
        name = f"corvis.plugins.{info.name}"
        try:
            mod = importlib.import_module(name)
            if hasattr(mod, "register"):
                mod.register(reg, ctx)
        except Exception as e:
            tb = traceback.format_exc(limit=2).strip().splitlines()[-1]
            errors.append(f"Plugin '{info.name}' failed to load: {type(e).__name__}: {e} ({tb})")
    return errors


def build_registry(ctx: ToolContext) -> ToolRegistry:
    reg = ToolRegistry(ctx)
    for mod in TOOL_MODULES:
        mod.register(reg, ctx)
    ctx.state["plugin_errors"] = load_plugins(reg, ctx) + ctx.state.get("addon_errors", [])
    return reg


__all__ = ["Tool", "ToolContext", "ToolRegistry", "build_registry", "load_plugins", "params"]
