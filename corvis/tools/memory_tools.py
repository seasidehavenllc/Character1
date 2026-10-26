"""Memory tools: search past chats, open one, and remember/forget facts about the owner."""
from __future__ import annotations

from ..memory import Memory, fmt_date
from .base import Tool, ToolContext, ToolRegistry, params


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    memory: Memory | None = ctx.state.get("memory")
    if memory is None:
        return

    def search_chats(query: str = "", limit: int = 6) -> str:
        exclude = ctx.state.get("conversation_id")
        if not query.strip():
            recent = memory.chats.recent(limit=max(1, min(limit, 20)), exclude=exclude)
            if not recent:
                return "There are no other saved chats yet."
            return "Recent chats:\n" + "\n".join(
                f"- {c['title']} ({fmt_date(c.get('updated') or 0)}, chat {c['id']})" for c in recent)
        hits = memory.chats.search(query, limit=max(1, min(limit, 15)), exclude=exclude)
        if not hits:
            return f"No earlier chats mention '{query}'. Try other words, or leave query empty to list recent chats."
        return "\n".join(
            f"{i}. \"{h['title']}\" ({h['date']}, chat {h['chat_id']})\n   {h['who']}: {h['snippet']}"
            + (f"\n   Corvis replied: {h['reply']}" if h["reply"] else "")
            for i, h in enumerate(hits, 1))

    def read_chat(chat_id: str, start: int = 0) -> str:
        try:
            return memory.chats.read(chat_id.strip(), start=max(0, int(start)))
        except KeyError:
            return f"ERROR: no saved chat with id '{chat_id}'. Use search_chats to find the id."

    bot = ctx.state.get("bot") or {}

    def remember(fact: str, about_owner: bool | None = None) -> str:
        # The lead's facts are shared. Other bots keep what they learn in their own memory,
        # unless it's about the owner (then every bot should know it).
        shared = bot.get("lead", True) if about_owner is None else bool(about_owner)
        saved, created = memory.facts.add(fact, bot=None if shared else bot.get("id"))
        if created:
            emit = ctx.state.get("emit")
            if emit:
                emit("memory", saved["text"], bot=None if shared else bot.get("id"),
                     bot_name="everyone" if shared else bot.get("name"))
        return (f"Saved to long-term memory as [{saved['id']}]: {saved['text']}" if created
                else f"Already remembered as [{saved['id']}].")

    def forget(memory_id: str) -> str:
        removed = memory.facts.remove(memory_id)
        if removed:
            return f"Forgot [{removed['id']}]: {removed['text']}"
        return f"ERROR: nothing in memory matches '{memory_id}'. Use the id shown in brackets, like m3."

    reg.register(Tool(
        "search_chats",
        "Search every earlier chat with the owner (ranked by relevance). Use it when the owner "
        "refers to something from before, or when past decisions, code or preferences could help. "
        "Leave query empty to list recent chats.",
        params([], query={"type": "string"}, limit={"type": "integer"}),
        search_chats))
    reg.register(Tool(
        "read_chat",
        "Read an earlier chat in full, by its chat id (from search_chats or a recalled note).",
        params(["chat_id"], chat_id={"type": "string"}, start={"type": "integer"}),
        read_chat))
    reg.register(Tool(
        "remember",
        "Save a lasting fact to long-term memory: about the owner (name, projects and where they "
        "live, preferred tools, style, routines), or something you learned doing your job "
        "(who approves what, how a customer likes to work, what worked last time). One short fact "
        "per call. Set about_owner=true for facts about the owner that every bot should know. "
        "Never save passwords, keys or other secrets.",
        params(["fact"], fact={"type": "string"}, about_owner={"type": "boolean"}),
        remember))
    experiences = ctx.state.get("experiences")
    beliefs = ctx.state.get("beliefs")

    def record_experience(goal: str, outcome: str, lesson: str = "", verified: bool = False) -> str:
        item = experiences.record(goal.strip(), outcome.strip(), lesson=lesson.strip(),
                                  verified=bool(verified), source=bot.get("name") or "Corvis")
        return (f"Recorded experience {item['id'][:8]} ({'verified' if item['verified'] else 'not verified'}). "
                "It will be recalled on similar tasks.")

    def note_belief(claim: str, confidence: float = 0.5, evidence: str = "", source: str = "") -> str:
        ev = [{"summary": evidence.strip(), "source": source.strip() or "unspecified"}] if evidence.strip() else []
        item = beliefs.add(claim, confidence=confidence, evidence=ev, source=source.strip() or "reasoning")
        return f"Noted belief {item['id'][:8]} at confidence {item['confidence']:.2f}: {item['claim']}"

    def revise_belief(belief_id: str, reason: str, claim: str = "", confidence: float | None = None) -> str:
        matches = [b for b in beliefs.search(limit=10_000) if b["id"].startswith(belief_id.strip())]
        if len(matches) != 1:
            return f"ERROR: no single belief matches id '{belief_id}'. Use the id shown in the belief context."
        item = beliefs.revise(matches[0]["id"], claim.strip() or None, confidence=confidence, reason=reason)
        return f"Revised belief {item['id'][:8]}: {item['claim']} (confidence {item['confidence']:.2f})"

    if experiences is not None:
        reg.register(Tool(
            "record_experience",
            "After finishing a task, record what happened so you do better next time: the goal, the "
            "actual outcome, and the lesson (what caused a bug, what fixed it, what to do differently). "
            "Set verified=true only if you checked the result yourself (tests passed, program ran, the "
            "owner confirmed). Don't record trivial tasks.",
            params(["goal", "outcome"], goal={"type": "string"}, outcome={"type": "string"},
                   lesson={"type": "string"}, verified={"type": "boolean"}),
            record_experience))
    if beliefs is not None:
        reg.register(Tool(
            "note_belief",
            "Record a claim you now hold about the owner's projects or tools, with your confidence (0-1) "
            "and the evidence behind it, e.g. 'This project's tests need Python 3.11' (0.9, from CI "
            "config). Only claims with real evidence; never guesses or secrets.",
            params(["claim"], claim={"type": "string"}, confidence={"type": "number"},
                   evidence={"type": "string"}, source={"type": "string"}),
            note_belief))
        reg.register(Tool(
            "revise_belief",
            "Change or lower confidence in a recorded belief when new evidence contradicts it. "
            "Use the id from the belief context; explain the reason.",
            params(["belief_id", "reason"], belief_id={"type": "string"}, reason={"type": "string"},
                   claim={"type": "string"}, confidence={"type": "number"}),
            revise_belief))
    reg.register(Tool(
        "forget",
        "Remove a fact from long-term memory by its id (like m3), when it's wrong or the owner asks.",
        params(["memory_id"], memory_id={"type": "string"}),
        forget))
