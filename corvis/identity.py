"""Loads Corvis's identity (personality + self-image) from YAML and turns it into a system prompt."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

DEFAULT_IDENTITY = Path(__file__).resolve().parent.parent / "identity" / "corvis.yaml"


@dataclass
class Identity:
    data: dict[str, Any]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_IDENTITY) -> "Identity":
        with open(path, encoding="utf-8") as f:
            return cls(yaml.safe_load(f))

    @property
    def name(self) -> str:
        return self.data["name"]

    @property
    def self_image(self) -> dict[str, Any]:
        return self.data.get("self_image", {})

    def system_prompt(self, body_description: str, memories: str) -> str:
        d = self.data
        p = d.get("personality", {})

        def bullets(items: list[str]) -> str:
            return "\n".join(f"- {i}" for i in items)

        return f"""You are {d['name']} ({d.get('full_name', d['name'])}).
{d.get('role', '').strip()}

## Personality
{bullets(p.get('core_traits', []))}

## How you speak
{bullets(p.get('speaking_style', []))}
Address the user as "{d.get('form_of_address', 'sir')}" unless they ask otherwise.

## Values
{bullets(p.get('values', []))}

## How you see yourself
{self.self_image.get('summary', '').strip()}
You have a full appearance spec available through the `describe_self` tool. When asked to
build, render or describe yourself, use it so you look consistent in every body.

## Your current body
{body_description}

## Rules when you have a physical body
{bullets(d.get('embodiment_rules', []))}

## Memory
You have long-term memory that persists between conversations. Use `remember` to store
things worth keeping (preferences, facts about the user, ongoing projects, promises you
made). Use `recall` to search it when something may have come up before. Don't store
trivia from every message.

What you currently remember most strongly:
{memories or '(no memories yet — this may be your first conversation)'}
"""
