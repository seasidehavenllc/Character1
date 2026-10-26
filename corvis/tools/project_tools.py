"""Project tools: available in chats that belong to a project (see corvis/projects.py)."""
from __future__ import annotations

from pathlib import Path

from ..conversations.store import ConversationStore
from ..projects import ProjectStore
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    project = ctx.state.get("project")
    data_dir = ctx.state.get("data_dir")
    if not project or not data_dir:
        return
    store = ProjectStore(data_dir)
    pid = project["id"]

    def search_project_knowledge(query: str) -> str:
        hits = store.search(store.get(pid), query)
        if not hits:
            return f"Nothing in the project's knowledge files matches '{query}'. Try other words."
        return "\n\n".join(f"[{h['file']}, from character {h['at']}]\n{h['text']}" for h in hits)

    def read_project_file(name: str, start: int = 0) -> str:
        f, text = store.file_text(store.get(pid), name)
        start = max(0, int(start or 0))
        piece = text[start:start + ctx.output_limit]
        more = f"\n\n(… {len(text) - start - len(piece)} more characters; read again with start={start + len(piece)})" \
            if start + len(piece) < len(text) else ""
        return f"{f['name']} (characters {start}-{start + len(piece)} of {len(text)}):\n{piece}{more}"

    def save_project_memory(note: str) -> str:
        p = store.add_note(pid, note, by=(ctx.state.get("bot") or {}).get("name", "Corvis"))
        emit = ctx.state.get("emit")
        if emit:
            emit("memory", note, bot_name=f"the {p['name']} project")
        return f"Saved to the {p['name']} project's memory."

    def search_project_chats(query: str = "") -> str:
        chats = ConversationStore(Path(data_dir) / "conversations")
        here = ctx.state.get("conversation_id")
        words = [w for w in query.lower().split() if w]
        found = []
        for c in chats.list():
            if c.get("project") != pid or c["id"] == here:
                continue
            try:
                conv = chats.get(c["id"])
            except KeyError:
                continue
            for m in conv["messages"]:
                text = m.get("text") or ""
                if not words or all(w in text.lower() for w in words):
                    who = "Owner" if m["role"] == "user" else "Corvis"
                    found.append(f"- \"{c['title']}\" (chat {c['id']}) {who}: {' '.join(text.split())[:300]}")
                    if not words:
                        break
            if len(found) >= 12:
                break
        if not found:
            return "No other chat in this project matches." if words else "This is the project's only chat so far."
        return "\n".join(found)

    reg.register(Tool("search_project_knowledge", "Search this project's knowledge files for a topic.",
                      params(["query"], query={"type": "string"}), search_project_knowledge))
    reg.register(Tool("read_project_file", "Read one of this project's knowledge files (by name).",
                      params(["name"], name={"type": "string"}, start={"type": "integer"}), read_project_file))
    reg.register(Tool("save_project_memory",
                      "Remember a decision, fact or preference for this project. Every chat in the project sees it.",
                      params(["note"], note={"type": "string"}), save_project_memory))
    reg.register(Tool("search_project_chats",
                      "Look through this project's other chats (threads). Leave query empty to list them.",
                      params([], query={"type": "string"}), search_project_chats))
