"""Connectors (MCP servers) and plugins (skills, slash commands, connectors, tools)."""
from __future__ import annotations

import io
import json
import sys
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from corvis import connectors as cm
from corvis.config import build_agent
from corvis.llm import Reply
from corvis.mcp_client import HttpTransport, MCPClient, MCPError, StdioTransport
from corvis.plugin_store import NeedsCodeApproval, PluginError, PluginStore
from corvis.web.server import create_app

FAKE = str(Path(__file__).with_name("fake_mcp_server.py"))
STDIO = {"name": "Notes App", "kind": "stdio", "command": sys.executable, "args": ["-I", FAKE]}


class LLM:
    model, native_tools = "fake", True

    def chat(self, messages, tools=None):
        return Reply("ok")


# --- the MCP client -----------------------------------------------------------------------

def test_stdio_client_lists_pages_and_calls_tools():
    client = MCPClient(StdioTransport(sys.executable, ["-I", FAKE]))
    try:
        client.connect()
        assert client.server_info["name"] == "fake"
        assert [t["name"] for t in client.list_tools()] == ["echo", "add_note", "fail"]  # both pages
        assert client.call_tool("echo", {"text": "hi"}) == "hi"
        assert client.call_tool("fail", {}).startswith("ERROR: it broke")
    finally:
        client.close()


def test_missing_program_gives_a_clear_error():
    with pytest.raises(MCPError, match="Couldn't start"):
        StdioTransport("definitely-not-a-program-xyz")


class FakeHttpMCP(BaseHTTPRequestHandler):
    """Streamable HTTP: initialize answers as JSON, tool calls as a server-sent event stream."""
    seen: list = []

    def do_POST(self):
        msg = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeHttpMCP.seen.append((msg.get("method"), self.headers.get("Mcp-Session-Id"),
                                 self.headers.get("Authorization")))
        if "id" not in msg:
            self.send_response(202)
            self.end_headers()
            return
        if msg["method"] == "initialize":
            result = {"protocolVersion": "2025-06-18", "capabilities": {}, "serverInfo": {"name": "web", "version": "1"}}
            body = json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Mcp-Session-Id", "s-123")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if msg["method"] == "tools/list":
            result = {"tools": [{"name": "search.issues", "description": "Find issues",
                                 "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
                                 "annotations": {"readOnlyHint": True}}]}
        else:
            result = {"content": [{"type": "text", "text": f"found: {msg['params']['arguments']['q']}"}]}
        events = (b'event: message\ndata: {"jsonrpc":"2.0","method":"notifications/progress","params":{}}\n\n'
                  + b"data: " + json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": result}).encode() + b"\n\n")
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(events)))
        self.end_headers()
        self.wfile.write(events)

    def do_DELETE(self):
        self.send_response(200)
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.fixture
def http_server():
    FakeHttpMCP.seen = []
    srv = HTTPServer(("127.0.0.1", 0), FakeHttpMCP)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/mcp"
    srv.shutdown()


def test_http_client_handles_json_sse_and_sessions(http_server):
    client = MCPClient(HttpTransport(http_server, {"Authorization": "Bearer tok"}))
    client.connect()
    assert client.list_tools()[0]["name"] == "search.issues"
    assert client.call_tool("search.issues", {"q": "crash"}) == "found: crash"
    client.close()
    methods = [m for m, *_ in FakeHttpMCP.seen]
    assert methods == ["initialize", "notifications/initialized", "tools/list", "tools/call"]
    assert all(sid == "s-123" for m, sid, _ in FakeHttpMCP.seen[1:])     # session id reused
    assert all(auth == "Bearer tok" for *_, auth in FakeHttpMCP.seen)


# --- connectors ---------------------------------------------------------------------------

def test_connector_store_validates_and_hides_secrets(tmp_path):
    store = cm.ConnectorStore(tmp_path)
    with pytest.raises(ValueError):
        store.add({"name": "x", "kind": "http", "url": "http://example.com/mcp"})   # remote must be https
    c = store.add({"name": "GitHub", "kind": "http", "url": "https://api.example.com/mcp", "token": "ghp_secret"})
    store.add({"name": "GitHub", "kind": "http", "url": "https://other.example.com/mcp"})
    assert [x["slug"] for x in store.list()] == ["github", "github_2"]
    shown = cm.public(c)
    assert shown["has_token"] and "ghp_secret" not in json.dumps(shown)


def test_connector_tools_ask_before_changing_things(tmp_path):
    manager = cm.ConnectorManager(cm.ConnectorStore(tmp_path))
    manager.store.add(STDIO)
    asked = []
    answer = {"ok": False}

    def approver(prompt):
        asked.append(prompt)
        return answer["ok"]

    tools = manager.tools_for_agent(approver)
    try:
        assert set(tools) == {"mcp_notes_app__echo", "mcp_notes_app__add_note", "mcp_notes_app__fail"}
        assert tools["mcp_notes_app__echo"].func(text="read me") == "read me"        # read-only: no question
        assert asked == []
        assert "declined" in tools["mcp_notes_app__add_note"].func(note="buy milk")  # changes things: asks
        assert "add_note" in asked[0] and "buy milk" in asked[0]
        answer["ok"] = True
        assert tools["mcp_notes_app__add_note"].func(note="buy milk") == "saved (1 notes)"
        assert manager.status(manager.store.list()[0]["id"])["state"] == "connected"
    finally:
        manager.close_all()


def test_broken_connector_is_reported_not_fatal(tmp_path):
    manager = cm.ConnectorManager(cm.ConnectorStore(tmp_path))
    bad = manager.store.add({"name": "Broken", "kind": "stdio", "command": "no-such-program-xyz"})
    assert manager.tools_for_agent(lambda _: True) == {}
    assert manager.status(bad["id"])["state"] == "error"


def test_long_tool_names_stay_valid():
    name = cm.tool_name("a" * 24, "really.long/tool name " * 5)
    assert len(name) <= 64 and name.startswith("mcp_") and all(c.isalnum() or c in "_-" for c in name)


# --- plugins ------------------------------------------------------------------------------

def make_plugin(root: Path, name="review-kit", code=False) -> Path:
    p = root / name
    (p / ".claude-plugin").mkdir(parents=True)
    (p / ".claude-plugin" / "plugin.json").write_text(json.dumps(
        {"name": name, "version": "1.2.0", "description": "Code review helpers", "author": {"name": "Tony"}}))
    (p / "skills" / "security-review").mkdir(parents=True)
    (p / "skills" / "security-review" / "SKILL.md").write_text(
        "---\nname: security-review\ndescription: Check code for security problems\n---\n"
        "1. Look for injection.\n2. Check secrets.\n")
    (p / "skills" / "security-review" / "checklist.md").write_text("- OWASP top 10\n")
    (p / "commands").mkdir()
    (p / "commands" / "review.md").write_text(
        "---\ndescription: Review a file\nargument-hint: <file>\n---\nReview $ARGUMENTS carefully. Start with $1.\n")
    (p / ".mcp.json").write_text(json.dumps({"mcpServers": {"notes": {
        "command": sys.executable, "args": ["-I", "${CLAUDE_PLUGIN_ROOT}/server.py"]}}}))
    (p / "server.py").write_text(Path(FAKE).read_text())
    if code:
        (p / "tools").mkdir()
        (p / "tools" / "hello.py").write_text(
            "from corvis.tools.base import Tool, params\n"
            "def register(reg, ctx):\n"
            "    reg.register(Tool('plugin_hello', 'Say hi', params(['who'], who={'type':'string'}),"
            " lambda who: f'hi {who}'))\n")
    return p


def test_install_plugin_from_folder_reads_everything(tmp_path):
    store = PluginStore(tmp_path / "data")
    info = store.install(str(make_plugin(tmp_path / "src")))
    assert info["name"] == "review-kit" and info["version"] == "1.2.0" and info["author"] == "Tony"
    assert info["skills"] == ["security-review"] and info["commands"] == ["review"]
    assert info["connectors"] == ["notes"]
    conn = store.connectors()[0]
    assert conn["source"] == "plugin:review-kit" and conn["args"][1].endswith("review-kit/server.py".replace("/", "/"))
    text = store.expand_command("/review app.py now")
    assert "Review app.py now carefully. Start with app.py." in text and "review-kit plugin" in text
    assert store.expand_command("/unknown x") is None and store.expand_command("hello") is None
    store.set_enabled("review-kit", False)
    assert store.skills() == [] and store.connectors() == [] and store.expand_command("/review x") is None


def test_plugins_with_code_need_approval(tmp_path):
    store = PluginStore(tmp_path / "data")
    src = make_plugin(tmp_path / "src", code=True)
    with pytest.raises(NeedsCodeApproval, match="hello.py"):
        store.install(str(src))
    assert store.list() == []
    store.install(str(src), allow_code=True)
    assert store.describe("review-kit")["tools"] == ["hello"]


def test_install_from_zip_and_reject_unsafe_zips(tmp_path):
    src = make_plugin(tmp_path / "src")
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in src.rglob("*"):
            if f.is_file():
                z.write(f, f"review-kit-main/{f.relative_to(src)}")
    store = PluginStore(tmp_path / "data")
    assert store.install(zip_bytes=buf.getvalue())["name"] == "review-kit"
    evil = io.BytesIO()
    with zipfile.ZipFile(evil, "w") as z:
        z.writestr("../../escape.txt", "x")
    with pytest.raises(PluginError, match="Unsafe path"):
        store.install(zip_bytes=evil.getvalue())
    with pytest.raises(PluginError, match="isn't a plugin"):
        store.install(str(tmp_path))


def test_marketplace_lists_and_installs(tmp_path):
    market = tmp_path / "market"
    make_plugin(market / "plugins")
    (market / ".claude-plugin").mkdir(parents=True)
    (market / ".claude-plugin" / "marketplace.json").write_text(json.dumps({"name": "tonys-tools", "plugins": [
        {"name": "review-kit", "source": "./plugins/review-kit", "description": "Review helpers"},
        {"name": "sneaky", "source": "./../../etc"}]}))
    store = PluginStore(tmp_path / "data")
    added = store.add_marketplace(folder=market)
    assert added["name"] == "tonys-tools" and added["plugins"][0]["installed"] is False
    store.install_from_market("tonys-tools", "review-kit")
    assert store.market_plugins("tonys-tools")[0]["installed"] is True
    with pytest.raises(PluginError, match="outside"):
        store.install_from_market("tonys-tools", "sneaky")


def test_agent_gets_skills_plugin_tools_and_connectors(tmp_path):
    data = tmp_path / "data"
    PluginStore(data).install(str(make_plugin(tmp_path / "src", code=True)), allow_code=True)
    cm.shared(data).store.add(STDIO)
    cfg = {"data_dir": str(data), "memory": {"enabled": False}, "computer": {"enabled": False}}
    try:
        agent = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=LLM())
        names = {s["function"]["name"] for s in agent.registry.schemas()}
        assert {"use_skill", "plugin_hello", "mcp_notes_app__echo", "mcp_review_kit_notes__echo"} <= names
        system = agent.messages[0]["content"]
        assert "security-review (review-kit plugin): Check code for security problems" in system
        assert "Connectors:" in system
        assert "Look for injection" in agent.registry.run("use_skill", {"name": "security-review"})
        assert "checklist.md" in agent.registry.run("use_skill", {"name": "security-review"})
        assert agent.registry.run("plugin_hello", {"who": "Tony"}) == "hi Tony"

        from corvis.bots import BotStore
        writer = BotStore(data, "Corvis").create({"name": "Writer", "job": "Write.", "abilities": ["web"]})
        bot_agent = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=LLM(), bot=writer)
        bot_names = {s["function"]["name"] for s in bot_agent.registry.schemas()}
        assert not any(n.startswith("mcp_") for n in bot_names)   # no connectors ability
    finally:
        cm.shared(data).close_all()


# --- the app's API ------------------------------------------------------------------------

def test_connector_and_plugin_api(tmp_path):
    cfg = {"data_dir": str(tmp_path), "web": {"default_workspace": str(tmp_path / "ws")},
           "memory": {"enabled": False}, "computer": {"enabled": False}}
    app = create_app(cfg, tmp_path)
    h = {"X-Corvis": "1"}
    try:
        with TestClient(app, base_url="http://127.0.0.1") as c:
            r = c.get("/api/connectors", headers=h).json()
            assert r["connectors"] == [] and any(t["id"] == "github" for t in r["catalog"])
            r = c.post("/api/connectors", headers=h, json={**STDIO, "token": ""}).json()
            conn = next(x for x in r["connectors"] if x["id"] == r["added"])
            assert conn["status"]["state"] == "connected" and len(conn["tools"]) == 3
            assert [t["read_only"] for t in conn["tools"]] == [True, False, False]
            r = c.patch(f"/api/connectors/{conn['id']}", headers=h, json={"approval": "always"}).json()
            assert r["connectors"][0]["approval"] == "always"
            assert c.post("/api/connectors", headers=h, json={"template": "filesystem"}).status_code == 400
            r = c.delete(f"/api/connectors/{conn['id']}", headers=h).json()
            assert r["connectors"] == []

            src = make_plugin(tmp_path / "src", code=True)
            r = c.post("/api/plugins", headers=h, json={"source": str(src)})
            assert r.status_code == 409 and r.json()["needs_code_approval"]
            r = c.post("/api/plugins", headers=h, json={"source": str(src), "allow_code": True}).json()
            assert r["installed"] == "review-kit" and r["commands"][0]["name"] == "review"
            listed = c.get("/api/connectors", headers=h).json()["connectors"]
            assert listed[0]["source"] == "plugin:review-kit"
            assert c.delete(f"/api/connectors/{listed[0]['id']}", headers=h).status_code == 400
            assert c.patch("/api/plugins/review-kit", headers=h, json={"enabled": False}).json()["plugins"][0]["enabled"] is False
            assert c.delete("/api/plugins/review-kit", headers=h).json()["plugins"] == []
    finally:
        cm.shared(tmp_path).close_all()


def test_starter_marketplace_installs_from_folder(tmp_path):
    root = Path(__file__).resolve().parent.parent / "examples" / "marketplace"
    store = PluginStore(tmp_path)
    added = store.add_marketplace(str(root))
    assert added["name"] == "corvis-starter-market"
    info = store.install_from_market("corvis-starter-market", "corvis-starter")
    assert set(info["skills"]) == {"code-review", "debug-like-a-pro"}
    assert set(info["commands"]) == {"review", "explain", "plan"}
    assert "Review src/app.py using the code-review skill" in store.expand_command("/review src/app.py")
