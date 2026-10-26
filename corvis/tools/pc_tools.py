"""PC-wide file tools: anything on the PC the owner allows, not just the project folder.

Asks the owner first before: deleting (to the Recycle Bin), moving/renaming, overwriting
a file outside the project, or creating a script/program outside the project.
"""
from __future__ import annotations

import shutil
from pathlib import Path

from .. import pc
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    policy: pc.PCPolicy | None = ctx.state.get("pc_policy")
    if policy is None or not policy.enabled:
        return
    project = ctx.workspace.root
    trash = Path(ctx.state.get("data_dir", project)) / "trash"

    def in_project(p: Path) -> bool:
        return pc._under(p, project)

    def ask(prompt: str) -> bool:
        return ctx.approver(prompt)

    def pc_list(path: str = "", show_hidden: bool = False) -> str:
        listing = pc.list_dir(policy, path, show_hidden)
        if not listing["path"]:
            return "Drives / top folders Corvis may use:\n" + "\n".join(e["path"] for e in listing["entries"])
        lines = [f"{listing['path']}  ({len(listing['entries'])} items)"]
        for e in listing["entries"][:400]:
            lines.append(f"  {e['name']}/" if e["is_dir"] else f"  {e['name']}  ({pc.human_size(e['size'])})")
        if len(listing["entries"]) > 400:
            lines.append(f"  ... and {len(listing['entries']) - 400} more")
        return "\n".join(lines)

    def pc_read(path: str, start: int = 0) -> str:
        return pc.read_text(policy.check(path, "read"), start)

    def pc_find(name: str, folder: str) -> str:
        hits = pc.find(policy, name, folder)
        return "\n".join(hits) if hits else f"Nothing named like '{name}' under {folder}."

    def pc_write(path: str, content: str, overwrite: bool = False) -> str:
        p = policy.check(path, "write")
        if p.is_dir():
            return f"ERROR: {p} is a folder."
        existed = p.exists()
        if existed and not overwrite:
            return f"ERROR: {p} already exists. Pass overwrite=true to replace it."
        reasons = []
        if existed and not in_project(p):
            reasons.append("replace an existing file outside the project")
        if p.suffix.lower() in pc.RUNNABLE_EXTS and not in_project(p):
            reasons.append(f"create a {p.suffix} file that can run code")
        if reasons and not ask(f"Corvis wants to {' and '.join(reasons)}:\n{p}\n\nFirst lines:\n{content[:400]}"):
            return "The owner declined this change."
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        return f"{'Replaced' if existed else 'Created'} {p} ({len(content.splitlines())} lines)"

    def pc_make_folder(path: str) -> str:
        p = policy.check(path, "write")
        if p.exists():
            return f"{p} already exists."
        p.mkdir(parents=True)
        return f"Created folder {p}"

    def pc_move(source: str, destination: str) -> str:
        src = policy.check(source, "delete")  # moving removes it from where it was
        dst = policy.check(destination, "write")
        if not src.exists():
            return f"ERROR: {src} doesn't exist."
        if dst.is_dir():
            dst = dst / src.name
        if dst.exists():
            return f"ERROR: {dst} already exists. Move or rename that first."
        what = "folder" if src.is_dir() else "file"
        if not ask(f"Move this {what}?\nFrom: {src}\nTo:   {dst}"):
            return "The owner declined this move."
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(src), str(dst))
        return f"Moved {src} to {dst}"

    def pc_delete(path: str) -> str:
        p = policy.check(path, "delete")
        if not p.exists():
            return f"ERROR: {p} doesn't exist."
        if any(p == r for r in policy.roots):
            return "ERROR: Corvis won't delete a whole drive."
        detail = f"folder: {pc.folder_summary(p)}" if p.is_dir() else f"file, {pc.human_size(p.stat().st_size)}"
        if not ask(f"Delete this {detail}? It goes to the Recycle Bin.\n{p}"):
            return "The owner declined deleting it."
        where = pc.recycle(p, trash)
        return f"Deleted {p} (it's in the {where} if you need it back)."

    pc_note = "Paths are full paths like D:/Games/MyGame or C:/Users/you/Documents."
    reg.register(Tool("pc_list", "List a folder anywhere on the PC. Empty path lists the drives. " + pc_note,
                      params([], path={"type": "string"}, show_hidden={"type": "boolean"}), pc_list))
    reg.register(Tool("pc_read", "Read a file anywhere on the PC (text, code, PDF, Word). " + pc_note,
                      params(["path"], path={"type": "string"}, start={"type": "integer"}), pc_read))
    reg.register(Tool("pc_find", "Find files or folders by name under a folder on the PC, "
                      "e.g. name='*.uproject' folder='D:/'.",
                      params(["name", "folder"], name={"type": "string"}, folder={"type": "string"}), pc_find))
    reg.register(Tool("pc_write", "Create a file anywhere on the PC (or overwrite with overwrite=true). "
                      "Use the project tools for files inside the project. " + pc_note,
                      params(["path", "content"], path={"type": "string"}, content={"type": "string"},
                             overwrite={"type": "boolean"}), pc_write))
    reg.register(Tool("pc_make_folder", "Create a folder anywhere on the PC.",
                      params(["path"], path={"type": "string"}), pc_make_folder))
    reg.register(Tool("pc_move", "Move or rename a file or folder on the PC. The owner must approve.",
                      params(["source", "destination"], source={"type": "string"},
                             destination={"type": "string"}), pc_move))
    reg.register(Tool("pc_delete", "Delete a file or folder on the PC. It goes to the Recycle Bin, and "
                      "the owner must approve.", params(["path"], path={"type": "string"}), pc_delete))
