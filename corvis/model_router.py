"""Provider-neutral model selection with explicit fallback and no hidden credential sharing.

All configured endpoints use the OpenAI-compatible ChatLLM contract. Native provider
adapters can be added separately when a provider's API differs.
"""
from __future__ import annotations
from .llm import ChatLLM, LLMError, Reply

class ModelRouter:
    def __init__(self, primary: ChatLLM, alternatives: list[ChatLLM] | None = None):
        self.models = [primary, *(alternatives or [])]
        self.last_model = primary.model

    def chat(self, messages: list[dict], tools: list[dict] | None = None) -> Reply:
        errors = []
        for client in self.models:
            try:
                result = client.chat(messages, tools)
                self.last_model = client.model
                return result
            except LLMError as exc:
                errors.append(f"{client.model}: {exc}")
        raise LLMError("All configured Corvis models failed. " + " | ".join(errors))

    @property
    def model(self) -> str:
        return self.last_model

    @property
    def native_tools(self) -> bool:
        # One tool-calling style for the whole conversation: the primary model's.
        return self.models[0].native_tools
