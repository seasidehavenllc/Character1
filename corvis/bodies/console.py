from __future__ import annotations

from .base import Body


class ConsoleBody(Body):
    name = "console"

    def describe(self) -> str:
        return (
            "You are running as a voice in a text terminal. You have no physical body right "
            "now, so you cannot move or see. You can still think, talk, remember and describe "
            "how you would look."
        )
