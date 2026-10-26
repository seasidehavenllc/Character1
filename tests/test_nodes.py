"""Cloud hub + PC node tests: pairing, the job queue, approvals relayed from the PC into the
hub's chat, PC tools that appear only while the PC is online, the Files browser through the
node, the hub installer's setup step, config edits, and the self-update safety net."""
from __future__ import annotations

import json
import os
import stat
import subprocess
import threading
import time
from pathlib import Path

import pytest

from corvis import hub_setup, supervisor
from corvis.config_edit import replace_block
from corvis.llm import Reply, ToolCall
from corvis.node import Node, link, node_cfg
from corvis.nodes import NodeHub
from corvis.web.auth import Auth

from tests.test_web import Server, wait_done

PASSWORD = "ravens fly at midnight"


# --- the hub's node registry ------------------------------------------------------------
def test_pairing_tokens_are_hashed_and_revocable(tmp_path):
    hub = NodeHub(tmp_path)
    node_id, token = hub.pair("Gaming PC")
    assert token.startswith("cvn_")
    assert token not in (tmp_path / "nodes.json").read_text()       # only a hash is stored
    assert hub.authenticate(token) == node_id
    assert hub.authenticate("cvn_made_up") is None and hub.authenticate(None) is None
    assert hub.paired() == [{"id": node_id, "name": "Gaming PC", "online": False, "last_seen": None}]
    assert hub.unpair(node_id) and hub.authenticate(token) is None


def test_jobs_results_and_relayed_approvals(tmp_path):
    hub = NodeHub(tmp_path)
    node_id, _ = hub.pair("PC")
    other_id, _ = hub.pair("Laptop")
    with pytest.raises(ConnectionError):
        hub.call(node_id, "tool", "pc_list", {})                     # never said hello: offline
    assert "not linked" not in hub.status_line() and "OFFLINE" in hub.status_line()

    hub.hello(node_id, "Kody's PC", [], {})
    asked = []

    def fake_pc():
        job = hub.poll(node_id, wait=5)
        assert job.name == "pc_move" and job.args == {"source": "a", "destination": "b"}
        assert not hub.ask(other_id, job.id, "sneaky")                # another node can't answer
        assert hub.ask(node_id, job.id, "Move a to b?") is True
        assert not hub.result(other_id, job.id, "forged")             # nor finish someone else's job
        hub.result(node_id, job.id, "moved")

    t = threading.Thread(target=fake_pc)
    t.start()
    out = hub.call(node_id, "tool", "pc_move", {"source": "a", "destination": "b"},
                   approver=lambda p: asked.append(p) or True)
    t.join(5)
    assert out == "moved"
    assert asked == ["On your PC (Kody's PC): Move a to b?"]
    assert "Kody's PC" in hub.status_line() and "online" in hub.status_line()


def test_call_gives_up_when_pc_goes_quiet(tmp_path, monkeypatch):
    hub = NodeHub(tmp_path)
    node_id, _ = hub.pair("PC")
    hub.hello(node_id, "PC", [], {})
    with pytest.raises(TimeoutError):
        hub.call(node_id, "tool", "pc_list", {}, timeout=0.5)        # PC never picks it up
    monkeypatch.setattr("corvis.nodes.ONLINE_GRACE", 0)
    with pytest.raises(ConnectionError):
        hub.call(node_id, "tool", "pc_list", {}, timeout=5)
    assert hub.jobs == {}                                             # nothing left hanging


def test_status_line_when_nothing_is_linked(tmp_path):
    assert "not linked yet" in NodeHub(tmp_path).status_line()


# --- config.yaml edits ------------------------------------------------------------------
def test_replace_block_keeps_comments_and_other_sections():
    text = ("name: Corvis   # my assistant\n\nllm:\n  model: old\n  # tuned\n  temperature: 0.2\n\n"
            "# How PC access works\npc_access:\n  enabled: true\n")
    out = replace_block(text, "llm", ["llm:", "  model: new"])
    assert "model: new" in out and "model: old" not in out and "temperature" not in out
    assert "# my assistant" in out and "# How PC access works\npc_access:\n  enabled: true" in out
    out2 = replace_block(out, "node", ["node:", "  hub_url: https://x"])
    assert out2.endswith("node:\n  hub_url: https://x\n") and "pc_access:" in out2
    assert replace_block("", "node", ["node:", "  a: 1"]) == "node:\n  a: 1\n"
    from corvis.config_edit import remove_block
    gone = remove_block(out2 + "\n# after\nlast: 1\n", "pc_access")
    assert "pc_access" not in gone and "How PC access works" not in gone and "# after\nlast: 1" in gone
    assert remove_block("a: 1\n", "missing") == "a: 1\n"


# --- hub setup (run by the installer) ---------------------------------------------------
class OkLLM:
    def __init__(self, **kw):
        self.kw = kw

    def chat(self, messages):
        return Reply("online")


MODELS = [{"id": "qwen/qwen3-coder", "supported_parameters": ["tools"], "pricing": {"prompt": "0.0000002"}},
          {"id": "some/chat-only", "supported_parameters": []},
          {"id": "google/gemini-2.5-flash", "supported_parameters": ["tools"],
           "architecture": {"input_modalities": ["text", "image"]}}]


def test_hub_setup_writes_private_key_and_config(tmp_path, monkeypatch):
    monkeypatch.setitem(hub_setup.runner, "models", lambda: MODELS)
    monkeypatch.setattr(hub_setup, "ChatLLM", OkLLM)
    config, env, data = tmp_path / "config.yaml", tmp_path / "corvis.env", tmp_path / "data"
    # The PC's own config came along: keep its personality, drop what only makes sense on the PC.
    config.write_text("name: Corvis\npersonality: \"dry wit\"\ndata_dir: C:/Corvis/data\n\n"
                      "# This PC lends its files\nnode:\n  hub_url: https://old\n  name: PC\n\n"
                      "vision:\n  model: qwen2.5vl:7b\n")
    answers = iter(["some/chat-only", "not/real", ""])                 # refused, unknown, then default
    secrets_ = iter(["sk-or-secret", PASSWORD, PASSWORD])
    logs = []
    code = hub_setup.run(config, "corvis-hub.tail.ts.net", env, data, ask=lambda _: next(answers),
                         secret=lambda _: next(secrets_), log=logs.append)
    assert code == 0
    assert any("doesn't support tool use" in m for m in logs) and any("isn't on OpenRouter" in m for m in logs)
    assert stat.S_IMODE(os.stat(env).st_mode) == 0o600
    assert "OPENROUTER_API_KEY=sk-or-secret" in env.read_text()
    text = config.read_text()
    assert "sk-or-secret" not in text                                  # the key never goes in config.yaml
    import yaml
    cfg = yaml.safe_load(text)
    assert cfg["personality"] == "dry wit"                             # owner's settings kept
    assert cfg["llm"]["model"] == "qwen/qwen3-coder" and cfg["llm"]["api_key_env"] == "OPENROUTER_API_KEY"
    assert cfg["web"]["host"] == "127.0.0.1"                           # only reachable through Tailscale
    assert cfg["remote"] == {"enabled": True, "allowed_hosts": ["corvis-hub.tail.ts.net"]}
    assert cfg["pc_access"]["enabled"] is False and cfg["apps"]["enabled"] is False
    assert "node" not in cfg and "data_dir" not in cfg and "This PC lends" not in text
    assert cfg["vision"]["model"] == "google/gemini-2.5-flash"           # photos read in the cloud too
    assert cfg["vision"]["base_url"] == hub_setup.BASE_URL
    assert Auth(data).login(PASSWORD)

    # Running it again keeps the key and password, and only asks to confirm.
    answers = iter(["", ""])
    assert hub_setup.run(config, "corvis-hub.tail.ts.net", env, data, ask=lambda _: next(answers),
                         secret=lambda _: pytest.fail("shouldn't ask"), log=lambda _: None) == 0
    assert "sk-or-secret" in env.read_text()


def test_api_key_comes_from_the_environment(monkeypatch):
    from corvis.config import api_key
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
    assert api_key({"api_key_env": "OPENROUTER_API_KEY", "api_key": "x"}) == "sk-or-env"
    monkeypatch.delenv("OPENROUTER_API_KEY")
    assert api_key({"api_key_env": "OPENROUTER_API_KEY"}) == "local"
    assert api_key({"api_key": "ollama"}) == "ollama"


# --- the supervisor: restarts and self-update rollback ---------------------------------
class FakeProc:
    def __init__(self, code):
        self.code = code

    def wait(self, timeout=None):
        return self.code


def test_supervisor_restarts_and_rolls_back_a_bad_update(tmp_path, monkeypatch):
    def git(*a):
        return subprocess.run(["git", *a], cwd=tmp_path, capture_output=True, text=True).stdout.strip()
    git("init", "-q", "-b", "main")
    git("config", "user.email", "a@local")
    git("config", "user.name", "Corvis")
    (tmp_path / "app.py").write_text("good\n")
    git("add", "-A")
    git("commit", "-qm", "good")
    good = git("rev-parse", "HEAD")
    (tmp_path / "app.py").write_text("broken\n")
    git("commit", "-qam", "self-edit")

    cfg = {"data_dir": str(tmp_path / "data")}
    supervisor.record_update(cfg, good, "corvis/self-edit-1")
    monkeypatch.setattr(supervisor, "CORVIS_HOME", tmp_path)
    monkeypatch.setattr(supervisor.time, "sleep", lambda s: None)
    codes = iter([3, 1, 0])          # asks to restart, then crashes at once, then stops normally
    cmds = []

    def popen(cmd, cwd):
        cmds.append(cmd)
        return FakeProc(next(codes))

    assert supervisor.serve(cfg, "c.yaml", open_browser=True, popen=popen, log=lambda _: None) == 0
    assert len(cmds) == 3
    assert "--no-browser" not in cmds[0] and all("--no-browser" in c for c in cmds[1:])  # one tab only
    assert (tmp_path / "app.py").read_text() == "good\n"                  # back on working code
    assert not supervisor.marker(cfg).exists()
    notice = json.loads(supervisor.notice_file(cfg).read_text())
    assert "corvis/self-edit-1" in notice["text"]


def test_supervisor_keeps_restarting_after_ordinary_crashes(tmp_path, monkeypatch):
    monkeypatch.setattr(supervisor.time, "sleep", lambda s: None)
    codes = iter([1, 1, 0])
    cfg = {"data_dir": str(tmp_path)}
    assert supervisor.serve(cfg, None, open_browser=False, popen=lambda cmd, cwd: FakeProc(next(codes)),
                            log=lambda _: None) == 0


# --- end to end: hub server + a real node -----------------------------------------------
class RunningNode:
    """A PC node (Corvis Node) running in a thread against the test hub."""

    def __init__(self, tmp_path, port, token, pc_root):
        cfg = {"data_dir": str(tmp_path / "pcdata"), "pc_access": {"roots": [str(pc_root)]},
               "apps": {"enabled": False}, "web": {"default_workspace": str(tmp_path / "pcproj")},
               "node": {"hub_url": f"http://127.0.0.1:{port}", "name": "Test PC"}}
        (tmp_path / "pcdata").mkdir(exist_ok=True)
        (tmp_path / "pcdata" / "node_token").write_text(token)
        self.node = Node(cfg, log=lambda _: None)
        self.stop = False
        self.thread = threading.Thread(target=self.loop, daemon=True)

    def loop(self):
        self.node.hello()
        while not self.stop:
            self.node.step()

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.stop = True


def _wait_for(pred, timeout=10.0):
    end = time.time() + timeout
    while time.time() < end:
        if pred():
            return
        time.sleep(0.05)
    raise AssertionError("timed out")


def test_hub_uses_the_pc_through_the_node(tmp_path, monkeypatch):
    monkeypatch.setattr("corvis.nodes.NodeHub.poll",
                        lambda self, nid, wait=25.0, _orig=NodeHub.poll: _orig(self, nid, 0.3))
    pc_root = tmp_path / "PC"
    (pc_root / "Games").mkdir(parents=True)
    (pc_root / "Games" / "notes.txt").write_text("level 3 boss: use fire")
    (pc_root / "Games" / "save.dat").write_bytes(b"\x00\x01")
    replies = [
        Reply("", [ToolCall("1", "pc_list", {"path": str(pc_root / "Games")})]),
        Reply("", [ToolCall("2", "pc_move", {"source": str(pc_root / "Games" / "save.dat"),
                                             "destination": str(pc_root / "save-backup.dat")})]),
        Reply("Listed and moved."),
    ]
    # A hub: its own disk is off limits, so PC access only arrives with the node.
    with Server(tmp_path, replies, pc_access={"enabled": False}, apps={"enabled": False}) as hub_srv:
        mgr = hub_srv.app.state.node_hub
        status, info = hub_srv.call("GET", "/api/info")
        assert info["nodes"] == []
        # Nodes need a pairing token, and the token can't be used as an owner login.
        assert hub_srv.call("POST", "/api/node/hello", {"name": "x"})[0] == 401
        status, paired = hub_srv.call("POST", "/api/nodes/pair", {"name": "Test PC"})
        assert status == 201
        token = paired["token"]
        bad = {"Authorization": "Bearer cvn_wrong"}
        assert hub_srv.call("GET", "/api/node/poll", headers=bad)[0] == 401

        with RunningNode(tmp_path, hub_srv.port, token, pc_root):
            _wait_for(lambda: mgr.online())
            status, info = hub_srv.call("GET", "/api/info")
            assert info["pc_access"] is True and info["nodes"][0]["online"] is True

            # Files browser on the phone -> hub -> node -> PC
            status, listing = hub_srv.call("GET", "/api/pc/list?path=" + str(pc_root / "Games"))
            assert status == 200 and [e["name"] for e in listing["entries"]] == ["notes.txt", "save.dat"]
            status, prev = hub_srv.call("GET", "/api/pc/preview?path=" + str(pc_root / "Games" / "notes.txt"))
            assert prev["kind"] == "text" and "use fire" in prev["text"]
            status, raw = hub_srv.call("GET", "/pcfile?path=" + str(pc_root / "Games" / "notes.txt"))
            assert status == 200 and raw == "level 3 boss: use fire"
            assert hub_srv.call("GET", "/api/pc/list?path=/etc")[0] == 403   # the PC's own rules hold

            # Corvis (on the hub) uses the PC's tools; the PC's approval shows in the hub's chat.
            runs = hub_srv.app.state.manager
            conv = runs.store.create(hub_srv.workspace)
            run = runs.start(conv["id"], "tidy my games folder")

            def approval():
                return next((e for e in run.events if e["kind"] == "approval"), None)
            _wait_for(approval)
            ev = approval()
            assert ev["text"].startswith("On your PC (Test PC):")
            assert run.answer(ev["id"], True)
            wait_done(runs, conv["id"], timeout=15)
            results = [e["text"] for e in run.events if e["kind"] == "result"]
            assert "notes.txt" in results[0]
            assert (pc_root / "save-backup.dat").exists() and not (pc_root / "Games" / "save.dat").exists()

        # PC switched off: its tools disappear and Corvis is told.
        monkeypatch.setattr("corvis.nodes.ONLINE_GRACE", 0)
        _wait_for(lambda: not mgr.online())
        assert "OFFLINE" in mgr.status_line()
        status, err = hub_srv.call("GET", "/api/pc/list?path=" + str(pc_root))
        assert status >= 400


class NoLLM:
    native_tools = True


def test_node_tools_only_while_online(tmp_path):
    from corvis.config import build_agent
    hub = NodeHub(tmp_path / "hub")
    node_id, _ = hub.pair("PC")
    agent = build_agent(tmp_path, {"data_dir": str(tmp_path / "d"), "internet": {"enabled": False},
                                   "pc_access": {"enabled": False}, "apps": {"enabled": False}},
                        approver=lambda _: True, on_event=lambda *_: None, llm=NoLLM(), node_hub=hub)
    names = lambda: {s["function"]["name"] for s in agent.registry.schemas()}  # noqa: E731
    assert "pc_list" not in names()
    schema = {"type": "function", "function": {"name": "pc_list", "description": "List a folder.",
                                               "parameters": {"type": "object", "properties": {}}}}
    hub.hello(node_id, "PC", [schema], {})
    assert "pc_list" in names()
    desc = next(s for s in agent.registry.schemas() if s["function"]["name"] == "pc_list")
    assert desc["function"]["description"].startswith("On the owner's PC:")
    assert "The owner's PC:" in agent.messages[0]["content"]   # PC rules known even while it was off


def test_link_saves_token_outside_config(tmp_path, monkeypatch):
    class R:
        status_code = 200

        def raise_for_status(self):
            pass
    sent = {}
    monkeypatch.setattr("corvis.node.requests.post", lambda url, **kw: sent.update(url=url, **kw) or R())
    config = tmp_path / "config.yaml"
    config.write_text("name: Corvis\n# keep me\npc_access:\n  enabled: true\n")
    cfg = {"data_dir": str(tmp_path / "data")}
    url = link(cfg, config, "corvis-hub.tail.ts.net/", " cvn_abc ", "Gaming PC")
    assert url == "https://corvis-hub.tail.ts.net" and sent["url"].endswith("/api/node/hello")
    text = config.read_text()
    assert "cvn_abc" not in text and "# keep me" in text and "hub_url: https://corvis-hub.tail.ts.net" in text
    import yaml
    n = node_cfg({**cfg, **yaml.safe_load(text)})
    assert n == {"hub_url": "https://corvis-hub.tail.ts.net", "token": "cvn_abc", "name": "Gaming PC"}


def test_hub_remembers_pc_name_and_installer_keeps_links(tmp_path, capsys):
    import argparse

    from corvis.__main__ import cmd_pair_pc
    hub = NodeHub(tmp_path)
    node_id, _ = hub.pair("My PC")
    hub.hello(node_id, "Kody's PC", [], {})
    again = NodeHub(tmp_path)                      # e.g. after the hub restarts
    [n] = again.paired()
    assert n["name"] == "Kody's PC" and n["last_seen"] and not n["online"]
    cfg = {"data_dir": str(tmp_path)}
    cmd_pair_pc(argparse.Namespace(name="My PC", if_none=True), cfg)   # re-running the installer
    assert "already linked (Kody's PC)" in capsys.readouterr().out and len(again.paired()) == 1
    cmd_pair_pc(argparse.Namespace(name="Laptop", if_none=False), cfg)
    assert "cvn_" in capsys.readouterr().out and len(again.paired()) == 2


def test_cloud_model_status_is_cached(monkeypatch):
    from corvis.web import server
    calls = []

    class R:
        status_code = 200

        def json(self):
            return {"data": [{"id": "qwen/qwen3-coder"}]}
    monkeypatch.setattr(server.requests, "get", lambda url, timeout: calls.append(url) or R())
    server._model_cache.clear()
    cfg = {"llm": {"base_url": "https://openrouter.ai/api/v1", "model": "qwen/qwen3-coder"}}
    a, b = server.model_status(cfg), server.model_status(cfg)
    assert a == b and a["cloud"] and a["installed"] and len(calls) == 1
    local = {"llm": {"base_url": "http://localhost:11434/v1", "model": "qwen3:8b"}}
    server.model_status(local), server.model_status(local)
    assert len(calls) == 3                            # local checks stay live


def test_first_run_copies_example_config_but_never_overwrites(tmp_path, monkeypatch):
    from corvis import config as config_mod
    monkeypatch.setattr(config_mod, "CORVIS_HOME", tmp_path)
    monkeypatch.setattr(config_mod, "DEFAULT_CONFIG", tmp_path / "config.yaml")
    (tmp_path / "config.example.yaml").write_text("name: Corvis\n")
    assert config_mod.load_config() == {"name": "Corvis"}
    (tmp_path / "config.yaml").write_text("name: Corvis\npersonality: mine\n")
    (tmp_path / "config.example.yaml").write_text("name: Changed\n")      # a newer version unzipped
    assert config_mod.load_config()["personality"] == "mine"
