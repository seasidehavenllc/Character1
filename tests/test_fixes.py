"""Tests for the v0.2 fixes: plugin isolation, self-edit branch safety, naming."""
from __future__ import annotations

import subprocess
import tempfile
import sys
import types
from pathlib import Path

import corvis.selfedit as selfedit
from corvis.__main__ import is_own_folder
from corvis.config import CORVIS_HOME, build_agent
from corvis.llm import Reply, ToolCall
from corvis.tools import load_plugins
from corvis.tools.base import ToolContext, ToolRegistry
from corvis.safety import CommandPolicy, Workspace


class FakeLLM:
    native_tools = True

    def __init__(self, replies):
        self.replies = list(replies)

    def chat(self, messages, tools=None):
        r = self.replies.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r


def iso(**cfg) -> dict:
    """Config with a throwaway data folder, so tests never touch real chats or memory."""
    return {"data_dir": tempfile.mkdtemp(), "internet": {"enabled": False}, **cfg}


def _git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True).stdout.strip()


def _repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q", "-b", "main")
    _git(tmp_path, "config", "user.email", "a@local")
    _git(tmp_path, "config", "user.name", "Corvis")
    (tmp_path / "x.txt").write_text("1\n")
    _git(tmp_path, "add", "-A")
    _git(tmp_path, "commit", "-qm", "init")
    return tmp_path


def _with_home(tmp_path, fn):
    """Point self-edit at a throwaway repo instead of Corvis's real folder."""
    old_home, old_tests = selfedit.CORVIS_HOME, selfedit.run_tests
    selfedit.CORVIS_HOME = tmp_path
    selfedit.run_tests = lambda: (True, "ok")
    try:
        return fn()
    finally:
        selfedit.CORVIS_HOME, selfedit.run_tests = old_home, old_tests


def test_broken_plugin_does_not_hide_others():
    import corvis.plugins as plugins_pkg
    pkg_dir = Path(plugins_pkg.__file__).parent
    bad, good = pkg_dir / "aaa_broken_test.py", pkg_dir / "zzz_good_test.py"
    bad.write_text("import does_not_exist_anywhere\n")
    good.write_text(
        "from corvis.tools.base import Tool, params\n"
        "def register(reg, ctx):\n"
        "    reg.register(Tool('zzz_good', 'test', params([]), lambda: 'ok'))\n")
    try:
        ctx = ToolContext(Workspace("."), CommandPolicy(), lambda _: False)
        reg = ToolRegistry(ctx)
        errors = load_plugins(reg, ctx)
        assert "zzz_good" in reg.tools
        assert any("aaa_broken_test" in e for e in errors)
    finally:
        bad.unlink()
        good.unlink()
        for name in ("corvis.plugins.aaa_broken_test", "corvis.plugins.zzz_good_test"):
            sys.modules.pop(name, None)


def test_current_model_plugin(tmp_path):
    cfg = iso(llm={"model": "qwen2.5-coder:14b"})
    a = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None,
                    llm=FakeLLM([]))
    assert a.registry.ctx.state["plugin_errors"] == []
    assert "qwen2.5-coder:14b" in a.registry.run("current_model", {})


def test_name_comes_from_config(tmp_path):
    a = build_agent(tmp_path, iso(name="Nova"), approver=lambda _: True,
                    on_event=lambda *_: None, llm=FakeLLM([]))
    assert a.messages[0]["content"].startswith("You are Nova,")
    b = build_agent(tmp_path, iso(), approver=lambda _: True,
                    on_event=lambda *_: None, llm=FakeLLM([]))
    assert b.messages[0]["content"].startswith("You are Corvis,")


def test_self_edit_refuses_leftover_branch(tmp_path):
    repo = _repo(tmp_path)
    _git(repo, "checkout", "-qb", "jarvis/self-edit-20261022-110849")
    out = _with_home(repo, lambda: selfedit.self_edit("x", iso(), approver=lambda _: True))
    assert "leftover self-edit branch" in out
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "jarvis/self-edit-20261022-110849"


def test_self_edit_interrupt_returns_to_main(tmp_path):
    repo = _repo(tmp_path)
    llm = FakeLLM([
        Reply("", [ToolCall("1", "write_file", {"path": "new.txt", "content": "hi"})]),
        KeyboardInterrupt(),
    ])
    try:
        _with_home(repo, lambda: selfedit.self_edit("x", iso(), approver=lambda _: True,
                                                    on_event=lambda *_: None, llm=llm))
        raise AssertionError("expected KeyboardInterrupt")
    except KeyboardInterrupt:
        pass
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    assert not (repo / "new.txt").exists()
    branches = _git(repo, "branch", "--list", "corvis/self-edit-*")
    assert "corvis/self-edit-" in branches  # partial work kept, not lost


def test_self_edit_merge_records_update(tmp_path):
    repo = _repo(tmp_path)
    before = _git(repo, "rev-parse", "HEAD")
    llm = FakeLLM([
        Reply("", [ToolCall("1", "write_file", {"path": "feature.txt", "content": "new\n"})]),
        Reply("Added feature."),
    ])
    cfg = iso()
    out = _with_home(repo, lambda: selfedit.self_edit("add feature", cfg, approver=lambda _: True,
                                                      on_event=lambda *_: None, llm=llm))
    assert out.startswith("Merged.")
    assert (repo / "feature.txt").exists()
    assert _git(repo, "rev-parse", "--abbrev-ref", "HEAD") == "main"
    # The merged branch is kept (so a rolled-back update can still be looked at),
    # and the supervisor knows what to go back to if the new code won't start.
    import json
    from corvis.supervisor import marker
    info = json.loads(marker(cfg).read_text())
    assert info["previous"] == before
    assert info["branch"] in _git(repo, "branch", "--list", "corvis/self-edit-*")
    # A kept, merged branch doesn't block the next self-edit.
    llm2 = FakeLLM([Reply("", [ToolCall("1", "write_file", {"path": "f2.txt", "content": "x\n"})]),
                    Reply("Done.")])
    out2 = _with_home(repo, lambda: selfedit.self_edit("again", iso(), approver=lambda _: True,
                                                       on_event=lambda *_: None, llm=llm2))
    assert out2.startswith("Merged.")


def test_code_mode_detects_own_folder():
    assert is_own_folder(str(CORVIS_HOME))
    assert not is_own_folder(str(CORVIS_HOME / "tests"))
