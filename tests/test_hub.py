"""Projects, Code sessions, Artifacts and Scheduled tasks (the Claude-style sections)."""
from __future__ import annotations

import datetime as dt
import subprocess
import time

import pytest
from starlette.testclient import TestClient

from corvis import code_sessions
from corvis.artifacts import ArtifactStore
from corvis.config import build_agent
from corvis.llm import Reply, ToolCall
from corvis.projects import KNOWLEDGE_IN_PROMPT, ProjectStore
from corvis.routines import RoutineStore, Scheduler, describe
from corvis.web.server import create_app
from tests.test_web import FakeLLM, manager_with, wait_done

H = {"X-Corvis": "1"}


def client(tmp_path, mgr=None):
    cfg = {"data_dir": str(tmp_path / "data"), "web": {"default_workspace": str(tmp_path / "ws")},
           "memory": {"enabled": False}, "computer": {"enabled": False}, "internet": {"enabled": False}}
    return TestClient(create_app(cfg, tmp_path / "data", manager=mgr), base_url="http://127.0.0.1")


# --- projects -------------------------------------------------------------------------------

def test_project_knowledge_goes_in_full_then_switches_to_search(tmp_path):
    store = ProjectStore(tmp_path)
    p = store.create("Rover", "A house-mapping rover", "Always use metric units.")
    p = store.add_text(p["id"], "Motor spec", "The drive motors are 12 V, 300 RPM, stall current 2.1 A.")
    block = store.prompt_block(p)
    assert "Always use metric units." in block and "stall current 2.1 A" in block and '<document name="Motor spec.md">' in block
    big = "filler words about nothing. " * (KNOWLEDGE_IN_PROMPT // 25)
    p = store.add_text(p["id"], "Datasheet", big + " The LiDAR spins at 600 RPM.")
    block = store.prompt_block(p)
    assert "stall current" not in block and "search_project_knowledge" in block
    hits = store.search(p, "lidar rpm")
    assert hits and "600 RPM" in hits[0]["text"]
    p = store.add_note(p["id"], "Wheels are 120 mm.")
    assert "Wheels are 120 mm." in store.prompt_block(p)
    with pytest.raises(ValueError):
        store.create("   ")
    with pytest.raises(KeyError):
        store.get("../../x")


def test_project_chat_gets_instructions_and_tools(tmp_path):
    projects = ProjectStore(tmp_path / "data")
    p = projects.create("Arm", instructions="Reply in pirate speak.")
    mgr = manager_with(tmp_path, [
        Reply("", [ToolCall("1", "save_project_memory", {"note": "Servos are MG996R."}),
                   ToolCall("2", "create_artifact", {"title": "Arm controller", "type": "code", "language": "python",
                                                     "content": "print('arm')"})]),
        Reply("Arr, done."),
    ])
    (tmp_path / "ws").mkdir()
    conv = mgr.store.create(str(tmp_path / "ws"), project=p["id"])
    mgr.start(conv["id"], "set it up")
    run = wait_done(mgr, conv["id"])
    agent = mgr.agents[conv["id"]]
    assert "Reply in pirate speak." in agent.messages[0]["content"]
    assert any(e["kind"] == "memory" for e in run.events)
    assert projects.get(p["id"])["notes"][0]["text"] == "Servos are MG996R."
    arts = ArtifactStore(tmp_path / "data").list(project=p["id"])
    assert arts[0]["title"] == "Arm controller" and arts[0]["conversation_id"] == conv["id"]
    assert any("artifact:" + arts[0]["id"] in e["text"] for e in run.events if e["kind"] == "result")


def test_chats_outside_projects_have_no_project_tools(tmp_path):
    cfg = {"data_dir": str(tmp_path / "data"), "memory": {"enabled": False}, "computer": {"enabled": False}}
    agent = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=FakeLLM([]))
    names = {s["function"]["name"] for s in agent.registry.schemas()}
    assert "create_artifact" in names and "save_project_memory" not in names


def test_project_api(tmp_path):
    with client(tmp_path) as c:
        p = c.post("/api/projects", headers=H, json={"name": "Game", "description": "Unreal shooter"}).json()
        p = c.post(f"/api/projects/{p['id']}/files", headers=H, json={"name": "Design", "text": "Sprint uses stamina."}).json()
        assert p["files"][0]["name"] == "Design.md" and p["knowledge"]["in_full"]
        up = c.post("/api/uploads?name=notes.txt", headers={**H, "Content-Type": "text/plain"}, content=b"jump height 2m").json()
        p = c.post(f"/api/projects/{p['id']}/files", headers=H, json={"attachment": up["id"]}).json()
        assert len(p["files"]) == 2
        assert c.get(f"/api/projects/{p['id']}/files/notes.txt", headers=H).json()["text"] == "jump height 2m"
        p = c.patch(f"/api/projects/{p['id']}", headers=H, json={"instructions": "Use C++20.", "starred": True}).json()
        assert p["instructions"] == "Use C++20." and p["starred"]
        chat = c.post(f"/api/projects/{p['id']}/chats", headers=H, json={}).json()
        assert chat["project"] == p["id"]
        other = c.post("/api/conversations", headers=H, json={}).json()
        moved = c.post(f"/api/conversations/{other['id']}/project", headers=H, json={"project": p["id"]}).json()
        assert moved["project"] == p["id"]
        full = c.get(f"/api/projects/{p['id']}", headers=H).json()
        assert {x["id"] for x in full["chats"]} == {chat["id"], other["id"]}
        listing = c.get("/api/projects", headers=H).json()["projects"]
        assert listing[0]["chat_count"] == 2
        r = c.delete(f"/api/projects/{p['id']}", headers=H).json()
        assert r["deleted_chats"] == 2
        assert c.get(f"/api/conversations/{chat['id']}", headers=H).status_code == 404
        assert c.get("/api/projects").status_code == 403   # the X-Corvis rule


# --- artifacts ------------------------------------------------------------------------------

def test_artifact_versions_and_edits(tmp_path):
    store = ArtifactStore(tmp_path)
    a = store.create("Clock", "html", "<p>tick</p>", conversation_id="c1")
    a = store.edit(a["id"], "tick", "tock", "Changed the word")
    a = store.add_version(a["id"], "<p>tock tock</p>")
    assert [v["content"] for v in a["versions"]] == ["<p>tick</p>", "<p>tock</p>", "<p>tock tock</p>"]
    with pytest.raises(ValueError, match="exactly once"):
        store.edit(a["id"], "tock", "x")
    with pytest.raises(ValueError, match="Unknown artifact type"):
        store.create("x", "exe", "data")
    assert store.find("clock")["id"] == a["id"]
    assert store.filename(store.create("My Script!", "code", "x=1", "python")) == "my-script.py"


def test_artifact_api_serves_pages_sandboxed(tmp_path):
    a = ArtifactStore(tmp_path / "data").create("Game", "html", "<script>alert(1)</script>")
    with client(tmp_path) as c:
        assert c.get("/api/artifacts", headers=H).json()["artifacts"][0]["id"] == a["id"]
        page = c.get(f"/artifact-view/{a['id']}")
        csp = page.headers["content-security-policy"]
        assert page.text == "<script>alert(1)</script>"
        assert csp.startswith("sandbox allow-scripts") and "allow-same-origin" not in csp and "connect-src 'none'" in csp
        assert page.headers["x-frame-options"] == "SAMEORIGIN"
        dl = c.get(f"/api/artifacts/{a['id']}/download", headers=H)
        assert dl.headers["content-disposition"].startswith("attachment") and dl.headers["content-type"] == "application/octet-stream"
        r = c.patch(f"/api/artifacts/{a['id']}", headers=H, json={"title": "Game 2", "content": "<p>new</p>"}).json()
        assert r["title"] == "Game 2" and r["versions"] == 2
        assert c.get(f"/artifact-view/{a['id']}?v=1").text == "<script>alert(1)</script>"
        assert c.delete(f"/api/artifacts/{a['id']}", headers=H).json()["ok"]
        assert c.get(f"/artifact-view/{a['id']}").status_code == 404


# --- code sessions --------------------------------------------------------------------------

def make_repo(path):
    path.mkdir()
    for args in (["init", "-q", "-b", "main"], ["config", "user.email", "t@example.com"], ["config", "user.name", "T"]):
        subprocess.run(["git", *args], cwd=path, check=True)
    (path / "app.py").write_text("print('hi')\n")
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "start"], cwd=path, check=True)


def test_code_session_tracks_changes_and_commits(tmp_path):
    repo = tmp_path / "repo"
    make_repo(repo)
    info = code_sessions.start(repo, "Add health check", new_branch=True)
    assert info["git"] and info["made_branch"] and info["branch"].startswith("corvis/add-health-check-")
    (repo / "app.py").write_text("print('hello')\n")
    (repo / "health.py").write_text("def ok():\n    return True\n")
    d = code_sessions.diff(repo, info)
    by = {f["path"]: f for f in d["files"]}
    assert by["app.py"]["status"] == "modified" and "+print('hello')" in by["app.py"]["patch"]
    assert by["health.py"]["status"] == "added" and by["health.py"]["added"] == 2
    assert code_sessions.stat(repo, info) == {"files": 2, "added": 3, "removed": 1}
    code_sessions.commit(repo, "Add health check")
    d = code_sessions.diff(repo, info)          # still shows everything since the session began
    assert {f["path"] for f in d["files"]} == {"app.py", "health.py"}
    with pytest.raises(ValueError):
        code_sessions.commit(repo, "")
    plain = tmp_path / "plain"
    plain.mkdir()
    assert code_sessions.start(plain)["git"] is False


def test_code_session_api(tmp_path):
    repo = tmp_path / "repo"
    make_repo(repo)
    with client(tmp_path) as c:
        s = c.post("/api/code/sessions", headers=H, json={"folder": str(repo), "prompt": "Fix it", "branch": False}).json()
        assert s["kind"] == "code" and s["code"]["branch"] == "main"
        (repo / "new.txt").write_text("x\n")
        listed = c.get("/api/code/sessions", headers=H).json()["sessions"]
        assert listed[0]["stat"]["files"] == 1
        assert c.get(f"/api/code/sessions/{s['id']}/diff", headers=H).json()["files"][0]["path"] == "new.txt"
        assert c.post(f"/api/code/sessions/{s['id']}/commit", headers=H, json={"message": "add new"}).json()["ok"]
        assert c.post("/api/code/sessions", headers=H, json={"folder": str(tmp_path / "nope")}).status_code == 400


# --- scheduled ------------------------------------------------------------------------------

def test_one_time_task_runs_once(tmp_path):
    store = RoutineStore(tmp_path)
    now = time.time()
    when = dt.datetime.fromtimestamp(now + 7200)
    r = store.create("Remind", "corvis", "Say hi", {"every": "once", "date": when.date().isoformat(),
                                                    "at": when.strftime("%H:%M")}, None, now=now)
    assert describe(r["schedule"]).startswith("Once,")
    fired = []
    sched = Scheduler(store, lambda x: fired.append(x["id"]) or "started")
    assert sched.tick(now) == []
    assert sched.tick(now + 7300) == [r["id"]] and fired == [r["id"]]
    assert store.get(r["id"])["enabled"] is False
    assert sched.tick(now + 99999) == []
    with pytest.raises(ValueError, match="passed"):
        store.update(r["id"], {"enabled": True}, now=now + 99999)
    past = dt.datetime.fromtimestamp(now - 3600)
    with pytest.raises(ValueError, match="already passed"):
        store.create("Late", "corvis", "x", {"every": "once", "date": past.date().isoformat(), "at": past.strftime("%H:%M")},
                     None, now=now)


def test_scheduled_api_and_run_history(tmp_path):
    mgr = manager_with(tmp_path, [Reply("Report ready."), Reply("Second report.")])
    with client(tmp_path, mgr) as c:
        t = c.post("/api/scheduled", headers=H, json={"name": "Daily", "prompt": "Summarise",
                                                      "schedule": {"every": "day", "at": "08:00"}, "fresh": True}).json()
        assert t["fresh"] is True
        first = c.post(f"/api/routines/{t['id']}/run", headers=H).json()["conversation_id"]
        wait_done(mgr, first)
        second = c.post(f"/api/routines/{t['id']}/run", headers=H).json()["conversation_id"]
        wait_done(mgr, second)
        assert first != second                       # a fresh chat for every run
        task = c.get("/api/scheduled", headers=H).json()["tasks"][0]
        assert [r["status"] for r in task["runs"]] == ["done", "done"]
        assert task["runs"][0]["conversation_id"] == second and task["runs"][1]["summary"] == "Report ready."
        assert c.patch(f"/api/scheduled/{t['id']}", headers=H, json={"enabled": False, "run": {"ts": 0}}).json()["enabled"] is False
        assert len(c.get("/api/scheduled", headers=H).json()["tasks"][0]["runs"]) == 2   # history can't be faked
