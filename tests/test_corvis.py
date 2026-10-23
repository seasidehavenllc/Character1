import json
from types import SimpleNamespace

from corvis.bodies import AvatarBody, RobotBody, SimulatedDriver
from corvis.brain import Corvis
from corvis.identity import Identity
from corvis.memory import MemoryStore


def test_identity_prompt_has_personality_and_body():
    ident = Identity.load()
    prompt = ident.system_prompt("TEST BODY", "")
    assert "Corvis" in prompt and "TEST BODY" in prompt and "sir" in prompt


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
    driver = SimulatedDriver()
    body = RobotBody(driver, max_speed_mps=0.5, max_duration_s=5)
    out = body.execute("drive", {"linear_mps": 10, "angular_dps": 0, "duration_s": 60})
    assert "0.5 m/s" in out and "5.0s" in out


def test_stop_word_halts_without_calling_model():
    driver = SimulatedDriver()
    corvis = Corvis(Identity.load(), MemoryStore(":memory:"), RobotBody(driver), client=SimpleNamespace())
    corvis.chat("STOP!")
    assert driver.log[-1] == "stop"
