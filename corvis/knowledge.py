"""Corvis's built-in library: courses and references for programming languages and robotics.

The library is plain Markdown in `knowledge/`, shipped inside the app, so it works offline
and is identical on every device. Each file is one course: front matter (title, tags), then
`## ` sections, with the learning path under `## Learning path` as `### Level N` steps.
It's indexed for full-text search at startup, which lets small offline models look things
up instead of relying only on what they remember.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

import yaml

KNOWLEDGE_DIR = Path(__file__).resolve().parent.parent / "knowledge"
MAX_SECTION_CHARS = 6000


@dataclass
class Course:
    id: str                      # e.g. "languages/python"
    title: str
    tags: list[str]
    summary: str
    sections: list[tuple[str, str]] = field(default_factory=list)  # (heading, body)

    @property
    def levels(self) -> list[str]:
        return [h for h, _ in self.sections if h.lower().startswith("level")]


def parse_course(course_id: str, text: str) -> Course:
    meta: dict = {}
    if text.startswith("---"):
        _, front, text = text.split("---", 2)
        meta = yaml.safe_load(front) or {}
    sections: list[tuple[str, str]] = []
    heading, buf = "Introduction", []
    in_code = False
    for line in text.splitlines():
        if line.startswith("```"):
            in_code = not in_code
        m = None if in_code else re.match(r"^(#{2,3})\s+(.*)", line)
        if m:
            if "".join(buf).strip():
                sections.append((heading, "\n".join(buf).strip()))
            heading, buf = m.group(2).strip(), []
        elif not line.startswith("# "):
            buf.append(line)
    if "".join(buf).strip():
        sections.append((heading, "\n".join(buf).strip()))
    return Course(course_id, meta.get("title", course_id), list(meta.get("tags", [])),
                  meta.get("summary", ""), sections)


class KnowledgeBase:
    def __init__(self, root: str | Path = KNOWLEDGE_DIR):
        self.root = Path(root)
        self.courses: dict[str, Course] = {}
        for path in sorted(self.root.rglob("*.md")):
            if path.name.lower() == "readme.md":
                continue
            cid = path.relative_to(self.root).with_suffix("").as_posix()
            self.courses[cid] = parse_course(cid, path.read_text(encoding="utf-8"))
        self.db = sqlite3.connect(":memory:", check_same_thread=False)
        self.db.execute("CREATE VIRTUAL TABLE sections USING fts5(course, title, tags, heading, body)")
        self.db.executemany(
            "INSERT INTO sections VALUES (?, ?, ?, ?, ?)",
            [(c.id, c.title, " ".join(c.tags), h, b) for c in self.courses.values() for h, b in c.sections],
        )

    def _guess(self, wanted: str) -> Course | None:
        """Find a course from a loose name like 'arduino basics' or 'hardware/arduino'."""
        words = set(re.split(r"[\s/_.-]+", wanted.lower())) - {""}
        scored = []
        for cid, c in self.courses.items():
            name_words = set(re.split(r"[/-]", cid.lower())) | set(c.title.lower().split())
            if hits := len(words & name_words):
                scored.append((hits, cid))
        scored.sort(reverse=True)
        if scored and (len(scored) == 1 or scored[0][0] > scored[1][0]):
            return self.courses[scored[0][1]]
        return None

    def ids(self) -> str:
        return ", ".join(self.courses)

    def catalog(self) -> str:
        lines = []
        for area in sorted({cid.split("/")[0] for cid in self.courses}):
            lines.append(f"{area.upper()}:")
            for c in self.courses.values():
                if c.id.startswith(area + "/"):
                    lines.append(f"- {c.id} — {c.title}: {c.summary} ({len(c.levels)} levels)")
        return "\n".join(lines)

    def search(self, query: str, limit: int = 4) -> str:
        terms = [w.replace('"', "") for w in query.split() if w.strip('"')]
        if not terms:
            return "Empty query."
        rows = self.db.execute(
            "SELECT course, heading, body FROM sections WHERE sections MATCH ? "
            "ORDER BY bm25(sections, 0, 4, 2, 3, 1) LIMIT ?",
            (" OR ".join(f'"{t}"' for t in terms), limit),
        ).fetchall()
        if not rows:
            return "Nothing in the library matches. Answer from your own knowledge, and say so."
        return "\n\n".join(f"### {c} › {h}\n{b[:2000]}" for c, h, b in rows)

    def open(self, course_id: str, section: str = "") -> str:
        course = self.courses.get(course_id.strip().strip("/")) or self._guess(course_id)
        if course is None:
            raise KeyError(f"No course {course_id!r}. Available: {', '.join(self.courses)}")
        if not section:
            outline = "\n".join(f"- {h}" for h, _ in course.sections)
            return f"# {course.title} ({course.id})\n{course.summary}\n\nSections:\n{outline}"
        for heading, body in course.sections:
            if section.lower() in heading.lower():
                text = f"# {course.title} › {heading}\n{body}"
                return text if len(text) <= MAX_SECTION_CHARS else text[:MAX_SECTION_CHARS] + "\n... (truncated)"
        raise KeyError(f"{course.id} has no section matching {section!r}. Open it without a section for the outline.")
