"""Artifact tools: Corvis makes web pages, documents, code and drawings that open beside the chat."""
from __future__ import annotations

from ..artifacts import TYPES, ArtifactStore
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    data_dir = ctx.state.get("data_dir")
    if not data_dir or (ctx.config.get("artifacts") or {}).get("enabled", True) is False:
        return
    store = ArtifactStore(data_dir)
    conv = ctx.state.get("conversation_id")
    project = (ctx.state.get("project") or {}).get("id")

    def done(a: dict, verb: str) -> str:
        # "artifact:<id>" lets the app show a card that opens it.
        return f"{verb} artifact '{a['title']}' (artifact:{a['id']}, version {len(a['versions'])}). " \
               "The owner can open it beside the chat."

    def create_artifact(title: str, type: str, content: str, language: str = "") -> str:
        return done(store.create(title, type, content, language, conversation_id=conv, project=project), "Created")

    def update_artifact(artifact: str, content: str, note: str = "", title: str = "") -> str:
        a = store.find(artifact, conv)
        return done(store.add_version(a["id"], content, note, conversation_id=conv, title=title or None), "Updated")

    def edit_artifact(artifact: str, old_text: str, new_text: str, note: str = "") -> str:
        a = store.find(artifact, conv)
        return done(store.edit(a["id"], old_text, new_text, note, conversation_id=conv), "Edited")

    def read_artifact(artifact: str, version: int = 0) -> str:
        a = store.find(artifact, conv)
        n = len(a["versions"])
        v = a["versions"][(int(version) - 1) if 1 <= int(version or 0) <= n else -1]
        text = v["content"]
        cut = text[:ctx.output_limit]
        return (f"{a['title']} ({a['type']}{', ' + a['language'] if a.get('language') else ''}; "
                f"artifact:{a['id']}; {n} versions)\n{cut}" + ("\n…(cut short)" if len(cut) < len(text) else ""))

    def list_artifacts(scope: str = "chat") -> str:
        items = store.list(conversation_id=conv if scope == "chat" else None,
                           project=project if scope == "project" else None)
        if not items:
            return "No artifacts yet." if scope == "all" else f"No artifacts in this {scope} yet (try scope 'all')."
        return "\n".join(f"- {a['title']} ({a['type']}, artifact:{a['id']}, {a['versions']} versions)" for a in items[:40])

    kinds = "; ".join(f"{k}: {v}" for k, v in TYPES.items())
    reg.register(Tool(
        "create_artifact",
        "Make an artifact that opens in a panel beside the chat: use it for anything the owner will "
        "look at, reuse or keep (web pages, mini apps, games, dashboards, documents, reports, full code "
        f"files, drawings) instead of pasting long content into the reply. Types: {kinds}. "
        "Web pages must be one self-contained HTML file: inline all CSS and JavaScript and use no "
        "CDN or network requests (they can't load; three.js is at /static/vendor/three/three.module.min.js).",
        params(["title", "type", "content"], title={"type": "string"},
               type={"type": "string", "enum": list(TYPES)}, content={"type": "string"},
               language={"type": "string", "description": "for code: python, javascript, rust, ..."}),
        create_artifact))
    reg.register(Tool("update_artifact", "Replace an artifact with a new full version (keeps the old ones).",
                      params(["artifact", "content"], artifact={"type": "string", "description": "id or title"},
                             content={"type": "string"}, note={"type": "string", "description": "what changed"},
                             title={"type": "string"}), update_artifact))
    reg.register(Tool("edit_artifact", "Change one exact piece of an artifact (a small edit; makes a new version).",
                      params(["artifact", "old_text", "new_text"], artifact={"type": "string"},
                             old_text={"type": "string"}, new_text={"type": "string"}, note={"type": "string"}),
                      edit_artifact))
    reg.register(Tool("read_artifact", "Read an artifact (latest version, or a version number).",
                      params(["artifact"], artifact={"type": "string"}, version={"type": "integer"}), read_artifact))
    reg.register(Tool("list_artifacts", "List artifacts in this chat, this project, or all.",
                      params([], scope={"type": "string", "enum": ["chat", "project", "all"]}), list_artifacts))
