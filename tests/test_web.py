"""Web app tests: saved chats, background runs, approvals, stop, and local-only security.

Runs a real server on a spare port with a scripted FakeLLM. No real model, no browser.
"""
from __future__ import annotations

import json
import socket
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

import uvicorn

from corvis.config import build_agent
from corvis.conversations.store import ConversationStore, make_title
from corvis.llm import Reply, ToolCall
from corvis.web.runs import RunManager
from corvis.web.server import create_app


class FakeLLM:
    native_tools = True

    def __init__(self, replies, delay=0.0):
        self.replies = list(replies)
        self.delay = delay

    def chat(self, messages, tools=None):
        time.sleep(self.delay)
        return self.replies.pop(0) if self.replies else Reply("(out of script)")


def manager_with(tmp_path: Path, replies, delay=0.0) -> RunManager:
    llm = FakeLLM(replies, delay)

    def factory(workspace, cfg, **kw):
        return build_agent(workspace, cfg, llm=llm, **kw)

    cfg = {"data_dir": str(tmp_path / "data"), "internet": {"enabled": False}}
    return RunManager(ConversationStore(tmp_path / "data" / "conversations"), cfg, agent_factory=factory)


def wait_done(mgr: RunManager, conv_id: str, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        run = mgr.runs.get(conv_id)
        if run and run.done:
            return run
        time.sleep(0.02)
    raise AssertionError("run did not finish")


def test_store_roundtrip_and_titles(tmp_path):
    store = ConversationStore(tmp_path)
    c = store.create(str(tmp_path))
    c["messages"].append({"role": "user", "text": "hi"})
    store.save(c)
    assert store.get(c["id"])["messages"][0]["text"] == "hi"
    assert [x["id"] for x in store.list()] == [c["id"]]
    store.delete(c["id"])
    assert store.list() == []
    assert make_title("  fix   the\nbuild ") == "fix the build"
    assert make_title("x" * 100).endswith("…")


def test_store_rejects_path_tricks(tmp_path):
    store = ConversationStore(tmp_path)
    for bad in ("../secret", "a/b", ""):
        try:
            store.get(bad)
            raise AssertionError("expected KeyError")
        except KeyError:
            pass


def test_run_saves_reply_and_history(tmp_path):
    (tmp_path / "proj").mkdir()
    mgr = manager_with(tmp_path, [
        Reply("", [ToolCall("1", "write_file", {"path": "a.txt", "content": "x"})]),
        Reply("Wrote **a.txt**."),
    ])
    conv = mgr.store.create(str(tmp_path / "proj"))
    mgr.start(conv["id"], "make a file please")
    run = wait_done(mgr, conv["id"])
    kinds = [e["kind"] for e in run.events]
    assert kinds[0] == "start" and kinds[-1] == "end" and "tool" in kinds and "done" in kinds
    saved = mgr.store.get(conv["id"])
    assert saved["title"] == "make a file please"
    assert saved["messages"][-1]["text"] == "Wrote **a.txt**."
    assert saved["messages"][-1]["status"] == "ok"
    assert any(m.get("role") == "tool" for m in saved["llm_history"])
    assert (tmp_path / "proj" / "a.txt").read_text() == "x"


def test_history_survives_restart(tmp_path):
    (tmp_path / "proj").mkdir()
    mgr = manager_with(tmp_path, [Reply("first answer")])
    conv = mgr.store.create(str(tmp_path / "proj"))
    mgr.start(conv["id"], "remember the word raven")
    wait_done(mgr, conv["id"])

    seen = {}

    class Spy(FakeLLM):
        def chat(self, messages, tools=None):
            seen["messages"] = [m.get("content") for m in messages]
            return Reply("second answer")

    def factory(workspace, cfg, **kw):
        return build_agent(workspace, cfg, llm=Spy([]), **kw)

    fresh = RunManager(mgr.store, mgr.cfg, agent_factory=factory)  # simulates a restart
    fresh.start(conv["id"], "what was the word?")
    wait_done(fresh, conv["id"])
    assert "remember the word raven" in seen["messages"]
    assert "first answer" in seen["messages"]


def test_approval_allow_and_deny(tmp_path):
    (tmp_path / "proj").mkdir()
    mgr = manager_with(tmp_path, [
        Reply("", [ToolCall("1", "run_command", {"command": "echo allowed-run"})]),
        Reply("", [ToolCall("2", "delete_file", {"path": "keep.txt"})]),
        Reply("done"),
    ])
    (tmp_path / "proj" / "keep.txt").write_text("keep")
    conv = mgr.store.create(str(tmp_path / "proj"))
    run = mgr.start(conv["id"], "go")

    def answer_next(allow):
        end = time.time() + 5
        while time.time() < end:
            for ev in run.events:
                if ev["kind"] == "approval" and ev.get("answered") is None:
                    ev["answered"] = allow
                    assert mgr.find_approval(ev["id"]) is run
                    assert run.answer(ev["id"], allow)
                    return
            time.sleep(0.02)
        raise AssertionError("no approval request")

    # "echo" is on the safe list, so the first command runs without asking.
    answer_next(False)  # deny deleting keep.txt
    wait_done(mgr, conv["id"])
    tool_results = [e["text"] for e in run.events if e["kind"] == "result"]
    assert "allowed-run" in tool_results[0]
    assert "declined" in tool_results[1]
    assert (tmp_path / "proj" / "keep.txt").exists()
    verdicts = [e["text"] for e in run.events if e["kind"] == "approval_result"]
    assert verdicts == ["denied"]


def test_stop_ends_run_cleanly(tmp_path):
    (tmp_path / "proj").mkdir()
    steps = [Reply("", [ToolCall(str(i), "list_dir", {"depth": i})]) for i in range(1, 30)]
    mgr = manager_with(tmp_path, steps, delay=0.05)
    conv = mgr.store.create(str(tmp_path / "proj"))
    run = mgr.start(conv["id"], "slow")
    time.sleep(0.2)
    run.stop()
    wait_done(mgr, conv["id"])
    saved = mgr.store.get(conv["id"])["messages"][-1]
    assert saved["status"] == "stopped"
    agent = mgr.agents[conv["id"]]
    # every tool call in the history has its answer (otherwise the next message would fail)
    call_ids = {c["id"] for m in agent.messages if m.get("tool_calls") for c in m["tool_calls"]}
    answered = {m["tool_call_id"] for m in agent.messages if m["role"] == "tool"}
    assert call_ids <= answered


def test_one_run_per_chat(tmp_path):
    (tmp_path / "proj").mkdir()
    mgr = manager_with(tmp_path, [Reply("ok")], delay=0.3)
    conv = mgr.store.create(str(tmp_path / "proj"))
    mgr.start(conv["id"], "first")
    try:
        mgr.start(conv["id"], "second")
        raise AssertionError("expected RuntimeError")
    except RuntimeError:
        pass
    wait_done(mgr, conv["id"])


# --- the HTTP server ------------------------------------------------------------
def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class Server:
    def __init__(self, tmp_path, replies, **extra_cfg):
        (tmp_path / "proj").mkdir(exist_ok=True)
        self.workspace = str(tmp_path / "proj")
        mgr = manager_with(tmp_path, replies)
        cfg = {**mgr.cfg, "web": {"default_workspace": self.workspace}, **extra_cfg}
        mgr.cfg = cfg
        self.app = create_app(cfg, manager=mgr)
        self.port = _free_port()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)

    def call(self, method, path, data=None, headers=None):
        hdrs = {"X-Corvis": "1", "Content-Type": "application/json"}
        hdrs.update(headers or {})
        req = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                     data=json.dumps(data).encode() if data is not None else None,
                                     headers={k: v for k, v in hdrs.items() if v is not None})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                raw = r.read().decode()
                return r.status, (json.loads(raw) if raw.startswith(("{", "[")) else raw)
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode()


def test_server_security(tmp_path):
    with Server(tmp_path, []) as s:
        assert s.call("GET", "/api/info", headers={"X-Corvis": None})[0] == 403
        assert s.call("GET", "/api/info", headers={"Host": "evil.example"})[0] == 403
        status, info = s.call("GET", "/api/info")
        assert status == 200 and info["name"] == "Corvis"
        status, page = s.call("GET", "/", headers={"X-Corvis": None})
        assert status == 200 and "<title>Corvis</title>" in page


def test_server_chat_flow(tmp_path):
    with Server(tmp_path, [Reply("Hello from Corvis")]) as s:
        status, conv = s.call("POST", "/api/conversations", {})
        assert status == 201 and conv["workspace"] == s.workspace
        status, _ = s.call("POST", f"/api/conversations/{conv['id']}/messages", {"text": "hi"})
        assert status == 202
        status, stream = s.call("GET", f"/api/conversations/{conv['id']}/events?after=0")
        events = [json.loads(line[6:]) for line in stream.split("\n") if line.startswith("data: ")]
        assert events[-1]["kind"] == "end"
        assert any(e["kind"] == "done" and e["text"] == "Hello from Corvis" for e in events)
        status, full = s.call("GET", f"/api/conversations/{conv['id']}")
        assert [m["role"] for m in full["messages"]] == ["user", "assistant"]
        assert "llm_history" not in full
        status, _ = s.call("PATCH", f"/api/conversations/{conv['id']}", {"title": "Renamed"})
        assert s.call("GET", "/api/conversations")[1]["conversations"][0]["title"] == "Renamed"
        status, err = s.call("PATCH", f"/api/conversations/{conv['id']}", {"workspace": s.workspace})
        assert status == 400 and "already started" in err
        assert s.call("DELETE", f"/api/conversations/{conv['id']}")[0] == 200
        assert s.call("GET", f"/api/conversations/{conv['id']}")[0] == 404


def test_server_refuses_corvis_folder_as_project(tmp_path):
    from corvis.config import CORVIS_HOME
    with Server(tmp_path, []) as s:
        status, err = s.call("POST", "/api/conversations", {"workspace": str(CORVIS_HOME)})
        assert status == 400 and "Improve Corvis" in err
        status, res = s.call("POST", "/api/folders/check", {"path": str(CORVIS_HOME)})
        assert res["is_corvis"] is True
        new = str(tmp_path / "brand-new")
        status, res = s.call("POST", "/api/folders/check", {"path": new, "create": True})
        assert res["exists"] is True and Path(new).is_dir()


def test_stop_ends_a_reply_even_while_the_model_is_thinking(tmp_path, monkeypatch):
    from corvis.web import runs as runs_mod
    monkeypatch.setattr(runs_mod, "STOP_GRACE", 0.2)
    (tmp_path / "proj").mkdir()
    mgr = manager_with(tmp_path, [Reply("This answer came far too late.")], delay=1.5)
    conv = mgr.store.create(str(tmp_path / "proj"))
    run = mgr.start(conv["id"], "think hard")
    time.sleep(0.1)
    assert mgr.stop(conv["id"]) is run
    wait_done(mgr, conv["id"], timeout=1.0)                 # ended long before the model answered
    assert run.events[-1] == {**run.events[-1], "kind": "end", "text": "stopped"}
    time.sleep(1.8)                                         # the late answer arrives...
    msgs = mgr.store.get(conv["id"])["messages"]
    assert [m.get("status") for m in msgs] == [None, "stopped"]  # ...and is dropped
    assert "too late" not in json.dumps(msgs)
    assert mgr.store.get(conv["id"]).get("llm_history") == []


def test_live_events_stream_without_middleware_buffering(tmp_path):
    with Server(tmp_path, [Reply("hi")]) as s:
        status, conv = s.call("POST", "/api/conversations", {})
        s.call("POST", f"/api/conversations/{conv['id']}/messages", {"text": "hello"})
        wait_done(s.app.state.manager, conv["id"])
        assert s.call("GET", f"/api/conversations/{conv['id']}/status")[1] == {"running": False, "events": 3}
        status, page = s.call("GET", "/", headers={"X-Corvis": None})
        assert status == 200
