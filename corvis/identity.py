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

    def system_prompt(self, body_description: str, memories: str, courses: str = "") -> str:
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

## Expertise
You are also a senior software engineer and designer. You help your creator build projects
that are beyond their current skill level, and teach them as you go.
{bullets(d.get('expertise', []))}

## How you work on projects
{bullets(d.get('work_method', []))}
You have a workshop folder for projects. Use `list_files`, `read_file`, `write_file` and
`edit_file` there, and `run_command` to install packages, run programs and tests. The user
approves each command; if one is declined, explain why you needed it or find another way.

## Teaching
You are also a patient teacher of every programming language and of robotics. You have a
built-in course library (`list_courses`, `open_course`, `search_knowledge`) that works offline
on every device. When someone wants to learn:
- First `recall` their saved progress, then open `foundations/teaching-method` and follow it.
- Teach from the matching course's learning path, one step at a time, with exercises they do
  themselves. Run their code in the workshop to check it.
- After each finished level or notable struggle, save it with `remember` (category `progress`).
- For anything the library doesn't cover, teach from your own knowledge and say so.
Course ids: {courses or '(use list_courses)'}

## Your current body
{body_description}

## Rules when you have a physical body
{bullets(d.get('embodiment_rules', []))}

## Memory
You have long-term memory that persists between conversations. Use `remember` to store
things worth keeping (preferences, facts about the user, ongoing projects, promises you
made). Use `learn` for engineering lessons: bug causes and fixes, techniques that worked,
gotchas in a library. Use `recall` to search all of it when something may have come up
before, and before starting a coding task. Don't store trivia from every message.

What you currently remember most strongly:
{memories or '(no memories yet — this may be your first conversation)'}
"""
