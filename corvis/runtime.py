"""Shared helpers for the terminal and web front ends."""

from __future__ import annotations

from .bodies import AvatarBody, ConsoleBody, RobotBody, Ros2Driver, SimulatedDriver
from .identity import Identity

EFFORTS = ["low", "medium", "high", "xhigh", "max"]


def make_body(kind: str, identity: Identity, ros2: bool = False):
    if kind == "avatar":
        return AvatarBody(identity)
    if kind == "robot":
        return RobotBody(Ros2Driver() if ros2 else SimulatedDriver())
    if kind == "console":
        return ConsoleBody()
    raise ValueError(f"Unknown body {kind!r} (console, avatar, robot)")


def describe_api_error(e: Exception) -> str | None:
    """Turn common SDK errors into a friendly line; None if it's not an API error."""
    name = type(e).__name__
    text = str(e)
    if "Could not resolve authentication method" in text:
        return "No Anthropic API key found. Set ANTHROPIC_API_KEY, then restart Corvis."
    if "Missing credentials" in text and "OPENAI_API_KEY" in text:
        return "No OpenAI API key found. Set OPENAI_API_KEY, then restart Corvis."
    if name == "AuthenticationError":
        return "Missing or invalid API key for this model (set ANTHROPIC_API_KEY or OPENAI_API_KEY)."
    if name == "RateLimitError":
        return "Rate limited by the model provider. Wait a moment and try again."
    if name == "APIConnectionError":
        return "Can't reach the model provider. Check your internet connection."
    if name == "NotFoundError":
        return "That model ID wasn't found. Check config/models.yaml."
    if hasattr(e, "status_code"):
        return f"API error {e.status_code}: {getattr(e, 'message', e)}"
    return None
