"""The built-in course library: structure, search, and code that actually runs."""

import re
import sys
from pathlib import Path

import pytest

from corvis.knowledge import KNOWLEDGE_DIR, KnowledgeBase

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
from check_knowledge import run_block  # noqa: E402

KB = KnowledgeBase()
EXPECTED = {
    "languages": {"python", "javascript", "typescript", "html-css", "java", "c", "cpp", "csharp", "go", "rust",
                  "swift", "kotlin", "php", "ruby", "sql", "bash", "lua", "dart", "r"},
    "robotics": {"fundamentals", "electronics", "arduino", "raspberry-pi", "control-pid", "kinematics", "ros2",
                 "computer-vision", "safety"},
    "foundations": {"teaching-method", "git", "debugging", "algorithms"},
}


def test_library_has_every_course():
    for area, names in EXPECTED.items():
        assert {f"{area}/{n}" for n in names} <= set(KB.courses), area


@pytest.mark.parametrize("course_id", sorted(KB.courses))
def test_course_is_complete(course_id):
    course = KB.courses[course_id]
    assert course.title and course.summary and course.tags
    assert len(course.levels) == 4, f"{course_id} should have Level 1-4"
    headings = [h for h, _ in course.sections]
    if course_id.startswith("languages/"):
        assert "Common mistakes" in headings and any("Setup" in h for h in headings)


def test_search_and_open():
    assert "pull-up" in KB.search("button pull-up resistor").lower()
    assert "Level 2" in KB.open("robotics/arduino", "level 2")
    assert "Sections:" in KB.open("rust")               # loose names work
    assert KB.open("hardware/arduino/basics").startswith("# Arduino")
    assert KB.open("Raspberry Pi").startswith("# Raspberry Pi")
    with pytest.raises(KeyError):
        KB.open("languages/cobol")


def test_every_python_snippet_is_valid_syntax():
    for path in KNOWLEDGE_DIR.rglob("*.md"):
        for code in re.findall(r"^```python(?: run)?\n(.*?)^```", path.read_text(), re.S | re.M):
            compile(code, str(path), "exec")


def test_python_examples_run():
    for path in KNOWLEDGE_DIR.rglob("*.md"):
        for code in re.findall(r"^```python run\n(.*?)^```", path.read_text(), re.S | re.M):
            status, out = run_block("python", code)
            assert status == "ok", f"{path}: {out}"
