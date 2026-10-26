"""Model providers: the same Corvis can think with a local model, Claude or ChatGPT.

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
    def send(self, user_text: str, run_tool: ToolRunner, on_event: EventSink,
             images: list[tuple[str, str]] | None = None) -> str:
        """Run one turn (with tool calls) and return Corvis's final reply text.
        `images` are (media type, base64 data) pairs attached to the user's message."""


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

    def send(self, user_text, run_tool, on_event, images=None):
        content: Any = user_text
        if images:
            content = [{"type": "image", "source": {"type": "base64", "media_type": mt, "data": data}}
                       for mt, data in images] + [{"type": "text", "text": user_text}]
        self.messages.append({"role": "user", "content": content})
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


def parse_text_tool_calls(text: str, tool_names: set[str]) -> list[tuple[str, dict[str, Any]]]:
    """Find tool calls a local model wrote as plain JSON text instead of real tool calls.

    Small open models often answer with e.g. {"name": "write_file", "arguments": {...}},
    sometimes inside ```json fences or <tool_call> tags. Only names of real tools count.
    """
    calls, decoder, i = [], json.JSONDecoder(), 0
    while (i := text.find("{", i)) != -1:
        try:
            obj, end = decoder.raw_decode(text, i)
        except ValueError:
            i += 1
            continue
        if isinstance(obj, dict) and obj.get("name") in tool_names:
            args = obj.get("arguments", obj.get("parameters", {}))
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except ValueError:
                    args = None
            if isinstance(args, dict):
                calls.append((obj["name"], args))
        i = end
    return calls


class OpenAIProvider(Provider):
    """ChatGPT in the cloud, or any model server that speaks the same API:
    Ollama / LM Studio on this device ("local"), or the user's home PC hub ("home")."""

    EFFORT = {"low": "low", "medium": "medium", "high": "high", "xhigh": "high", "max": "high"}

    def __init__(self, model: ModelConfig, effort: str = "high", client: Any = None):
        super().__init__(model, effort)
        if client is None:
            import openai

            if model.provider in ("local", "home"):
                # CPU-only devices can be slow, so allow long replies.
                client = openai.OpenAI(base_url=model.base_url, api_key=model.api_key or "local", timeout=900)
            else:
                client = openai.OpenAI()
        self.client = client

    def start(self, system, tools, transcript):
        self.tool_names = {t["name"] for t in tools}
        self.tools = [
            {"type": "function",
             "function": {"name": t["name"], "description": t["description"], "parameters": t["input_schema"]}}
            for t in tools
        ]
        self.messages: list[dict[str, Any]] = [{"role": "system", "content": system}]
        self.messages += [{"role": t["role"], "content": t["text"]} for t in transcript]

    def send(self, user_text, run_tool, on_event, images=None):
        content: Any = user_text
        if images:
            content = [{"type": "text", "text": user_text}] + [
                {"type": "image_url", "image_url": {"url": f"data:{mt};base64,{data}"}} for mt, data in images]
        self.messages.append({"role": "user", "content": content})
        turn = 0
        while True:
            turn += 1
            extra = {}
            if self.model.provider == "openai":
                extra["reasoning_effort"] = self.EFFORT.get(self.effort, "medium")
            response = self.client.chat.completions.create(
                model=self.model.api_model or self.model.id, messages=self.messages, tools=self.tools, **extra,
            )
            msg = response.choices[0].message
            content = msg.content or ""
            # (call id, tool name, arguments as a JSON string)
            calls = [(c.id, c.function.name, c.function.arguments or "{}") for c in (msg.tool_calls or [])]
            if not calls and self.model.provider != "openai":
                calls = [(f"text_call_{turn}_{n}", name, json.dumps(args))
                         for n, (name, args) in enumerate(parse_text_tool_calls(content, self.tool_names))]
                if calls:
                    content = ""  # the text was the tool calls themselves
            entry: dict[str, Any] = {"role": "assistant", "content": content}
            if calls:
                entry["tool_calls"] = [{"id": cid, "type": "function", "function": {"name": name, "arguments": args}}
                                       for cid, name, args in calls]
            self.messages.append(entry)
            if not calls:
                return (content or msg.refusal or "").strip()
            for cid, name, args in calls:
                try:
                    out, _ = run_tool(name, json.loads(args))
                except json.JSONDecodeError:
                    out = "Error: tool arguments were not valid JSON."
                self.messages.append({"role": "tool", "tool_call_id": cid, "content": out})


def make_provider(model: ModelConfig, effort: str = "high") -> Provider:
    if model.provider == "anthropic":
        return AnthropicProvider(model, effort)
    if model.provider in ("openai", "local", "home"):
        return OpenAIProvider(model, effort)
    raise ValueError(f"Unknown provider {model.provider!r} for model {model.id}")
