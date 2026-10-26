"""Second-brain tools: the knowledge base, learning sessions, conversation memory and project memory
(see corvis/brain/). Available when the app runs with the brain turned on."""
from __future__ import annotations

from ..brain.kb import compute_confidence, health_label, source_reliability
from .base import Tool, ToolContext, ToolRegistry, params

STR_LIST = {"type": "array", "items": {"type": "string"}}


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    brain = ctx.state.get("brain")
    if brain is None:
        return
    kb, jobs, cont = brain.kb, brain.jobs, brain.continuity
    who = (ctx.state.get("bot") or {}).get("name", "Corvis")

    def line(d: dict) -> str:
        h = d["health"]
        via = f" (related to {d['via']})" if d.get("via") else ""
        return (f"- [{d['id']}] {d['title']}{via}: {d.get('summary', '')}\n"
                f"  confidence {d.get('confidence', 0)}%, health {h['score']}% ({h['label']}), "
                f"last verified {d.get('last_verified')}, {len(d.get('sources') or [])} sources"
                + (" — due for re-verification" if h["overdue"] else ""))

    def knowledge_search(query: str, include_conversations: bool = True) -> str:
        hits = kb.search(query, limit=6)
        parts = []
        if hits:
            parts.append("Knowledge base:\n" + "\n".join(line(h) for h in hits))
        if include_conversations and cont:
            convs = cont.search_conversations(query, limit=4)
            convs = [c for c in convs if c] if query.strip() else []
            if convs:
                parts.append("Earlier conversations:\n" + "\n".join(
                    f"- {c['date']} “{c['title']}” ({c['topic']}): {c['summary']}" for c in convs))
        if not parts:
            return (f"Nothing in memory about '{query}'. If it matters, search the web (and save what you find with "
                    "save_knowledge), or start learn_topic for a proper study.")
        return "\n\n".join(parts) + "\n\nRead a file in full with read_knowledge."

    def read_knowledge(file: str) -> str:
        d = kb.find(file)
        if not d:
            return f"ERROR: no knowledge file '{file}'. Use knowledge_search to find its id (Category/Topic)."
        h = d["health"]
        chains = kb.neighbours(d["id"], 2)[:6]
        links = "\n".join(" → ".join(c) for c in chains)
        return (f"{d['title']} [{d['id']}]\nConfidence {d.get('confidence')}%, health {h['score']}% ({h['label']}), "
                f"created {d.get('created')}, last verified {d.get('last_verified')}\n\n{d['body'][:ctx.output_limit]}"
                + (f"\n\nRelationship paths:\n{links}" if links else ""))

    def save_knowledge(title: str, category: str, summary: str, key_points: list | None = None, details: str = "",
                       sources: list | None = None, related: list | None = None, reason: str = "") -> str:
        urls = [str(u).strip() for u in (sources or []) if str(u).strip().startswith(("http://", "https://"))]
        if not urls and category.lower() not in ("personal", "projects"):
            return ("ERROR: knowledge needs at least one source URL you actually read (only Personal and Projects "
                    "notes may go without). Search, read the pages, then save.")
        srcs = [{"title": u, "url": u, "reliability": source_reliability(u)} for u in urls[:12]]
        rel_ids = []
        for r in related or []:
            f = kb.find(str(r))
            if f:
                rel_ids.append(f["id"])
        doc = {"title": title, "category": category, "summary": summary.strip(),
               "key_points": [str(p) for p in (key_points or []) if str(p).strip()][:12], "details": details,
               "sources": srcs, "related": rel_ids,
               "confidence": compute_confidence(srcs, 0.5 if len(srcs) > 1 else 0.0, 0) if srcs else 50}
        existing = kb.find(title)
        if existing:
            r = kb.propose(existing["id"], doc, reason or f"updated by {who} in chat", brain.auto_threshold)
            if r["status"] == "applied":
                return f"Updated {existing['id']} (confidence {r['confidence']}%); the old version is archived."
            return (f"Proposed an update to {existing['id']} (confidence {r['confidence']}%). It's waiting for the "
                    "owner's review in Knowledge → Reviews.")
        d = kb.create(doc, f"Learn (chat): {title}")
        return f"Saved new knowledge [{d['id']}], confidence {d['confidence']}%, health {d['health']['score']}%."

    def relate_knowledge(a: str, b: str) -> str:
        fa, fb = kb.find(a), kb.find(b)
        if not fa or not fb:
            return f"ERROR: couldn't find {'both' if not fa and not fb else repr(a if not fa else b)}. Use knowledge_search."
        kb.relate(fa["id"], fb["id"])
        return f"Linked {fa['title']} ↔ {fb['title']}."

    def learn_topic(topic: str, deep: bool = False) -> str:
        try:
            job = brain.learn(topic, "research" if deep else "learn", by=who)
        except ValueError as e:
            return f"ERROR: {e}"
        kind = "research session (long, many sources)" if deep else "learning session"
        return (f"Started a {kind} on “{job['topic']}” (job {job['id']}). It runs in the background; progress and the "
                "report are in Knowledge → Overview, and learning_status shows how it's going.")

    def learning_status() -> str:
        recent = jobs.list()[:6]
        lines = []
        for j in recent:
            s = j.get("summary") or {}
            last = j["log"][-1]["text"] if j["log"] else ""
            lines.append(f"- {j['id']} {j['mode']} “{j['topic']}”: {j['status']}"
                         + (f" — {s.get('new_files', 0)} new, {s.get('updated_files', 0)} updated, "
                            f"{s.get('sources_reviewed', 0)} sources" if s else f" — {last}"))
        pend = kb.pending()
        out = "Learning sessions:\n" + ("\n".join(lines) if lines else "none yet")
        if pend:
            out += "\n\nUpdates waiting for the owner's review:\n" + "\n".join(f"- {p['title']}: {p['reason']}" for p in pend)
        return out

    def knowledge_dashboard() -> str:
        d = kb.dashboard()
        cats = "\n".join(f"- {c}: {v['files']} files, {v['health']}% ({health_label(v['health'])})"
                         for c, v in d["categories"].items())
        due = "\n".join(f"- {x['title']} {x['health']}%" for x in d["needs_review_list"][:8])
        return (f"Knowledge health {d['overall_health']}% ({d['overall_label']}). {d['total_files']} files in "
                f"{d['total_categories']} categories, {d['total_sources']} sources, {d['relationships']} relationships; "
                f"{d['healthy_files']} healthy, {d['needs_review']} need review, {d['pending_reviews']} updates pending."
                + (f"\n\nBy category:\n{cats}" if cats else "") + (f"\n\nNeeds review:\n{due}" if due else ""))

    def recall_conversations(query: str = "", since_days: int = 0) -> str:
        found = cont.search_conversations(query, since_days=max(0, int(since_days or 0)), limit=8)
        if not found:
            return (f"No remembered conversations{f' about {query!r}' if query else ''}"
                    f"{f' in the last {since_days} days' if since_days else ''}. Try search_chats for raw chat text.")
        out = []
        for c in found:
            extra = "; ".join(f"{k.replace('_', ' ')}: {', '.join(c[k][:3])}" for k in ("decisions", "open_tasks", "discoveries")
                              if c.get(k))
            out.append(f"- {c['date']} “{c['title']}” ({c['topic']}, chat {c['conversation']}): {c['summary']}"
                       + (f"\n  {extra}" if extra else ""))
        return "\n".join(out)

    def project_memory(name: str = "") -> str:
        if not name.strip():
            ps = cont.projects()
            return ("Projects:\n" + "\n".join(f"- {p['name']}: {p['status'] or 'active'} (updated {p['updated']})" for p in ps)
                    if ps else "No project memory yet. update_project_memory starts one.")
        p = cont.project(name)
        if not p:
            return f"No project called '{name}'. project_memory with no name lists them."
        return f"{p['name']} — status: {p['status'] or 'active'} (updated {p['updated']})\n" + "\n".join(
            f"{k.replace('_', ' ').title()}: " + ("; ".join(p[k]) or "none") for k in
            ("goals", "open_tasks", "completed_tasks", "research", "notes", "ideas"))

    def update_project_memory(name: str, status: str = "", goals: list | None = None, open_tasks: list | None = None,
                              completed_tasks: list | None = None, research: list | None = None, notes: list | None = None,
                              ideas: list | None = None) -> str:
        p = cont.update_project(name, {"status": status, "goals": goals, "open_tasks": open_tasks,
                                       "completed_tasks": completed_tasks, "research": research, "notes": notes,
                                       "ideas": ideas})
        brain.repo.commit(f"Project memory: {p['name']}")
        return f"Project memory for {p['name']} updated ({len(p['open_tasks'])} open tasks)."

    reg.register(Tool(
        "knowledge_search",
        "Search your long-term knowledge base (validated, sourced files with confidence and health scores) and "
        "your memory of earlier conversations. Use this FIRST, before the web, whenever a question touches "
        "something you may already know. Related topics come along through the knowledge graph.",
        params(["query"], query={"type": "string"}, include_conversations={"type": "boolean"}),
        knowledge_search))
    reg.register(Tool(
        "read_knowledge",
        "Read one knowledge file in full (by id like Robotics/ServoMotors, or by title), with its sources, "
        "history and relationship paths.",
        params(["file"], file={"type": "string"}),
        read_knowledge))
    reg.register(Tool(
        "save_knowledge",
        "Save what you learned to the knowledge base, in your own words (never copied text). Give the URLs you "
        "actually read as sources. If the topic already has a file, this proposes an update (applied straight away "
        "only when confidence is high; otherwise the owner reviews it) and the old version is archived.",
        params(["title", "category", "summary"], title={"type": "string"},
               category={"type": "string", "description": "Robotics, ArtificialIntelligence, Programming, Engineering, "
                                                          "Electronics, Business, Projects, Research or Personal"},
               summary={"type": "string"}, key_points=STR_LIST, details={"type": "string"}, sources=STR_LIST,
               related={**STR_LIST, "description": "titles or ids of related knowledge files"},
               reason={"type": "string", "description": "for an update: what changed and why"}),
        save_knowledge))
    reg.register(Tool(
        "relate_knowledge",
        "Link two knowledge files as related (both ways), building the knowledge graph.",
        params(["a", "b"], a={"type": "string"}, b={"type": "string"}),
        relate_knowledge))
    reg.register(Tool(
        "learn_topic",
        "Start a background learning session: Corvis searches the web, reads trusted sources, compares them, and "
        "writes or updates knowledge files with a report. deep=true is a long research session (hundreds of sources, "
        "following related topics).",
        params(["topic"], topic={"type": "string"}, deep={"type": "boolean"}),
        learn_topic))
    reg.register(Tool(
        "learning_status",
        "How the learning and research sessions are going, and which knowledge updates wait for review.",
        params([]), learning_status))
    reg.register(Tool(
        "knowledge_dashboard",
        "The knowledge base's health: files, categories, sources, overall and per-category health, what needs review.",
        params([]), knowledge_dashboard))
    if cont is None:
        return
    reg.register(Tool(
        "recall_conversations",
        "Remember earlier conversations from their summaries (decisions, open tasks, discoveries). Use for questions "
        "like 'what did we discuss about robotics last month?' (query='robotics', since_days=31).",
        params([], query={"type": "string"}, since_days={"type": "integer"}),
        recall_conversations))
    reg.register(Tool(
        "project_memory",
        "Long-term project memory: status, goals, open and completed tasks, research, notes and ideas. "
        "No name lists the projects.",
        params([], name={"type": "string"}),
        project_memory))
    reg.register(Tool(
        "update_project_memory",
        "Update a project's long-term memory (creates it if new). Lists are added to; tasks listed in "
        "completed_tasks leave the open list.",
        params(["name"], name={"type": "string"}, status={"type": "string"}, goals=STR_LIST, open_tasks=STR_LIST,
               completed_tasks=STR_LIST, research=STR_LIST, notes=STR_LIST, ideas=STR_LIST),
        update_project_memory))
