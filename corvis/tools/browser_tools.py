"""The bot's computer: browse, read, click and type on real websites, signed in as the owner."""
from __future__ import annotations

from .. import computer as comp_mod
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    cfg = (ctx.config.get("computer") or {})
    if cfg.get("enabled", True) is False:
        return
    comp = ctx.state.get("computer")
    if comp is None and not comp_mod.available():
        return  # no browser installed on this machine (the hub installer sets it up)
    if comp is None:
        comp = comp_mod.shared(ctx.state["data_dir"], allow_private=bool(cfg.get("allow_private")))
    key = (ctx.state.get("bot") or {}).get("id", "corvis")   # each bot uses its own tab

    def browser_open(url: str) -> str:
        return comp.open(key, url)

    def browser_read() -> str:
        return comp.read(key)

    def browser_click(element: int) -> str:
        info = comp.describe_element(key, element)
        if comp_mod.is_risky(info):
            label = info.get("text") or info.get("tag")
            if not ctx.approver(f"Click \"{label}\" on {comp.status_url(key)}?\n"
                                "(It looks like it buys, sends, posts or deletes something.)"):
                return "The owner declined that click."
        return comp.click(key, element)

    def browser_type(element: int, text: str, submit: bool = False) -> str:
        return comp.type(key, element, text, submit)

    def browser_press(key_name: str) -> str:
        return comp.press(key, key_name)

    def browser_scroll(direction: str = "down") -> str:
        return comp.scroll(key, direction)

    reg.register(Tool("browser_open", "Open a web page on your computer's browser (stays signed in to "
                      "the owner's tools). Returns the page text and numbered things you can click or type into.",
                      params(["url"], url={"type": "string"}), browser_open))
    reg.register(Tool("browser_read", "Read the current page again (text and numbered elements).",
                      params([]), browser_read))
    reg.register(Tool("browser_click", "Click a numbered element from the last page read.",
                      params(["element"], element={"type": "integer"}), browser_click))
    reg.register(Tool("browser_type", "Type into a numbered box (replaces what's there). submit=true "
                      "presses Enter after. Never for passwords.",
                      params(["element", "text"], element={"type": "integer"}, text={"type": "string"},
                             submit={"type": "boolean"}), browser_type))
    reg.register(Tool("browser_press", "Press a key on the page, like Enter, Tab, Escape or PageDown.",
                      params(["key_name"], key_name={"type": "string"}), browser_press))
    reg.register(Tool("browser_scroll", "Scroll the page up or down.",
                      params([], direction={"type": "string", "enum": ["up", "down"]}), browser_scroll))
