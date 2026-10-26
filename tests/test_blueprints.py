"""Hologram blueprints: the store, the quick tests, Corvis's tools and the app's API."""
from __future__ import annotations

import pytest
from starlette.testclient import TestClient

from corvis import blueprint_sim as sim
from corvis.blueprints import TEMPLATES, BlueprintStore, describe, mass
from corvis.config import build_agent
from corvis.llm import Reply
from corvis.web.server import create_app


class LLM:
    model, native_tools = "fake", True

    def chat(self, messages, tools=None):
        return Reply("ok")


# --- the store ----------------------------------------------------------------------------

def test_templates_have_believable_masses(tmp_path):
    store = BlueprintStore(tmp_path)
    kg = {t: sum(mass(p) for p in store.create(template=t)["parts"]) for t in TEMPLATES if t != "blank"}
    assert 4 < kg["rover"] < 12
    assert 1 < kg["robot_arm"] < 6
    assert 0.3 < kg["drone"] < 1.5
    assert 0.1 < kg["arc_reactor"] < 2


def test_create_find_edit_delete(tmp_path):
    store = BlueprintStore(tmp_path)
    bp = store.create("Mark II", "rover")
    assert store.find("mark ii")["id"] == bp["id"]
    assert store.find("mark")["id"] == bp["id"]          # unique partial name
    with pytest.raises(KeyError, match="No blueprint called"):
        store.find("nothing like it")

    first = bp["parts"][0]["name"]
    bp = store.edit(bp["id"], add=[{"name": "Antenna", "shape": "cylinder", "size": [0.005, 0.3, 0],
                                    "position": [0, 0.4, 0], "material": "aluminium"}],
                    update=[{"part": first, "material": "titanium"}])
    assert bp["version"] == 2
    assert any(p["name"] == "Antenna" for p in bp["parts"])
    assert next(p for p in bp["parts"] if p["name"] == first)["material"] == "titanium"
    bp = store.edit(bp["id"], remove=["antenna"])
    assert not any(p["name"] == "Antenna" for p in bp["parts"])
    with pytest.raises(KeyError):
        store.edit(bp["id"], remove=["antenna"])

    store.delete(bp["id"])
    assert store.list() == []


def test_parts_are_cleaned_and_bad_input_refused(tmp_path):
    store = BlueprintStore(tmp_path)
    bp = store.create("Odd", parts=[{"name": "x" * 200, "size": [-1, "a"], "material": "Carbon Fibre", "infill": 9}])
    part = bp["parts"][0]
    assert len(part["name"]) <= 60 and part["shape"] == "box" and part["material"] == "carbon_fiber"
    assert all(s > 0 for s in part["size"]) and 0 < part["infill"] <= 1
    with pytest.raises(ValueError, match="Unknown shape"):
        store.create("x", parts=[{"shape": "blob"}])
    with pytest.raises(ValueError, match="Unknown material"):
        store.create("x", parts=[{"material": "cheese"}])
    with pytest.raises(ValueError, match="Unknown template"):
        store.create("x", "spaceship")
    with pytest.raises(KeyError):
        store.get("../../etc/passwd")


def test_save_refuses_a_stale_version(tmp_path):
    store = BlueprintStore(tmp_path)
    bp = store.create("Arm", "robot_arm")
    store.edit(bp["id"], remove=[bp["parts"][-1]["id"]])     # Corvis changes it meanwhile
    with pytest.raises(ValueError, match="changed since"):
        store.save(bp["id"], {"parts": bp["parts"]}, version=1)
    saved = store.save(bp["id"], {"name": "Arm v2", "parts": bp["parts"]}, version=2)
    assert saved["name"] == "Arm v2" and saved["version"] == 3


# --- quick tests --------------------------------------------------------------------------

def test_every_situation_reports_every_part(tmp_path):
    bp = BlueprintStore(tmp_path).create(template="drone")
    for situation in sim.SITUATIONS:
        result = sim.run(bp, situation)
        assert set(result["parts"]) == {p["id"] for p in bp["parts"]}
        assert result["headline"] and result["assumes"] and result["mass_kg"] > 0
        assert all(r["status"] in ("ok", "warn", "fail") for r in result["parts"].values())
    with pytest.raises(ValueError, match="Unknown test"):
        sim.run(bp, "lava")


def test_tests_respond_to_their_settings(tmp_path):
    rover = BlueprintStore(tmp_path).create(template="rover")
    worst = lambda r: max(x["ratio"] for x in r["parts"].values())
    assert worst(sim.run(rover, "drop", {"height_m": 15})) > worst(sim.run(rover, "drop", {"height_m": 0.3}))
    assert worst(sim.run(rover, "load", {"load_n": 5000})) > worst(sim.run(rover, "load", {"load_n": 10}))
    hot = sim.run(rover, "heat", {"ambient_c": 150, "extra_c": 200})
    assert any(r["status"] == "fail" for r in hot["parts"].values())
    calm, storm = sim.run(rover, "wind", {"speed_ms": 1}), sim.run(rover, "wind", {"speed_ms": 70})
    assert storm["force_n"] > calm["force_n"]
    assert sim.run(rover, "power", {"duty": 20})["runtime_h"] > sim.run(rover, "power", {"duty": 100})["runtime_h"]
    # out-of-range settings are clamped, not trusted
    assert sim.run(rover, "drop", {"height_m": 1e9})["parts"] == sim.run(rover, "drop", {"height_m": 20})["parts"]


# --- Corvis's tools -----------------------------------------------------------------------

def test_corvis_can_design_edit_and_test_blueprints(tmp_path):
    asked = []
    cfg = {"data_dir": str(tmp_path / "data"), "memory": {"enabled": False}, "computer": {"enabled": False}}
    agent = build_agent(tmp_path, cfg, approver=lambda p: asked.append(p) or True,
                        on_event=lambda *_: None, llm=LLM())
    names = {s["function"]["name"] for s in agent.registry.schemas()}
    assert {"open_blueprints", "create_blueprint", "edit_blueprint", "test_blueprint", "delete_blueprint"} <= names
    assert "open_blueprints" in agent.messages[0]["content"]

    run = agent.registry.run
    assert "Created blueprint 'Scout'" in run("create_blueprint", {"name": "Scout", "template": "rover"})
    assert "Opening the Scout blueprint" in run("open_blueprints", {"blueprint": "scout"})
    assert "added 1" in run("edit_blueprint", {"blueprint": "Scout", "add_parts": [
        {"name": "Mast", "shape": "cylinder", "size": [0.01, 0.4, 0], "position": [0, 0.5, 0]}]})
    assert "Mast" in run("show_blueprint", {"blueprint": "Scout"})
    report = run("test_blueprint", {"blueprint": "Scout", "situation": "drop", "settings": {"height_m": 3}})
    assert "Parts closest to their limits" in report and "Assumes" in report
    assert run("open_blueprints", {"blueprint": "nope"}).startswith("ERROR")

    assert not asked
    run("delete_blueprint", {"blueprint": "Scout"})
    assert asked                                            # deleting asks the owner first
    assert BlueprintStore(tmp_path / "data").list() == []


def test_blueprint_tools_can_be_turned_off(tmp_path):
    cfg = {"data_dir": str(tmp_path / "data"), "memory": {"enabled": False}, "computer": {"enabled": False},
           "blueprints": {"enabled": False}}
    agent = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=LLM())
    assert not any("blueprint" in s["function"]["name"] for s in agent.registry.schemas())


# --- the app ------------------------------------------------------------------------------

def test_blueprint_api_and_page(tmp_path):
    cfg = {"data_dir": str(tmp_path), "web": {"default_workspace": str(tmp_path / "ws")},
           "memory": {"enabled": False}, "computer": {"enabled": False}}
    h = {"X-Corvis": "1"}
    with TestClient(create_app(cfg, tmp_path), base_url="http://127.0.0.1") as c:
        page = c.get("/blueprints")
        assert page.status_code == 200 and "holo" in page.text
        assert "http" not in page.text.split("importmap")[1].split("</script>")[0]   # no CDN
        assert c.get("/static/vendor/three/three.module.min.js").status_code == 200

        r = c.get("/api/blueprints", headers=h).json()
        assert r["blueprints"] == [] and "drone" in r["templates"] and "drop" in r["situations"]
        assert c.get("/api/blueprints").status_code in (401, 403)          # the X-Corvis rule

        made = c.post("/api/blueprints", headers=h, json={"name": "Bird", "template": "drone"})
        assert made.status_code == 201
        bp = made.json()["blueprint"]
        got = c.get(f"/api/blueprints/{bp['id']}", headers=h).json()
        assert got["blueprint"]["name"] == "Bird" and got["summary"]["mass_kg"] > 0

        parts = bp["parts"][:-1]
        saved = c.put(f"/api/blueprints/{bp['id']}", headers=h, json={"parts": parts, "version": 1})
        assert saved.status_code == 200 and len(saved.json()["blueprint"]["parts"]) == len(parts)
        stale = c.put(f"/api/blueprints/{bp['id']}", headers=h, json={"parts": parts, "version": 1})
        assert stale.status_code == 409

        test = c.post(f"/api/blueprints/{bp['id']}/test", headers=h,
                      json={"situation": "wind", "params": {"speed_ms": 20}}).json()
        assert test["situation"] == "wind" and test["parts"]
        assert c.post(f"/api/blueprints/{bp['id']}/test", headers=h, json={"situation": "x"}).status_code == 400

        assert c.delete(f"/api/blueprints/{bp['id']}", headers=h).json()["blueprints"] == []
        assert c.get(f"/api/blueprints/{bp['id']}", headers=h).status_code == 404
        assert c.get("/api/blueprints/notanid", headers=h).status_code == 404
