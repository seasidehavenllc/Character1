"""A Body is anything Corvis can inhabit: a terminal, a 3D avatar, a robot.

The brain never talks to hardware directly. It asks the current body which tools
it offers, calls them, and reads back what actually happened.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Body(ABC):
    name: str = "body"

    @abstractmethod
    def describe(self) -> str:
        """Plain-language description of this body and its abilities, for the system prompt."""

    def tools(self) -> list[dict[str, Any]]:
        """Claude tool definitions this body exposes. Default: none."""
        return []

    def execute(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        raise KeyError(f"{self.name} has no tool {tool_name!r}")

    def speak(self, text: str) -> None:
        """Deliver Corvis's words through this body (print, TTS, speaker...)."""
        print(f"\nCorvis: {text}\n")

    def set_expression(self, expression: str) -> None:
        """Show an expression from identity.self_image.expressions, if the body can."""

    def emergency_stop(self) -> None:
        """Halt all motion immediately. Must be safe to call at any time."""

    def shutdown(self) -> None:
        self.emergency_stop()
