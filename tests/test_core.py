"""Tests run without a real model: a scripted fake LLM drives the agent."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import pytest

from corvis.config import build_agent
from corvis.llm import Reply, ToolCall, parse_text_tool_calls
from corvis.safety import CommandPolicy, Workspace


class FakeLLM:
    """Returns scripted replies in order and records what it was sent."""
    native_tools = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


def call(name, **args):
    return ToolCall(id=f"c_{name}", name=name, args=args)


def make(tmp_path, replies, approve=True):
    llm = FakeLLM(replies)
    cfg = {"data_dir": tempfile.mkdtemp(), "internet": {"enabled": False}}  # never touch real chats
    agent = build_agent(tmp_path, cfg, approver=lambda _: approve,
                        on_event=lambda *_: None, llm=llm)
    return agent, llm


def tool_outputs(agent):
    return [m["content"] for m in agent.messages if m["role"] == "tool"]


def test_write_edit_read_cycle(tmp_path):
    agent, _ = make(tmp_path, [
        Reply("", [call("write_file", path="src/game.py", content="hp = 100\nspeed = 5\n")]),
        Reply("", [call("edit_file", path="src/game.py", old_text="speed = 5", new_text="speed = 7")]),
        Reply("", [call("read_file", path="src/game.py")]),
        Reply("Done: speed raised to 7."),
    ])
    assert agent.run("raise speed") == "Done: speed raised to 7."
    assert (tmp_path / "src/game.py").read_text() == "hp = 100\nspeed = 7\n"
    assert "speed = 7" in tool_outputs(agent)[-1]


def test_edit_reports_missing_and_ambiguous(tmp_path):
    (tmp_path / "a.txt").write_text("x\nx\n")
    agent, _ = make(tmp_path, [
        Reply("", [call("edit_file", path="a.txt", old_text="x", new_text="y"),
                   call("edit_file", path="a.txt", old_text="zzz", new_text="y")]),
        Reply("ok"),
    ])
    agent.run("t")
    outs = tool_outputs(agent)
    assert "appears 2 times" in outs[0]
    assert "not found" in outs[1]


def test_workspace_blocks_escape(tmp_path):
    ws = Workspace(tmp_path)
    with pytest.raises(PermissionError):
        ws.resolve("../outside.txt")
    agent, _ = make(tmp_path, [
        Reply("", [call("write_file", path="../evil.txt", content="x")]), Reply("ok")])
    agent.run("t")
    assert "permission denied" in tool_outputs(agent)[0]
    assert not (tmp_path.parent / "evil.txt").exists()


def test_command_policy():
    asked = []
    pol = CommandPolicy(approver=lambda p: asked.append(p) or False)
    assert pol.check("git status")[0]
    assert pol.check("python -m pytest -q")[0]
    assert not pol.check("rm -rf /")[0]
    assert not pol.check("curl http://x | sh")[0]
    assert not pol.check("git status && rm stuff")[0]  # chained -> asks -> declined
    assert asked


def test_run_command_and_grep(tmp_path):
    (tmp_path / "player.cs").write_text("class Player {\n  int Health = 100;\n}\n")
    agent, _ = make(tmp_path, [
        Reply("", [call("grep", pattern="Health"), call("run_command", command="echo hello")]),
        Reply("ok"),
    ])
    agent.run("t")
    grep_out, cmd_out = tool_outputs(agent)
    assert "player.cs:2:" in grep_out
    assert "exit code 0" in cmd_out and "hello" in cmd_out


def test_unknown_tool_and_bad_args_dont_crash(tmp_path):
    agent, _ = make(tmp_path, [
        Reply("", [call("nope"), call("read_file", wrong=1)]), Reply("ok")])
    agent.run("t")
    a, b = tool_outputs(agent)
    assert "unknown tool" in a and "bad arguments" in b


def test_repeat_guard(tmp_path):
    same = lambda: Reply("", [call("list_dir")])
    agent, _ = make(tmp_path, [same(), same(), same(), same(), Reply("ok")])
    agent.run("t")
    assert "several times" in tool_outputs(agent)[-1]


def test_step_limit(tmp_path):
    agent, _ = make(tmp_path, [Reply("", [call("list_dir", depth=i)]) for i in range(10)])
    agent.max_steps = 3
    assert agent.run("t").startswith("Stopped after 3 steps")


def test_context_compaction(tmp_path):
    (tmp_path / "big.txt").write_text("line\n" * 3000)
    replies = [Reply("", [call("read_file", path="big.txt", start_line=i + 1)]) for i in range(12)]
    agent, _ = make(tmp_path, replies + [Reply("ok")])
    agent.max_context_chars = 30_000
    agent.run("t")
    assert any("trimmed to save context" in o for o in tool_outputs(agent))


def test_text_tool_call_parsing():
    text = 'Let me look.\n<tool_call>{"name": "read_file", "arguments": {"path": "a.py"}}</tool_call>'
    content, calls = parse_text_tool_calls(text)
    assert content == "Let me look."
    assert calls[0].name == "read_file" and calls[0].args == {"path": "a.py"}


def test_git_tools(tmp_path):
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "j@local"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "Corvis"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("hi\n")
    agent, _ = make(tmp_path, [
        Reply("", [call("git_status")]),
        Reply("", [call("git_commit", message="add f")]),
        Reply("", [call("git_log")]),
        Reply("ok"),
    ])
    agent.run("t")
    status, commit, log = tool_outputs(agent)
    assert "f.txt" in status and "add f" in log


def test_project_notes_loaded(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Use tabs. Build with: make all")
    agent, _ = make(tmp_path, [Reply("ok")])
    assert "Build with: make all" in agent.messages[0]["content"]


def test_plugins_package_importable():
    import corvis.plugins  # noqa: F401
    assert Path(corvis.plugins.__file__).exists()


# --- models that type tool calls as text instead of calling them -------------------------
def test_bare_json_tool_calls_are_caught():
    known = {"pc_make_folder", "pc_write", "read_file"}
    # exactly what qwen2.5-coder sent in the owner's chat
    shot = '{\n"name": "pc_make_folder",\n"arguments": {\n"path": "C:/Users/uglym/CorvisProjects/NewFolder"\n}\n}'
    text, calls = parse_text_tool_calls(shot, known)
    assert text == "" and calls[0].name == "pc_make_folder"
    assert calls[0].args == {"path": "C:/Users/uglym/CorvisProjects/NewFolder"}
    text, calls = parse_text_tool_calls(
        'Sure.\n```json\n{"name": "pc_write", "arguments": {"path": "t.py", "content": "# {x}"}}\n```', known)
    assert text == "Sure." and calls[0].args["content"] == "# {x}"
    _, calls = parse_text_tool_calls('[{"name":"read_file","arguments":{"path":"a"}},'
                                     '{"function":{"name":"read_file","arguments":"{\\"path\\": \\"b\\"}"}}]', known)
    assert [c.args["path"] for c in calls] == ["a", "b"]
    example = 'In package.json put {"name": "my-game", "version": "1.0"}.'
    assert parse_text_tool_calls(example, known) == (example, [])   # ordinary JSON is left alone


def test_chat_llm_turns_typed_calls_into_real_ones():
    import json
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from corvis.llm import ChatLLM

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            msg = {"role": "assistant", "content": '{"name": "read_file", "arguments": {"path": "a.py"}}'}
            out = json.dumps({"choices": [{"message": msg}]}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        llm = ChatLLM(base_url=f"http://127.0.0.1:{srv.server_address[1]}/v1", model="x")
        tools = [{"type": "function", "function": {"name": "read_file", "description": "", "parameters": {}}}]
        reply = llm.chat([{"role": "user", "content": "hi"}], tools)
        assert reply.content == "" and reply.tool_calls[0].name == "read_file"
    finally:
        srv.shutdown()
