"""Attachment tools: read files the owner sent, look at their images, copy them into the project."""
from __future__ import annotations

import shutil

from ..attachments import AttachmentStore, human_size
from ..llm import LLMError
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    store: AttachmentStore | None = ctx.state.get("attachments")
    if store is None:
        return
    listing = ctx.state.get("conversation_attachments")  # callable -> this chat's attachments

    def resolve(ref: str) -> dict:
        ref = str(ref).strip()
        known = listing() if listing else []
        for meta in reversed(known):  # newest first, so a re-sent file wins
            if ref in (meta["id"], meta["name"]) or ref.lower() == meta["name"].lower():
                return store.get(meta["id"])
        if not listing:
            return store.get(ref)
        names = ", ".join(f"{m['name']} ({m['id']})" for m in known) or "none yet"
        raise KeyError(f"No attachment '{ref}' in this chat. Attachments here: {names}")

    def read_attachment(attachment: str, start: int = 0) -> str:
        try:
            meta = resolve(attachment)
        except KeyError as e:
            return f"ERROR: {e.args[0] if e.args else e}"
        if meta["kind"] == "image":
            return "ERROR: that's an image. Use look_at_image to ask about it."
        text = store.text(meta)
        if text is None:
            return (f"{meta['name']} is a binary file ({human_size(meta['size'])}). "
                    "Use save_attachment to copy it into the project.")
        start = max(0, int(start))
        piece = text[start:start + 12_000]
        more = (f"\n\n[{len(text) - start - len(piece)} more characters. Call read_attachment with "
                f"start={start + len(piece)}.]" if start + len(piece) < len(text) else "")
        return f"{meta['name']} (characters {start}-{start + len(piece)} of {len(text)})\n\n{piece}{more}"

    def look_at_image(attachment: str, question: str = "") -> str:
        try:
            meta = resolve(attachment)
        except KeyError as e:
            return f"ERROR: {e.args[0] if e.args else e}"
        if meta["kind"] != "image":
            return "ERROR: that isn't an image. Use read_attachment instead."
        from ..vision import look
        try:
            return look(store.path(meta), meta["mime"], ctx.config, question)
        except LLMError as e:
            return f"ERROR: {e}"

    def save_attachment(attachment: str, path: str = "", overwrite: bool = False) -> str:
        try:
            meta = resolve(attachment)
        except KeyError as e:
            return f"ERROR: {e.args[0] if e.args else e}"
        target = ctx.workspace.resolve(path or meta["name"])
        if target.is_dir() or str(path).endswith(("/", "\\")):
            target = ctx.workspace.resolve(f"{ctx.workspace.rel(target)}/{meta['name']}")
        if target.exists() and not overwrite:
            return f"ERROR: {ctx.workspace.rel(target)} already exists. Pass overwrite=true to replace it."
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(store.path(meta), target)
        return f"Saved {meta['name']} to {ctx.workspace.rel(target)} ({human_size(meta['size'])})"

    reg.register(Tool(
        "read_attachment",
        "Read a file the owner attached (code, text, PDF, Word, zip listing), by attachment id "
        "or file name. Long files come in parts: pass start to keep reading.",
        params(["attachment"], attachment={"type": "string"}, start={"type": "integer"}),
        read_attachment))
    reg.register(Tool(
        "look_at_image",
        "Ask the vision model a specific question about an image the owner attached "
        "(e.g. 'what does the error dialog say?', 'what colour is the health bar?').",
        params(["attachment"], attachment={"type": "string"}, question={"type": "string"}),
        look_at_image))
    reg.register(Tool(
        "save_attachment",
        "Copy an attached file into the project (e.g. a texture, model or script the owner sent). "
        "path is relative to the project; a folder path keeps the original file name.",
        params(["attachment"], attachment={"type": "string"}, path={"type": "string"},
               overwrite={"type": "boolean"}),
        save_attachment))
