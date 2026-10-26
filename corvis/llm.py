"""Local LLM client.

Talks to any OpenAI-compatible server running on your PC:
Ollama, llama.cpp (llama-server), LM Studio, vLLM. No cloud.

Supports native tool calling, plus a text fallback for models that write
tool calls as <tool_call>{...}</tool_call> in plain text instead.
"""
from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

import requests


class LLMError(RuntimeError):
    pass


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict


@dataclass
class Reply:
    content: str
    tool_calls: list[ToolCall] = field(default_factory=list)

    def as_message(self) -> dict:
        """Format this reply as an assistant message for the history."""
        msg: dict = {"role": "assistant", "content": self.content or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": c.id,
                    "type": "function",
                    "function": {"name": c.name, "arguments": json.dumps(c.args)},
                }
                for c in self.tool_calls
            ]
        return msg


def _new_id() -> str:
    return "call_" + uuid.uuid4().hex[:12]


_TEXT_CALL = re.compile(r"<tool_call>\s*(.*?)\s*</tool_call>", re.DOTALL)
_EMPTY_FENCE = re.compile(r"```[\w-]*\s*```")


def _as_call(obj, known: set[str] | None) -> ToolCall | None:
    """Turn {"name": ..., "arguments": {...}} (or common variants) into a ToolCall."""
    if not isinstance(obj, dict):
        return None
    fn = obj["function"] if isinstance(obj.get("function"), dict) else obj
    name = fn.get("name") or obj.get("tool") or obj.get("tool_name")
    if not isinstance(name, str) or (known is not None and name not in known):
        return None
    args = fn.get("arguments", fn.get("parameters", fn.get("args", fn.get("input", {}))))
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except json.JSONDecodeError:
            args = {}
    return ToolCall(_new_id(), name, args if isinstance(args, dict) else {})


def parse_text_tool_calls(text: str, known: set[str] | None = None) -> tuple[str, list[ToolCall]]:
    """Pull tool calls out of plain text, for models that write them instead of calling them.

    Handles <tool_call>{...}</tool_call>, ```json fenced``` calls, and bare JSON objects (or
    lists) like {"name": "pc_make_folder", "arguments": {...}}. Bare JSON only counts when
    `name` is one of Corvis's real tools, so ordinary JSON in an answer is left alone.
    """
    calls: list[ToolCall] = []
    spans: list[tuple[int, int]] = []
    decoder = json.JSONDecoder()

    for m in _TEXT_CALL.finditer(text):
        try:
            obj = json.loads(m.group(1))
        except json.JSONDecodeError:
            continue
        found = [c for c in (_as_call(o, None) for o in (obj if isinstance(obj, list) else [obj])) if c]
        if found:
            calls += found
            spans.append(m.span())

    if not calls and known:
        i = 0
        while i < len(text):
            if text[i] not in "{[":
                i += 1
                continue
            try:
                obj, end = decoder.raw_decode(text, i)
            except json.JSONDecodeError:
                i += 1
                continue
            items = obj if isinstance(obj, list) else [obj]
            found = [_as_call(o, known) for o in items]
            if items and all(found):
                calls += found  # type: ignore[arg-type]
                spans.append((i, end))
                i = end
            else:
                i += 1

    for a, b in reversed(spans):
        text = text[:a] + text[b:]
    if spans:
        text = _EMPTY_FENCE.sub("", text).strip()
    return text, calls


class ChatLLM:
    def __init__(
        self,
        base_url: str = "http://localhost:11434/v1",
        model: str = "qwen3-coder:30b",
        api_key: str = "local",
        temperature: float = 0.2,
        max_tokens: int = 8192,
        timeout: int = 900,
        native_tools: bool = True,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.native_tools = native_tools

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Reply:
        payload: dict = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
        }
        if tools and self.native_tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"
        try:
            r = requests.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=self.timeout,
            )
        except requests.RequestException as e:
            local = any(h in self.base_url for h in ("127.0.0.1", "localhost", "0.0.0.0"))
            hint = "Is Ollama / llama-server running?" if local else "Check this server's internet connection."
            raise LLMError(f"Could not reach the model server at {self.base_url}. {hint} ({e})") from e
        if r.status_code != 200:
            raise LLMError(f"Model server returned {r.status_code}: {r.text[:500]}")

        msg = r.json()["choices"][0]["message"]
        content = msg.get("content") or ""
        calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            fn = tc.get("function", {})
            args = fn.get("arguments") or "{}"
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {"_raw": args}
            calls.append(ToolCall(tc.get("id") or _new_id(), fn.get("name", ""), args))
        if not calls:
            known = {t["function"]["name"] for t in tools} if tools else None
            content, calls = parse_text_tool_calls(content, known)
        return Reply(content, calls)
