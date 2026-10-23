"""Corvis's mind: a chosen AI model + identity + memory + workshop + whatever body he is in."""

from __future__ import annotations

import json
import time
from typing import Any, Callable

from .account import Account
from .bodies.base import Body
from .identity import Identity
from .knowledge import KnowledgeBase
from .memory import MemoryStore
from .models import ModelCatalog
from .providers import Provider, make_provider
from .workshop import Workshop

STOP_WORDS = {"stop", "halt", "freeze"}

CORE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "remember",
        "description": "Save something to your long-term memory so you still know it in future conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact, preference or event, written as a full sentence."},
                "category": {"type": "string",
                             "enum": ["user", "preference", "project", "promise", "progress", "self", "general"],
                             "description": "Use 'progress' for what the user has learned in a course."},
                "importance": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["content", "category", "importance"],
        },
    },
    {
        "name": "learn",
        "description": "Save an engineering lesson so you improve over time: a bug's cause and fix, a technique "
        "that worked, a library gotcha. Include the language/tool it applies to.",
        "input_schema": {
            "type": "object",
            "properties": {
                "lesson": {"type": "string"},
                "topic": {"type": "string", "description": "e.g. 'python', 'unity', 'react', 'ros2'"},
            },
            "required": ["lesson", "topic"],
        },
    },
    {
        "name": "recall",
        "description": "Search your long-term memory and lessons by keywords.",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
    {
        "name": "forget",
        "description": "Delete a memory by its #id (only when the user asks you to forget something).",
        "input_schema": {
            "type": "object",
            "properties": {"memory_id": {"type": "integer"}},
            "required": ["memory_id"],
        },
    },
    {
        "name": "list_courses",
        "description": "List the courses in your built-in library (programming languages, foundations, robotics).",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "open_course",
        "description": "Open a library course. Without `section` you get its outline; with a section name "
        "(e.g. 'Level 2', 'Common mistakes', 'Complete example') you get that section's text.",
        "input_schema": {
            "type": "object",
            "properties": {"course": {"type": "string", "description": "e.g. 'languages/rust' or 'robotics/arduino'"},
                           "section": {"type": "string"}},
            "required": ["course"],
        },
    },
    {
        "name": "search_knowledge",
        "description": "Search your built-in library for a topic, concept or error across all courses.",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
    {
        "name": "describe_self",
        "description": "Get your full appearance spec (forms, colors, voice, expressions).",
        "input_schema": {"type": "object", "properties": {}},
    },
]

ProviderFactory = Callable[..., Provider]


class Corvis:
    def __init__(self, identity: Identity, memory: MemoryStore, body: Body, workshop: Workshop,
                 catalog: ModelCatalog, model_id: str | None = None, effort: str = "high",
                 provider_factory: ProviderFactory = make_provider, account: Account | None = None,
                 knowledge: KnowledgeBase | None = None):
        self.identity = identity
        self.memory = memory
        self.body = body
        self.workshop = workshop
        self.catalog = catalog
        self.effort = effort
        self.provider_factory = provider_factory
        self.account = account
        self.knowledge = knowledge or KnowledgeBase()
        self.model = catalog.get(model_id or catalog.default)  # what the user picked (may be "auto")
        self.active = None                                       # the model actually thinking right now
        self.transcript: list[dict[str, str]] = []  # plain text, shared across models
        self.provider: Provider | None = None
        self._last_sync_try = 0.0

    # --- switching -------------------------------------------------------------------

    def switch_model(self, model_id: str) -> None:
        """Think with a different model (or "auto"). The conversation so far carries over as text."""
        self.model = self.catalog.get(model_id)
        self.active = None
        self.provider = None

    def set_effort(self, effort: str) -> None:
        self.effort = effort
        self.provider = None

    def transfer_to(self, body: Body) -> None:
        """Move Corvis into a different body. His identity and memory come with him."""
        self.body.shutdown()
        self.body = body
        self.provider = None

    def tools(self) -> list[dict[str, Any]]:
        return CORE_TOOLS + self.workshop.tools() + self.body.tools()

    def _start_provider(self) -> None:
        system = self.identity.system_prompt(
            self.body.describe(), MemoryStore.format(self.memory.top()), self.knowledge.ids(),
        ) + f"\n## Current model\nYou are currently thinking with {self.active.label}.\n"
        self.provider = self.provider_factory(self.active, self.effort)
        self.provider.start(system, self.tools(), self.transcript)

    # --- tools -----------------------------------------------------------------------

    def _run_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "remember":
            mid = self.memory.add(args["content"], args.get("category", "general"), args.get("importance", 3))
            return f"Stored as memory #{mid}."
        if name == "learn":
            mid = self.memory.add(f"[{args.get('topic', 'general')}] {args['lesson']}", "lesson", 4)
            return f"Lesson stored as #{mid}."
        if name == "recall":
            found = self.memory.search(args["query"])
            return MemoryStore.format(found) if found else "No matching memories."
        if name == "forget":
            return "Forgotten." if self.memory.forget(int(args["memory_id"])) else "No memory with that id."
        if name == "list_courses":
            return self.knowledge.catalog()
        if name == "open_course":
            return self.knowledge.open(args["course"], args.get("section", ""))
        if name == "search_knowledge":
            return self.knowledge.search(args["query"])
        if name == "describe_self":
            return json.dumps(self.identity.self_image, indent=2)
        if name in {t["name"] for t in self.workshop.tools()}:
            return self.workshop.execute(name, args)
        return self.body.execute(name, args)

    # --- conversation ----------------------------------------------------------------

    def chat(self, user_text: str, on_event: Callable[[str], None] = lambda e: None) -> str:
        # Safety reflex: stop words halt the body before any model is consulted.
        if user_text.strip().lower().strip(".!") in STOP_WORDS:
            self.body.emergency_stop()
            reply = "All motion halted."
            self.body.speak(reply)
            return reply

        self._choose_model(on_event)

        def run_tool(name: str, args: dict[str, Any]) -> tuple[str, bool]:
            on_event(f"{name}: {_summarize(args)}")
            try:
                return self._run_tool(name, args), False
            except Exception as e:  # report tool failures back to the model instead of crashing
                return f"Error: {e}", True

        self.body.set_expression("thinking")
        try:
            try:
                reply = self.provider.send(user_text, run_tool, on_event)
            except Exception:
                # The native history may now end mid-turn; rebuild it from the transcript next time.
                self.provider = None
                if not (self.model.provider == "auto" and self.active.provider == "home"):
                    raise
                # Auto mode: the home PC dropped off mid-reply, so carry on with this device's model.
                on_event("home PC unreachable — switching to this device")
                self.catalog.home = []
                self.catalog._home_checked = time.time()
                self._choose_model(on_event)
                reply = self.provider.send(user_text, run_tool, on_event)
        finally:
            self.body.set_expression("idle")
        self.transcript += [{"role": "user", "text": user_text}, {"role": "assistant", "text": reply}]
        self.body.speak(reply)
        self.sync(on_event)
        return reply

    def _choose_model(self, on_event: Callable[[str], None]) -> None:
        target = self.catalog.resolve_auto() if self.model.provider == "auto" else self.model
        if self.active is None or target.id != self.active.id:
            if self.model.provider == "auto":
                on_event(f"thinking on {target.label}")
            self.active = target
            self.provider = None
        if self.provider is None:
            self._start_provider()

    def sync(self, on_event: Callable[[str], None] = lambda e: None, force: bool = False) -> int | None:
        """Share memories with the user's other devices through the home PC, when it's reachable."""
        acct = self.account
        if acct is None or not acct.signed_in:
            return None
        # When the hub looked offline, only retry once a minute so offline chats stay fast.
        if not (force or acct.hub_online or time.time() - self._last_sync_try > 60):
            return None
        self._last_sync_try = time.time()
        got = acct.try_sync(self.memory)
        if got:
            on_event(f"synced {got} memories from your other devices")
        return got


def _summarize(args: dict[str, Any]) -> str:
    shown = {k: (v if not isinstance(v, str) or len(v) < 80 else v[:77] + "...") for k, v in args.items()
             if k not in {"content", "new_text", "old_text"}}
    return json.dumps(shown)
