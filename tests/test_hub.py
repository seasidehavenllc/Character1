"""Home PC hub: accounts, memory sync between devices, and Auto mode (PC online -> PC, offline -> device)."""

import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from corvis.account import Account, HubError
from corvis.bodies import ConsoleBody
from corvis.brain import Corvis
from corvis.hardware import DeviceInfo
from corvis.hub import HubStore, make_hub_server
from corvis.identity import Identity
from corvis.memory import MemoryStore
from corvis.models import ModelCatalog
from corvis.providers import parse_text_tool_calls
from corvis.workshop import Workshop


def serve(server):
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server


def fake_model_server(models, reply):
    """A stand-in for Ollama: lists `models` and answers every chat with `reply`."""

    class H(BaseHTTPRequestHandler):
        def _send(self, data):
            body = json.dumps(data).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            self._send({"object": "list", "data": [{"id": m, "object": "model"} for m in models]})

        def do_POST(self):
            req = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            self._send({"id": "x", "object": "chat.completion", "created": 0, "model": req["model"],
                        "choices": [{"index": 0, "finish_reason": "stop",
                                     "message": {"role": "assistant", "content": f"{reply} ({req['model']})"}}]})

        def log_message(self, *a):
            pass

    return serve(HTTPServer(("127.0.0.1", 0), H))


@pytest.fixture
def hub():
    pc_ollama = fake_model_server(["qwen2.5-coder:32b", "qwen2.5-coder:7b"], "from PC")
    hub = serve(make_hub_server(f"http://127.0.0.1:{pc_ollama.server_port}/v1", "127.0.0.1", 0,
                                store=HubStore(":memory:")))
    yield f"127.0.0.1:{hub.server_port}", hub
    hub.shutdown()
    pc_ollama.shutdown()


def device(tmp_path, name, hub_url=None, register=False, local_models=()):
    acct = Account(tmp_path / f"{name}.json")
    if hub_url:
        acct.sign_in(hub_url, "tony", "correct horse battery", register=register)
    phone_ollama = fake_model_server(local_models, f"from {name}") if local_models else None
    server = f"http://127.0.0.1:{phone_ollama.server_port}/v1" if phone_ollama else ""
    cat = ModelCatalog([], server, device=DeviceInfo("Linux", "arm64", 8, 8.0, "CPU only", "qwen2.5-coder:3b", ""),
                       account=acct)
    corvis = Corvis(Identity.load(), MemoryStore(":memory:"), ConsoleBody(), Workshop(tmp_path / name), cat,
                    account=acct)
    return corvis, phone_ollama


def test_accounts_reject_wrong_password(hub, tmp_path):
    url, _ = hub
    Account(tmp_path / "a.json").sign_in(url, "tony", "correct horse battery", register=True)
    with pytest.raises(HubError, match="Wrong username or password"):
        Account(tmp_path / "b.json").sign_in(url, "tony", "wrong password!!")
    with pytest.raises(HubError, match="taken"):
        Account(tmp_path / "c.json").sign_in(url, "TONY", "another password", register=True)


def test_memories_sync_between_devices(hub, tmp_path):
    url, _ = hub
    pc, _ = device(tmp_path, "pc", url, register=True)
    phone, _ = device(tmp_path, "phone", url)

    mid = pc.memory.add("Tony is building an Iron Man suit", "project", 5)
    pc.sync(force=True)
    assert phone.sync(force=True) == 1
    assert phone.memory.search("suit")[0].content == "Tony is building an Iron Man suit"

    pc.memory.forget(mid)                     # deletions sync too
    pc.sync(force=True)
    phone.sync(force=True)
    assert phone.memory.search("suit") == []


def test_other_accounts_cannot_see_your_memories(hub, tmp_path):
    url, _ = hub
    tony, _ = device(tmp_path, "tony", url, register=True)
    tony.memory.add("secret plans", "project", 5)
    tony.sync(force=True)
    other = Account(tmp_path / "pepper.json")
    other.sign_in(url, "pepper", "another password", register=True)
    store = MemoryStore(":memory:")
    other.sync(store)
    assert store.search("secret") == []


def test_auto_uses_home_pc_then_falls_back_to_phone(hub, tmp_path):
    url, hub_server = hub
    phone, phone_ollama = device(tmp_path, "phone", url, register=True, local_models=["qwen2.5-coder:3b"])
    assert phone.model.id == "auto"

    events = []
    reply = phone.chat("hello", on_event=events.append)
    assert reply == "from PC (qwen2.5-coder:32b)"     # PC's biggest model, reached through the hub
    assert "thinking on qwen2.5-coder:32b · Home PC" in events

    hub_server.shutdown()                            # the home PC goes offline
    hub_server.server_close()
    phone.catalog._home_checked = 0                  # don't wait for the 20s recheck
    reply = phone.chat("still there?", on_event=events.append)
    assert reply == "from phone (qwen2.5-coder:3b)"
    assert [t["text"] for t in phone.transcript][:2] == ["hello", "from PC (qwen2.5-coder:32b)"]
    phone_ollama.shutdown()


def test_brain_requires_sign_in(hub):
    import urllib.error
    import urllib.request

    url, _ = hub
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"http://{url}/brain/v1/models")
    assert e.value.code == 401


def test_parse_tool_calls_written_as_text():
    text = ('Sure!\n```json\n{"name": "write_file", "arguments": {"path": "a.py", "content": "x = {1: 2}"}}\n```\n'
            '<tool_call>{"name": "run_command", "arguments": "{\\"command\\": \\"python a.py\\"}"}</tool_call>\n'
            '{"name": "not_a_tool", "arguments": {}}')
    calls = parse_text_tool_calls(text, {"write_file", "run_command"})
    assert calls == [("write_file", {"path": "a.py", "content": "x = {1: 2}"}),
                     ("run_command", {"command": "python a.py"})]
