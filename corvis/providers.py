"""Model providers: the same Corvis can think with Claude or ChatGPT.

Each provider runs one conversation turn, including the tool-calling loop, and keeps
its own native message history. When you switch models, Corvis starts the new provider
from the plain-text transcript of the conversation so far.
"""

from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Any, Callable

from .models import ModelConfig

# run_tool(name, input) -> (result_text, is_error)
ToolRunner = Callable[[str, dict[str, Any]], tuple[str, bool]]
EventSink = Callable[[str], None]


class Provider(ABC):
    def __init__(self, model: ModelConfig, effort: str = "high"):
        self.model = model
        self.effort = effort

    @abstractmethod
    def start(self, system: str, tools: list[dict[str, Any]], transcript: list[dict[str, str]]) -> None:
        """Begin a fresh native conversation from a plain-text transcript."""

    @abstractmethod
    def send(self, user_text: str, run_tool: ToolRunner, on_event: EventSink) -> str:
        """Run one turn (with tool calls) and return Corvis's final reply text."""


class AnthropicProvider(Provider):
    def __init__(self, model: ModelConfig, effort: str = "high", client: Any = None):
        super().__init__(model, effort)
        if client is None:
            import anthropic

            client = anthropic.Anthropic()
        self.client = client

    def start(self, system, tools, transcript):
        # The system prompt and tool list stay fixed for the whole conversation: changing
        # them mid-conversation would invalidate the model's earlier reasoning.
        self.system = system
        self.tools = list(tools)
        if self.model.web_tools:
            self.tools += [
                {"type": "web_search_20260209", "name": "web_search"},
                {"type": "web_fetch_20260209", "name": "web_fetch"},
            ]
        self.messages: list[dict[str, Any]] = [{"role": t["role"], "content": t["text"]} for t in transcript]

    def send(self, user_text, run_tool, on_event):
        self.messages.append({"role": "user", "content": user_text})
        extra: dict[str, Any] = {}
        if self.model.fallbacks:
            extra = {"betas": ["server-side-fallback-2026-07-01"], "fallbacks": "default"}

        while True:
            with self.client.beta.messages.stream(
                model=self.model.id,
                max_tokens=64000,
                system=self.system,
                tools=self.tools,
                messages=self.messages,
                thinking={"type": "adaptive"},
                output_config={"effort": self.effort},
                **extra,
            ) as stream:
                response = stream.get_final_message()
            # Keep the full content (thinking blocks included) so the history stays valid.
            self.messages.append({"role": "assistant", "content": response.content})

            if response.stop_reason == "refusal":
                return "I'm afraid I can't help with that one."
            if response.stop_reason == "pause_turn":  # a long web search paused; let it continue
                continue
            for block in response.content:
                if block.type == "server_tool_use":
                    on_event(f"{block.name}: {json.dumps(block.input)[:120]}")
            if response.stop_reason != "tool_use":
                text = "".join(b.text for b in response.content if b.type == "text").strip()
                if response.stop_reason == "max_tokens":
                    text += "\n\n[Reply cut off at the length limit — ask me to continue.]"
                return text

            results = []
            for block in response.content:
                if block.type == "tool_use":
                    out, is_error = run_tool(block.name, block.input)
                    result = {"type": "tool_result", "tool_use_id": block.id, "content": out}
                    if is_error:
                        result["is_error"] = True
                    results.append(result)
            self.messages.append({"role": "user", "content": results})


class OpenAIProvider(Provider):
    EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}

    def __init__(self, model: ModelConfig, effort: str = "high", client: Any = None):
        super().__init__(model, effort)
        if client is None:
            try:
                import openai
            except ImportError as e:
                raise RuntimeError("ChatGPT models need the OpenAI SDK: pip install openai") from e
            client = openai.OpenAI()
        self.client = client

    def start(self, system, tools, transcript):
        self.tools = [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in tools
        ]
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        self.messages += [{"role": t["role"], "content": t["text"]} for t in transcript]

    def send(self, user_text, run_tool, on_event):
        self.messages.append({"role": "user", "content": user_text})
        while True:
            response = self.client.chat.completions.create(
                model=self.model.id,
                messages=self.messages,
                tools=self.tools,
                reasoning_effort=self.EFFORT.get(self.effort, "medium"),
            )
            msg = response.choices[0].message
            calls = msg.tool_calls or []
            entry: dict[str, Any] = {"role": "assistant", "content": msg.content or ""}
            if calls:
                entry["tool_calls"] = [
                    {"id": c.id, "type": "function",
                     "function": {"name": c.function.name, "arguments": c.function.arguments}}
                    for c in calls
                ]
            self.messages.append(entry)
            if not calls:
                return (msg.content or msg.refusal or "").strip()
            for c in calls:
                try:
                    args = json.loads(c.function.arguments or "{}")
                    out, _ = run_tool(c.function.name, args)
                except json.JSONDecodeError:
                    out = "Error: tool arguments were not valid JSON."
                self.messages.append({"role": "tool", "tool_call_id": c.id, "content": out})


def make_provider(model: ModelConfig, effort: str = "high") -> Provider:
    if model.provider == "anthropic":
        return AnthropicProvider(model, effort)
    if model.provider == "openai":
        return OpenAIProvider(model, effort)
    raise ValueError(f"Unknown provider {model.provider!r} for model {model.id}")
