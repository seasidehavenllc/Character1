import json
from types import SimpleNamespace as NS

import pytest

from corvis.bodies import AvatarBody, ConsoleBody, RobotBody, SimulatedDriver
from corvis.brain import Corvis
from corvis.identity import Identity
from corvis.memory import MemoryStore
from corvis.models import ModelCatalog, ModelConfig
from corvis.providers import AnthropicProvider, OpenAIProvider
from corvis.workshop import Workshop


def test_identity_prompt_has_personality_expertise_and_body():
    prompt = Identity.load().system_prompt("TEST BODY", "")
    assert "Corvis" in prompt and "TEST BODY" in prompt and "sir" in prompt
    assert "Rust" in prompt and "learn" in prompt


def test_model_catalog_loads_claude_and_chatgpt():
    cat = ModelCatalog.load()
    providers = {m.provider for m in cat.list()}
    assert providers == {"anthropic", "openai"}
    assert cat.get(cat.default).provider == "anthropic"


def test_memory_add_search_forget():
    mem = MemoryStore(":memory:")
    mid = mem.add("The user's favourite drink is black coffee", "preference", 4)
    mem.add("Working on a robot arm project", "project", 3)
    assert mem.search("coffee")[0].id == mid
    assert mem.search('weird "quotes" (stuff)') == []
    assert mem.forget(mid) and not mem.search("coffee")


def test_avatar_builds_files(tmp_path):
    body = AvatarBody(Identity.load(), out_dir=tmp_path)
    paths = body.build()
    spec = json.loads(paths[0].read_text())
    assert spec["humanoid_form"]["accent_rgba"][2] == 1.0
    compile(paths[1].read_text(), "build_corvis.py", "exec")  # Blender script is valid Python


def test_robot_clamps_to_safety_limits():
    body = RobotBody(SimulatedDriver(), max_speed_mps=0.5, max_duration_s=5)
    out = body.execute("drive", {"linear_mps": 10, "angular_dps": 0, "duration_s": 60})
    assert "0.5 m/s" in out and "5.0s" in out


def test_workshop_files_and_confinement(tmp_path):
    ws = Workshop(tmp_path, approve=lambda cmd: True)
    ws.execute("write_file", {"path": "app/main.py", "content": "print('hi')\n"})
    ws.execute("edit_file", {"path": "app/main.py", "old_text": "hi", "new_text": "hello"})
    assert "app/main.py" in ws.execute("list_files", {"path": "."})
    assert "exit code 0" in ws.execute("run_command", {"command": "python app/main.py"})
    assert "hello" in ws.execute("run_command", {"command": "python app/main.py"})
    with pytest.raises(PermissionError):
        ws.execute("read_file", {"path": "../outside.txt"})


def test_workshop_commands_need_approval(tmp_path):
    ws = Workshop(tmp_path)  # default: deny
    assert "did not approve" in ws.execute("run_command", {"command": "echo hi"})


class ScriptedProvider:
    """Stands in for a real model: calls the given tools, then replies."""

    def __init__(self, model, effort, calls=()):
        self.model, self.calls, self.started = model, list(calls), 0

    def start(self, system, tools, transcript):
        self.started += 1
        self.transcript = list(transcript)

    def send(self, user_text, run_tool, on_event):
        results = [run_tool(name, args) for name, args in self.calls]
        return f"[{self.model.id}] " + " | ".join(r for r, _ in results)


def make_corvis(tmp_path, calls=(), body=None):
    catalog = ModelCatalog([ModelConfig("a", "A", "anthropic"), ModelConfig("b", "B", "openai")], "a")
    return Corvis(Identity.load(), MemoryStore(":memory:"), body or ConsoleBody(),
                  Workshop(tmp_path, approve=lambda c: True), catalog,
                  provider_factory=lambda m, e: ScriptedProvider(m, e, calls))


def test_corvis_learns_and_uses_workshop(tmp_path):
    corvis = make_corvis(tmp_path, calls=[
        ("write_file", {"path": "x.txt", "content": "data"}),
        ("learn", {"lesson": "Always pin dependency versions", "topic": "python"}),
    ])
    reply = corvis.chat("build it")
    assert (tmp_path / "x.txt").read_text() == "data"
    assert "Lesson stored" in reply
    assert corvis.memory.search("pin dependency")[0].category == "lesson"


def test_switching_models_keeps_conversation(tmp_path):
    corvis = make_corvis(tmp_path)
    corvis.chat("hello")
    corvis.switch_model("b")
    reply = corvis.chat("still there?")
    assert reply.startswith("[b]")
    assert [t["text"] for t in corvis.provider.transcript] == ["hello", corvis.transcript[1]["text"]]


def test_stop_word_halts_without_calling_model(tmp_path):
    driver = SimulatedDriver()
    corvis = make_corvis(tmp_path, body=RobotBody(driver))
    corvis.chat("STOP!")
    assert driver.log[-1] == "stop" and corvis.provider is None


# --- providers against fake API clients ----------------------------------------------

def _block(**kw):
    return NS(**kw)


class FakeAnthropic:
    def __init__(self, responses):
        self.responses, self.requests = list(responses), []
        self.beta = NS(messages=NS(stream=self._stream))

    def _stream(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})
        resp = self.responses.pop(0)

        class Ctx:
            def __enter__(s): return NS(get_final_message=lambda: resp)
            def __exit__(s, *a): return False
        return Ctx()


def test_anthropic_provider_tool_loop():
    client = FakeAnthropic([
        NS(stop_reason="tool_use", content=[_block(type="tool_use", id="t1", name="recall", input={"query": "x"})]),
        NS(stop_reason="end_turn", content=[_block(type="text", text="Done, sir.")]),
    ])
    p = AnthropicProvider(ModelConfig("claude-opus-5-5", "Opus", "anthropic", fallbacks=True, web_tools=True),
                          client=client)
    p.start("SYS", [{"name": "recall", "description": "d", "input_schema": {"type": "object"}}], [])
    calls = []
    reply = p.send("hi", lambda n, a: (calls.append(n) or "nothing", False), lambda e: None)
    assert reply == "Done, sir." and calls == ["recall"]
    req = client.requests[1]
    assert req["system"] == "SYS" and req["fallbacks"] == "default"
    assert req["messages"][-1]["content"][0]["tool_use_id"] == "t1"
    assert any(t.get("type") == "web_search_20260209" for t in req["tools"])


def test_openai_provider_tool_loop():
    call = NS(id="c1", function=NS(name="recall", arguments='{"query": "x"}'))
    responses = [
        NS(choices=[NS(message=NS(content=None, refusal=None, tool_calls=[call]))]),
        NS(choices=[NS(message=NS(content="All set.", refusal=None, tool_calls=None))]),
    ]
    requests = []
    client = NS(chat=NS(completions=NS(create=lambda **kw: requests.append({**kw, "messages": list(kw["messages"])}) or responses.pop(0))))
    p = OpenAIProvider(ModelConfig("gpt-5", "GPT", "openai"), client=client)
    p.start("SYS", [{"name": "recall", "description": "d", "input_schema": {"type": "object"}}], [])
    reply = p.send("hi", lambda n, a: (f"got {a['query']}", False), lambda e: None)
    assert reply == "All set."
    assert requests[1]["messages"][-1] == {"role": "tool", "tool_call_id": "c1", "content": "got x"}
    assert requests[0]["tools"][0]["function"]["name"] == "recall"
