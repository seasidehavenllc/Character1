"""Memory tests: facts, searching saved chats, automatic recall, and the agent wiring."""
from __future__ import annotations

import time
from pathlib import Path

from corvis.config import build_agent
from corvis.conversations.store import ConversationStore
from corvis.llm import Reply, ToolCall
from corvis.memory import ChatIndex, FactStore, Memory, chunk_text, tokenize


class FakeLLM:
    native_tools = True

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append([dict(m) for m in messages])
        return self.replies.pop(0)


def add_chat(store: ConversationStore, title: str, pairs: list[tuple[str, str]], age_days: float = 0):
    conv = store.create("C:/Games/Test")
    conv["title"] = title
    ts = time.time() - age_days * 86400
    for user, corvis in pairs:
        conv["messages"].append({"role": "user", "text": user, "ts": ts})
        conv["messages"].append({"role": "assistant", "text": corvis, "ts": ts})
    store.save(conv)
    return conv


def seeded(tmp_path: Path) -> tuple[Memory, dict, dict]:
    store = ConversationStore(tmp_path / "conversations")
    stamina = add_chat(store, "Stamina system", [
        ("Add stamina to the player that drains while sprinting",
         "Done. Stamina drains at 20 per second while sprinting and regenerates at 12 per second. "
         "The code is in Source/Player/StaminaComponent.cpp."),
    ], age_days=3)
    inventory = add_chat(store, "Inventory grid", [
        ("Make a grid inventory like Resident Evil",
         "Built a 6x8 grid inventory with item rotation in InventoryGrid.cs."),
    ], age_days=1)
    return Memory(tmp_path), stamina, inventory


def test_tokenize_and_chunk():
    assert tokenize("The Players are sprinting!") == ["player", "sprinting"]
    assert "c#" in tokenize("I prefer C# for Unity")
    assert tokenize("hi hello thanks") == []
    chunks = chunk_text("para one\n\n" + "x" * 1500)
    assert len(chunks) >= 3 and all(len(c) <= 700 for c in chunks)


def test_facts_add_dedupe_and_forget(tmp_path):
    facts = FactStore(tmp_path)
    f1, created = facts.add("My games live in D:/Games")
    assert created and f1["id"] == "m1"
    again, created = facts.add("my games live in d:/games")
    assert not created and again["id"] == "m1"
    facts.add("Prefers C# and Unity")
    assert "[m2] Prefers C# and Unity" in facts.block()
    assert facts.remove("m1")["text"] == "My games live in D:/Games"
    assert facts.remove("Unity")["id"] == "m2"  # unique partial match works too
    assert facts.remove("nothing like this") is None
    assert facts.block() == ""


def test_chat_search_ranks_and_excludes(tmp_path):
    memory, stamina, inventory = seeded(tmp_path)
    hits = memory.chats.search("how fast does stamina drain when sprinting?")
    assert hits[0]["chat_id"] == stamina["id"]
    assert "20 per second" in hits[0]["snippet"] or "drains" in hits[0]["snippet"]
    assert memory.chats.search("stamina", exclude=stamina["id"]) == []
    assert memory.chats.search("inventory grid")[0]["chat_id"] == inventory["id"]
    assert [c["id"] for c in memory.chats.recent()] == [inventory["id"], stamina["id"]]


def test_chat_index_sees_new_and_deleted_chats(tmp_path):
    memory, stamina, _ = seeded(tmp_path)
    assert memory.chats.search("stamina")
    (tmp_path / "conversations" / f"{stamina['id']}.json").unlink()
    assert memory.chats.search("stamina") == []
    store = ConversationStore(tmp_path / "conversations")
    add_chat(store, "Dash ability", [("Add a dash that costs stamina", "Dash added.")])
    assert memory.chats.search("dash")[0]["title"] == "Dash ability"


def test_read_chat(tmp_path):
    memory, stamina, _ = seeded(tmp_path)
    text = memory.chats.read(stamina["id"])
    assert text.startswith('Chat "Stamina system"')
    assert "You: Add stamina" in text and "Corvis: Done." in text
    part = memory.chats.read(stamina["id"], max_chars=40)
    assert "start=40" in part
    for bad in ("../x", "nope"):
        try:
            memory.chats.read(bad)
            raise AssertionError("expected KeyError")
        except KeyError:
            pass


def test_recall_is_strict(tmp_path):
    memory, stamina, _ = seeded(tmp_path)
    block, titles = memory.recall("the sprinting stamina feels too slow, tweak the drain")
    assert titles == ["Stamina system"] and stamina["id"] in block
    assert "Corvis replied: Done. Stamina drains at 20 per second" in block  # the answer comes along
    assert memory.recall("hi there!") == ("", [])
    assert memory.recall("what's the weather like in Boston")[0] == ""
    assert memory.recall("stamina drain", exclude=stamina["id"]) == ("", [])


def test_recall_leaves_unrelated_chats_alone(tmp_path):
    """Sharing a couple of words isn't enough; referring back (or a clear topic match) is."""
    memory = Memory(tmp_path)
    store = ConversationStore(tmp_path / "conversations")
    add_chat(store, "Why so slow", [("Why do you take a long time to respond? Images and config.yaml load fine",
                                     "The model is split between CPU and GPU; that's the slowdown.")])
    assert memory.recall("Says you can't see images, add the correct 7b in config.yaml") == ("", [])
    assert memory.recall("why are you slow to respond again, like last time?")[1] == ["Why so slow"]


def test_agent_gets_recall_and_facts(tmp_path):
    memory, stamina, _ = seeded(tmp_path)
    memory.facts.add("Owner's name is Kody")
    events = []
    llm = FakeLLM([Reply("ok"), Reply("ok again")])
    agent = build_agent(tmp_path / "ws" if (tmp_path / "ws").mkdir() is None else None,
                        {"data_dir": str(tmp_path), "internet": {"enabled": False}},
                        approver=lambda _: True, on_event=lambda k, t: events.append((k, t)), llm=llm)
    agent.run("make the stamina drain slower while sprinting")
    first = llm.seen[0]
    assert "Owner's name is Kody" in first[0]["content"]           # facts in the system prompt
    assert "Recalled from earlier chats" in first[-1]["content"]   # recall attached to the message
    assert any(k == "recall" and t.startswith("Stamina system") for k, t in events)

    memory.facts.add("Prefers metric units")                        # facts refresh every task
    agent.run("thanks")
    assert "Prefers metric units" in llm.seen[1][0]["content"]
    assert "Recalled" not in llm.seen[1][-1]["content"]


def test_memory_tools(tmp_path):
    memory, stamina, _ = seeded(tmp_path)
    llm = FakeLLM([
        Reply("", [ToolCall("1", "search_chats", {"query": "stamina sprint"}),
                   ToolCall("2", "read_chat", {"chat_id": stamina["id"]}),
                   ToolCall("3", "remember", {"fact": "Uses Unreal Engine 5"}),
                   ToolCall("4", "search_chats", {}),
                   ToolCall("5", "forget", {"memory_id": "m1"}),
                   ToolCall("6", "read_chat", {"chat_id": "missing"})]),
        Reply("done"),
    ])
    (tmp_path / "ws").mkdir()
    agent = build_agent(tmp_path / "ws", {"data_dir": str(tmp_path), "internet": {"enabled": False},
                                          "memory": {"auto_recall": False}},
                        approver=lambda _: True, on_event=lambda *_: None, llm=llm)
    agent.run("go")
    outs = [m["content"] for m in agent.messages if m["role"] == "tool"]
    assert "Stamina system" in outs[0]
    assert "StaminaComponent.cpp" in outs[1]
    assert "[m1]" in outs[2] and memory.facts.list() == []  # remembered, then forgotten
    assert "Recent chats" in outs[3]
    assert outs[4].startswith("Forgot [m1]")
    assert outs[5].startswith("ERROR")


def test_memory_can_be_turned_off(tmp_path):
    agent = build_agent(tmp_path, {"data_dir": str(tmp_path / "d"), "memory": {"enabled": False},
                                   "internet": {"enabled": False}},
                        approver=lambda _: True, on_event=lambda *_: None, llm=FakeLLM([]))
    assert "search_chats" not in agent.registry.tools
    assert agent.recall_provider is None and agent.context_provider is None
