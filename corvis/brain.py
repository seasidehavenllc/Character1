"""Corvis's mind: Claude + identity + memory + whatever body he is currently in."""

from __future__ import annotations

import json
from typing import Any

import anthropic

from .bodies.base import Body
from .identity import Identity
from .memory import MemoryStore

MODEL = "claude-opus-5-5"
STOP_WORDS = {"stop", "halt", "freeze"}

CORE_TOOLS: list[dict[str, Any]] = [
    {
        "name": "remember",
        "description": "Save something to your long-term memory so you still know it in future conversations.",
        "input_schema": {
            "type": "object",
            "properties": {
                "content": {"type": "string", "description": "The fact, preference or event, written as a full sentence."},
                "category": {"type": "string", "enum": ["user", "preference", "project", "promise", "self", "general"]},
                "importance": {"type": "integer", "minimum": 1, "maximum": 5},
            },
            "required": ["content", "category", "importance"],
        },
    },
    {
        "name": "recall",
        "description": "Search your long-term memory by keywords.",
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
        "name": "describe_self",
        "description": "Get your full appearance spec (forms, colors, voice, expressions).",
        "input_schema": {"type": "object", "properties": {}},
    },
]


class Corvis:
    def __init__(self, identity: Identity, memory: MemoryStore, body: Body,
                 client: anthropic.Anthropic | None = None, effort: str = "medium"):
        self.identity = identity
        self.memory = memory
        self.body = body
        self.client = client or anthropic.Anthropic()
        self.effort = effort
        self.messages: list[dict[str, Any]] = []

    def transfer_to(self, body: Body) -> None:
        """Move Corvis into a different body. His identity and memory come with him."""
        self.body.shutdown()
        self.body = body
        # The system prompt changes with the body, so start a fresh short-term context.
        self.messages = []

    def _system(self) -> str:
        return self.identity.system_prompt(self.body.describe(), MemoryStore.format(self.memory.top()))

    def _run_tool(self, name: str, args: dict[str, Any]) -> str:
        if name == "remember":
            mid = self.memory.add(args["content"], args.get("category", "general"), args.get("importance", 3))
            return f"Stored as memory #{mid}."
        if name == "recall":
            found = self.memory.search(args["query"])
            return MemoryStore.format(found) if found else "No matching memories."
        if name == "forget":
            return "Forgotten." if self.memory.forget(int(args["memory_id"])) else "No memory with that id."
        if name == "describe_self":
            return json.dumps(self.identity.self_image, indent=2)
        return self.body.execute(name, args)

    def chat(self, user_text: str) -> str:
        # Safety reflex: stop words halt the body before the model is even consulted.
        if user_text.strip().lower().strip(".!") in STOP_WORDS:
            self.body.emergency_stop()
            reply = "All motion halted."
            self.body.speak(reply)
            return reply

        self.messages.append({"role": "user", "content": user_text})
        tools = CORE_TOOLS + self.body.tools()
        self.body.set_expression("thinking")

        while True:
            response = self.client.beta.messages.create(
                model=MODEL,
                max_tokens=16000,
                system=self._system(),
                tools=tools,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                betas=["server-side-fallback-2026-07-01"],
                fallbacks="default",
            )
            # Keep the full content (incl. thinking blocks) so the conversation stays valid.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                reply = "I'm afraid I can't help with that one, sir."
                break
            if response.stop_reason == "pause_turn":
                continue
            if response.stop_reason != "tool_use":
                reply = "".join(b.text for b in response.content if b.type == "text").strip()
                break

            results = []
            for block in response.content:
                if block.type != "tool_use":
                    continue
                try:
                    out = self._run_tool(block.name, block.input)
                    results.append({"type": "tool_result", "tool_use_id": block.id, "content": out})
                except Exception as e:  # report tool failures back to Corvis instead of crashing
                    results.append({"type": "tool_result", "tool_use_id": block.id,
                                    "content": f"Error: {e}", "is_error": True})
            self.messages.append({"role": "user", "content": results})

        self.body.set_expression("idle")
        self.body.speak(reply)
        return reply
