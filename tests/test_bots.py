"""Bots (Grok Bot-style teammates): jobs and abilities, hand-offs between bots, @mentions in a
shared thread, per-bot memory, routines on a schedule, and the bots' own computer."""
from __future__ import annotations

import datetime as dt
import functools
import http.server
import json
import threading
import time
from zoneinfo import ZoneInfo

import pytest

from corvis import computer as computer_mod
from corvis.bots import LEAD_ID, BotStore, tool_filter
from corvis.config import build_agent
from corvis.llm import Reply, ToolCall
from corvis.memory import FactStore
from corvis.routines import RoutineStore, Scheduler, check_schedule, describe, next_run

from tests.test_web import FakeLLM, Server, manager_with, wait_done

SALES_JOB = "Find new leads in the CRM and draft friendly follow-ups. Never send without approval."


class SeeingLLM(FakeLLM):
    """FakeLLM that also records what each call was sent."""

    def __init__(self, replies):
        super().__init__(replies)
        self.seen = []

    def chat(self, messages, tools=None):
        self.seen.append({"messages": [dict(m) for m in messages],
                          "tools": {t["function"]["name"] for t in tools or []}})
        return super().chat(messages, tools)


def manager_seeing(tmp_path, replies):
    mgr = manager_with(tmp_path, [])
    llm = SeeingLLM(replies)
    mgr.agent_factory = lambda ws, cfg, **kw: build_agent(ws, cfg, llm=llm, **kw)
    (tmp_path / "proj").mkdir(exist_ok=True)
    return mgr, llm


# --- the bot list ----------------------------------------------------------------------
def test_bot_store(tmp_path):
    bots = BotStore(tmp_path, "Corvis")
    assert [b["id"] for b in bots.list()] == [LEAD_ID]
    sales = bots.create({"name": "Sales Outbound", "job": SALES_JOB, "abilities": ["web", "computer", "nope"]})
    assert sales["abilities"] == ["web", "computer"] and sales["color"].startswith("#")
    with pytest.raises(ValueError):
        bots.create({"name": "sales outbound"})                  # names are unique
    with pytest.raises(ValueError):
        bots.create({"name": "Bad @name"})
    with pytest.raises(ValueError):
        bots.delete(LEAD_ID)                                     # the lead stays
    sales2 = bots.create({"name": "Sales"})
    assert bots.mentioned("hey @Sales Outbound, any leads?")["id"] == sales["id"]   # longest name wins
    assert bots.mentioned("@sales check this")["id"] == sales2["id"]
    assert bots.mentioned("email sales@acme.com") is None
    assert bots.update(LEAD_ID, {"job": "Run the team", "name": "Hacked"})["name"] == "Corvis"
    assert bots.get(LEAD_ID)["job"] == "Run the team"
    assert bots.delete(sales2["id"]) and bots.find("Sales") is None


def test_bots_only_get_the_abilities_they_were_given(tmp_path):
    cfg = {"data_dir": str(tmp_path / "d"), "internet": {"enabled": True}}
    bots = BotStore(tmp_path / "d", "Corvis")
    scout = bots.create({"name": "Talent Scout", "job": "Find candidates.", "abilities": ["web"]})
    llm = SeeingLLM([Reply("ok")])
    agent = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=llm, bot=scout)
    names = {s["function"]["name"] for s in agent.registry.schemas()}
    assert {"web_search", "remember", "ask_bot", "update_plan", "create_routine"} <= names
    assert not names & {"write_file", "run_command", "pc_list", "browser_open"}
    assert agent.registry.run("run_command", {"command": "echo hi"}).startswith("ERROR: unknown tool")
    system = agent.messages[0]["content"]
    assert system.startswith("You are Talent Scout, one of the owner's AI teammates")
    assert "Find candidates." in system and "- Corvis:" in system          # knows its team
    lead = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=llm)
    lead_names = {s["function"]["name"] for s in lead.registry.schemas()}
    assert {"write_file", "ask_bot"} <= lead_names
    if computer_mod.available():                     # browser tools exist only with Playwright
        assert "browser_open" in lead_names
    assert "- Talent Scout: Find candidates." in lead.messages[0]["content"]
    assert tool_filter({"abilities": []})("remember") is True


# --- per-bot memory ------------------------------------------------------------------
def test_each_bot_has_its_own_memory(tmp_path):
    facts = FactStore(tmp_path)
    facts.add("Owner's name is Kody")
    facts.add("Acme only signs annual contracts; Dana approves", bot="sales")
    facts.add("Bug reports go to Linear", bot="bugs")
    block = facts.block("sales")
    assert "Kody" in block and "Dana approves" in block and "Linear" not in block
    assert "What you've learned doing your job" in block
    assert facts.add("Acme only signs annual contracts; Dana approves", bot="sales")[1] is False


# --- hand-offs and shared threads ------------------------------------------------------
def test_lead_loops_in_a_teammate(tmp_path):
    mgr, llm = manager_seeing(tmp_path, [
        # Corvis (lead) hands the work over...
        Reply("", [ToolCall("1", "ask_bot", {"bot": "Sales Outbound", "request": "Acme replied on pricing. Draft an answer."})]),
        # ...Sales Outbound learns something and answers...
        Reply("", [ToolCall("2", "remember", {"fact": "Acme only signs annual; Dana approves"})]),
        Reply("Draft: Hi Dana, annual pricing is attached."),
        # ...and Corvis wraps up.
        Reply("Sales Outbound drafted the Acme reply."),
    ])
    sales = mgr.bots.create({"name": "Sales Outbound", "job": SALES_JOB, "abilities": ["web"]})
    conv = mgr.store.create(str(tmp_path / "proj"))
    run = mgr.start(conv["id"], "Acme wrote back about pricing, handle it")
    wait_done(mgr, conv["id"])
    kinds = [(e["kind"], e.get("bot_name")) for e in run.events]
    assert ("handoff", "Sales Outbound") in kinds and ("handoff_done", "Sales Outbound") in kinds
    assert ("memory", "Sales Outbound") in kinds
    assert [e["text"] for e in run.events if e["kind"] == "done"] == ["Sales Outbound drafted the Acme reply."]
    # the teammate worked with its own job and saw the request, not the chat
    sub_call = llm.seen[1]["messages"]
    assert SALES_JOB in sub_call[0]["content"]
    assert "Acme replied on pricing. Draft an answer." in sub_call[-1]["content"]
    assert "write_file" not in llm.seen[1]["tools"]                     # its abilities, not the lead's
    # what it learned went into its own memory
    from corvis.memory import Memory
    fact = Memory(tmp_path / "data").facts.list()[0]
    assert fact["bot"] == sales["id"]
    saved = mgr.store.get(conv["id"])["messages"][-1]
    assert any(e.get("bot") == sales["id"] for e in saved["events"])  # steps keep who did them


def test_mention_puts_a_bot_in_the_thread_and_others_catch_up(tmp_path):
    mgr, llm = manager_seeing(tmp_path, [Reply("Three leads are waiting: Acme, Bolt, Crane."),
                                         Reply("Got it, I'll prioritise Acme.")])
    sales = mgr.bots.create({"name": "Sales Outbound", "job": SALES_JOB})
    conv = mgr.store.create(str(tmp_path / "proj"))
    run = mgr.start(conv["id"], "@Sales Outbound what's waiting?")
    wait_done(mgr, conv["id"])
    assert run.bot["id"] == sales["id"] and run.events[0]["bot_name"] == "Sales Outbound"
    msgs = mgr.store.get(conv["id"])["messages"]
    assert msgs[0]["to"] == sales["id"] and msgs[1]["bot"] == sales["id"]
    mgr.start(conv["id"], "Corvis, which one first?")
    wait_done(mgr, conv["id"])
    lead_task = llm.seen[-1]["messages"][-1]["content"]
    assert "Sales Outbound: Three leads are waiting" in lead_task       # the lead caught up
    assert mgr.store.get(conv["id"])["messages"][-1]["bot"] == LEAD_ID
    stored = mgr.store.get(conv["id"])
    assert stored["bot_history"][sales["id"]] and stored["llm_history"]  # each keeps its own history


# --- routines --------------------------------------------------------------------------
DENVER = "America/Denver"


def ts(*a):
    return dt.datetime(*a, tzinfo=ZoneInfo(DENVER)).timestamp()


def test_schedule_math():
    fri_9am = ts(2026, 10, 23, 9, 0)
    weekday = check_schedule({"every": "weekday", "at": "8:00"})
    assert next_run(weekday, DENVER, fri_9am) == ts(2026, 10, 26, 8, 0)        # skips the weekend
    assert next_run(check_schedule({"every": "day", "at": "21:30"}), DENVER, fri_9am) == ts(2026, 10, 23, 21, 30)
    weekly = check_schedule({"every": "week", "day": "Friday", "at": "09:00"})
    assert next_run(weekly, DENVER, fri_9am) == ts(2026, 10, 30, 9, 0)          # not the same minute again
    assert next_run(check_schedule({"every": "hours", "hours": 4}), DENVER, fri_9am) == fri_9am + 4 * 3600
    # across the DST change (Nov 1 2026): still 8:00 local
    assert dt.datetime.fromtimestamp(next_run(weekday, DENVER, ts(2026, 10, 30, 9, 0)),
                                     ZoneInfo(DENVER)).hour == 8
    assert describe(weekly) == "Every Friday at 09:00" and describe(weekday) == "Weekdays at 08:00"
    for bad in ({"every": "month"}, {"every": "day", "at": "25:00"}, {"every": "hours", "hours": 0}):
        with pytest.raises(ValueError):
            check_schedule(bad)


def test_scheduler_fires_due_routines_once(tmp_path):
    store = RoutineStore(tmp_path)
    now = ts(2026, 10, 23, 7, 0)
    r = store.create("Morning leads", "sales", "Check the CRM for new leads", {"every": "day", "at": "08:00"},
                     DENVER, now=now)
    broken = store.create("Broken", "x", "boom", {"every": "hours", "hours": 1}, DENVER, now=now)
    fired = []

    def fire(rt):
        if rt["id"] == broken["id"]:
            raise RuntimeError("bot missing")
        fired.append(rt["id"])
        return "started"
    sched = Scheduler(store, fire)
    assert sched.tick(now + 60) == []
    three_days_late = ts(2026, 10, 26, 12, 0)                      # Corvis was off for days
    assert set(sched.tick(three_days_late)) == {r["id"], broken["id"]}
    assert fired == [r["id"]]                                      # once, not once per missed day
    assert store.get(r["id"])["next_run"] == ts(2026, 10, 27, 8, 0)
    assert store.get(broken["id"])["last_status"].startswith("Couldn't start")
    assert sched.tick(three_days_late + 5) == []


def test_routines_api_and_unread_results(tmp_path):
    with Server(tmp_path, [Reply("2 new leads: Acme and Bolt. Drafts are ready.")]) as s:
        status, bot = s.call("POST", "/api/bots", {"name": "Sales Outbound", "job": SALES_JOB, "abilities": ["web"]})
        assert status == 201
        assert s.call("POST", "/api/owner", {"tz": DENVER})[1]["tz"] == DENVER
        status, r = s.call("POST", "/api/routines", {"name": "Morning leads", "bot": bot["id"],
                                                     "prompt": "Check for new leads",
                                                     "schedule": {"every": "weekday", "at": "08:00"}})
        assert status == 201 and r["tz"] == DENVER and r["when"] == "Weekdays at 08:00"
        assert s.call("POST", "/api/routines", {"name": "x", "prompt": "y", "schedule": {"every": "year"}})[0] == 400
        status, out = s.call("POST", f"/api/routines/{r['id']}/run")
        cid = out["conversation_id"]
        wait_done(s.app.state.manager, cid)
        listed = {c["id"]: c for c in s.call("GET", "/api/conversations")[1]["conversations"]}
        assert listed[cid]["unread"] and listed[cid]["bot"] == bot["id"] and listed[cid]["routine"] == r["id"]
        conv = s.call("GET", f"/api/conversations/{cid}")[1]
        assert conv["title"] == "Morning leads" and conv["messages"][0]["routine"] == "Morning leads"
        assert conv["messages"][1]["bot"] == bot["id"]
        assert not s.call("GET", "/api/conversations")[1]["conversations"][0]["unread"]   # opened = read
        assert s.call("PATCH", f"/api/routines/{r['id']}", {"enabled": False})[1]["enabled"] is False
        assert s.call("DELETE", f"/api/bots/{bot['id']}")[0] == 200
        assert s.call("GET", "/api/routines")[1]["routines"] == []        # its routines went with it
        info = s.call("GET", "/api/info")[1]
        assert [b["id"] for b in info["bots"]] == [LEAD_ID] and "computer" in info["abilities"]


def test_create_routine_tool_needs_the_owners_ok(tmp_path):
    cfg = {"data_dir": str(tmp_path / "d"), "internet": {"enabled": False}}
    store = RoutineStore(tmp_path / "d")
    asked = []
    answers = iter([False, True])
    agent = build_agent(tmp_path, cfg, approver=lambda p: asked.append(p) or next(answers),
                        on_event=lambda *_: None, llm=SeeingLLM([]),
                        extra_state={"routines": store, "owner_tz": lambda: DENVER})
    args = {"name": "Standup notes", "request": "Summarise yesterday's commits", "every": "weekday", "at": "09:15"}
    assert "declined" in agent.registry.run("create_routine", args)
    out = agent.registry.run("create_routine", args)
    assert "Weekdays at 09:15 (America/Denver)" in out and len(store.list()) == 1
    assert "Weekdays at 09:15" in asked[0] and "Summarise yesterday's commits" in asked[0]
    assert "Standup notes" in agent.registry.run("list_routines", {})


# --- the bots' computer ------------------------------------------------------------------
SITE = {
    "/": "<html><head><title>Acme CRM</title></head><body><h1>Leads</h1><p>3 new leads.</p>"
         "<a href='/dana'>Dana at Acme</a><input type=password placeholder=Password>"
         "<button onclick=\"document.body.insertAdjacentHTML('beforeend','<p>SENT</p>')\">Send email</button>"
         "</body></html>",
    "/dana": "<html><head><title>Dana</title></head><body><p>Signs annual contracts only.</p></body></html>",
}


class SiteHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        page = SITE.get(self.path.split("?")[0])
        self.send_response(200 if page else 404)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write((page or "nope").encode())

    def log_message(self, *a):
        pass


@pytest.fixture
def site():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), SiteHandler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


def test_bot_uses_its_computer(tmp_path, site):
    pytest.importorskip("playwright")
    from corvis.computer import Computer
    comp = Computer(tmp_path / "d", allow_private=True)
    cfg = {"data_dir": str(tmp_path / "d"), "internet": {"enabled": False}}
    asked = []
    agent = build_agent(tmp_path, cfg, approver=lambda p: asked.append(p) or False, on_event=lambda *_: None,
                        llm=SeeingLLM([]), extra_state={"computer": comp})
    try:
        page = agent.registry.run("browser_open", {"url": site})
        assert "Page: Acme CRM" in page and "[1] a 'Dana at Acme'" in page
        assert "Signs annual contracts" in agent.registry.run("browser_click", {"element": 1})
        agent.registry.run("browser_open", {"url": site})
        assert "never type passwords" in agent.registry.run("browser_type", {"element": 2, "text": "hunter2"})
        assert "declined" in agent.registry.run("browser_click", {"element": 3})   # "Send email" asks first
        assert asked and "Send email" in asked[0]
        assert "SENT" not in agent.registry.run("browser_read", {})
        assert comp.screen()[:2] == b"\xff\xd8"
    finally:
        comp.close()


def test_computer_refuses_private_addresses(tmp_path, site):
    pytest.importorskip("playwright")
    from corvis.computer import Computer
    comp = Computer(tmp_path)
    try:
        with pytest.raises(PermissionError):
            comp.open("x", site)
        with pytest.raises(PermissionError):
            comp.owner("goto", url="http://192.168.1.1/")
    finally:
        comp.close()
