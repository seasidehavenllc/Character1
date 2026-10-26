"""The coding agent loop: think -> call tools -> read results -> repeat until done."""
from __future__ import annotations

from typing import Callable

from .llm import ChatLLM, LLMError
from .tools.base import ToolRegistry

Event = Callable[[str, str], None]  # (kind, text)


def _default_event(kind: str, text: str) -> None:
    print(f"[{kind}] {text}")


class CodingAgent:
    def __init__(
        self,
        llm: ChatLLM,
        registry: ToolRegistry,
        system_prompt: str,
        max_steps: int = 60,
        max_context_chars: int = 200_000,
        on_event: Event = _default_event,
        context_provider: Callable[[], str] | None = None,
        recall_provider: Callable[[str], tuple[str, list[str]]] | None = None,
    ):
        self.llm = llm
        self.registry = registry
        self.max_steps = max_steps
        self.max_context_chars = max_context_chars
        self.on_event = on_event
        self.base_system = system_prompt
        self.context_provider = context_provider   # e.g. long-term memory, refreshed every task
        self.recall_provider = recall_provider     # e.g. snippets from earlier chats
        self.messages: list[dict] = [{"role": "system", "content": system_prompt}]

    # --- context management -------------------------------------------------
    def _size(self) -> int:
        return sum(len(str(m.get("content") or "")) for m in self.messages)

    def _compact(self) -> None:
        """Shrink old tool outputs when the conversation gets too long.

        Recent messages stay intact; older file dumps and logs become stubs.
        The model can always re-read a file if it needs it again.
        """
        if self._size() <= self.max_context_chars:
            return
        protected = len(self.messages) - 8
        for m in self.messages[1:protected]:
            if m["role"] == "tool" and len(m["content"]) > 300:
                m["content"] = m["content"][:200] + "\n[older output trimmed to save context; re-run the tool if needed]"
                if self._size() <= self.max_context_chars * 0.7:
                    return

    # --- main loop ----------------------------------------------------------
    def run(self, task: str, should_stop: Callable[[], bool] = lambda: False, extra: str = "") -> str:
        """Work on a task until done. should_stop is checked between steps (used by Stop buttons)."""
        self.should_stop = should_stop  # teammates this bot loops in stop when it does
        self._refresh_system()
        content = task
        if self.recall_provider and task.strip():
            try:
                block, titles = self.recall_provider(task)
            except Exception as e:  # memory trouble must never block work
                block, titles = "", []
                self.on_event("error", f"Couldn't search earlier chats: {e}")
            if block:
                content = task + block
                self.on_event("recall", "; ".join(titles) + "\n" + block.strip())
        content += extra  # e.g. attached files
        self.messages.append({"role": "user", "content": content})
        repeat_guard: dict[str, int] = {}

        for step in range(1, self.max_steps + 1):
            if should_stop():
                return self._stopped()
            self._compact()
            try:
                reply = self.llm.chat(self.messages, self.registry.schemas())
            except LLMError as e:
                self.on_event("error", str(e))
                return f"Stopped: {e}"

            self.messages.append(reply.as_message())
            if reply.content and reply.tool_calls:
                self.on_event("thinking", reply.content)

            if not reply.tool_calls:
                self.on_event("done", reply.content)
                return reply.content

            for i, call in enumerate(reply.tool_calls):
                if should_stop():
                    # Every tool call needs an answer or the history becomes invalid.
                    for skipped in reply.tool_calls[i:]:
                        self.messages.append({"role": "tool", "tool_call_id": skipped.id,
                                              "content": "Cancelled: the owner pressed stop."})
                    return self._stopped()

                key = f"{call.name}:{sorted(call.args.items())!r}"
                repeat_guard[key] = repeat_guard.get(key, 0) + 1
                self.on_event("tool", f"{call.name} {_short(call.args)}")

                if repeat_guard[key] > 3:
                    result = ("ERROR: you have made this exact call several times with the same "
                              "result. Change approach: re-read the relevant code or try something else.")
                else:
                    result = self.registry.run(call.name, call.args)

                self.on_event("result", result[:4000])
                self.messages.append({"role": "tool", "tool_call_id": call.id, "content": result})

        msg = f"Stopped after {self.max_steps} steps without finishing. Say 'continue' to keep going."
        self.on_event("error", msg)
        return msg

    def _refresh_system(self) -> None:
        extra = ""
        if self.context_provider:
            try:
                extra = self.context_provider() or ""
            except Exception:
                extra = ""
        self.messages[0] = {"role": "system", "content": self.base_system + extra}

    def _stopped(self) -> str:
        msg = "Stopped. Tell me how you'd like to continue."
        self.messages.append({"role": "assistant", "content": msg})
        self.on_event("stopped", msg)
        return msg


def _short(args: dict, limit: int = 120) -> str:
    parts = []
    for k, v in args.items():
        s = str(v).replace("\n", "\\n")
        parts.append(f"{k}={s[:60] + '…' if len(s) > 60 else s}")
    text = ", ".join(parts)
    return text[:limit]


def _first_line(text: str) -> str:
    line = text.strip().splitlines()[0] if text.strip() else "(empty)"
    return line[:160]
