import json
import pytest
from corvis.beliefs import BeliefStore
from corvis.experience import ExperienceStore
from corvis.reasoning import should_use_deliberation, DecisionRecord
from corvis.model_router import ModelRouter
from corvis.llm import LLMError, Reply


def test_belief_add_search_and_revise(tmp_path):
    store = BeliefStore(tmp_path)
    belief = store.add("SQLite is sufficient for this prototype", confidence=.7,
                       evidence=[{"summary": "single-user workload", "source": "project analysis"}])
    assert store.search("SQLite prototype")[0]["id"] == belief["id"]
    updated = store.revise(belief["id"], confidence=.35, reason="load test showed contention")
    assert updated["confidence"] == .35
    assert len(updated["history"]) == 1
    assert "revisable claims" in store.context("SQLite")


def test_belief_delete(tmp_path):
    store = BeliefStore(tmp_path)
    b = store.add("test claim")
    assert store.delete(b["id"]) is True
    assert store.delete(b["id"]) is False


def test_experience_is_append_only_and_queryable(tmp_path):
    store = ExperienceStore(tmp_path)
    store.record("Fix browser startup", "browser executable missing", verified=True, lesson="install browser")
    assert store.recent(query="browser")[0]["verified"] is True


def test_reasoning_heuristic_and_record():
    assert should_use_deliberation("Compare these two architectures")
    assert not should_use_deliberation("Hi")
    record = DecisionRecord("q", "a", evidence=["source"], confidence=.8)
    assert record.to_dict()["confidence"] == .8


class FakeModel:
    def __init__(self, model, result=None, error=None):
        self.model, self.result, self.error = model, result, error
    def chat(self, messages, tools=None):
        if self.error: raise self.error
        return self.result


def test_router_falls_back_and_tracks_model():
    reply = Reply("ok")
    router = ModelRouter(FakeModel("primary", error=LLMError("offline")), [FakeModel("backup", result=reply)])
    assert router.chat([]).content == "ok"
    assert router.model == "backup"


def test_router_reports_all_failures():
    router = ModelRouter(FakeModel("a", error=LLMError("down")), [FakeModel("b", error=LLMError("down"))])
    with pytest.raises(LLMError, match="All configured"):
        router.chat([])


def test_belief_search_returns_best_matches_first(tmp_path):
    store = BeliefStore(tmp_path)
    best = store.add("Unreal builds need Visual Studio 2022 with C++ workloads")
    for i in range(12):
        store.add(f"unrelated note {i} about Unreal")
    assert store.search("Unreal Visual Studio C++ builds", limit=3)[0]["id"] == best["id"]


def test_agent_can_record_experiences_and_beliefs(tmp_path):
    from corvis.config import build_agent
    cfg = {"data_dir": str(tmp_path / "d")}
    llm = FakeModel("m", result=Reply("ok"))
    llm.native_tools = True
    agent = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=llm)
    run = agent.registry.run
    assert "verified" in run("record_experience", {"goal": "Fix login crash", "outcome": "tests pass",
                                                   "lesson": "token was None on first launch", "verified": True})
    assert ExperienceStore(tmp_path / "d").recent(query="login")[0]["lesson"] == "token was None on first launch"
    out = run("note_belief", {"claim": "This repo's tests need Python 3.11", "confidence": 0.9,
                              "evidence": "CI config pins 3.11", "source": "ci.yml"})
    bid = out.split()[2]
    assert "0.30" in run("revise_belief", {"belief_id": bid, "reason": "CI moved to 3.12", "confidence": 0.3})
    assert "record_experience" in agent.messages[0]["content"]


def test_fallback_models_from_config():
    from corvis.config import make_llm
    from corvis.llm import ChatLLM
    assert isinstance(make_llm({"model": "a"}), ChatLLM)
    router = make_llm({"model": "big", "api_key": "secret", "text_tool_mode": True,
                       "fallbacks": [{"base_url": "http://localhost:11434/v1", "model": "small"}]})
    assert isinstance(router, ModelRouter)
    assert [m.model for m in router.models] == ["big", "small"]
    assert router.models[1].api_key == "local"          # the primary's key isn't sent to the fallback
    assert router.native_tools is False


def test_private_and_tailscale_addresses_are_refused(monkeypatch):
    import socket
    from corvis import computer, internet
    for ip in ["100.101.102.103", "192.168.1.5", "127.0.0.1", "fd7a:115c:a1e0::1"]:
        fam = socket.AF_INET6 if ":" in ip else socket.AF_INET
        monkeypatch.setattr(socket, "getaddrinfo", lambda *a, ip=ip, fam=fam: [(fam, 1, 6, "", (ip, 80))])
        with pytest.raises(internet.WebError):
            internet.check_url("http://my-pc.tail1234.ts.net/")
        assert computer.public_url("http://my-pc.tail1234.ts.net/") is False
    monkeypatch.setattr(socket, "getaddrinfo", lambda *a: [(socket.AF_INET, 1, 6, "", ("93.184.215.14", 80))])
    assert internet.check_url("http://example.com/") == "http://example.com/"
