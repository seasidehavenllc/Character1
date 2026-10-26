"""Blueprint models: importing real 3D files, smooth shapes, blueprint files, the shape library,
finding models online (honestly), undo, and Corvis steering the hologram live."""
from __future__ import annotations

import io
import json
import math
import struct
import zipfile

import pytest
from starlette.testclient import TestClient

from corvis import blueprint_finder as finder
from corvis import blueprint_geom as geom
from corvis.blueprints import BlueprintStore, clean_part, volume
from corvis.config import build_agent
from corvis.llm import Reply
from corvis.meshes import MeshStore, ModelError, import_model, read_model, simplify, split_pieces
from corvis.shape_library import ShapeLibrary
from corvis.web.server import create_app

H = {"X-Corvis": "1"}


class LLM:
    model, native_tools = "fake", True

    def chat(self, messages, tools=None):
        return Reply("ok")


def cube_stl(size=10.0, offset=(0, 0, 0), binary=True) -> bytes:
    """A closed cube (12 triangles), z up, in 'millimetres'."""
    s, (ox, oy, oz) = size, offset
    v = [(ox + x * s, oy + y * s, oz + z * s) for x in (0, 1) for y in (0, 1) for z in (0, 1)]
    quads = [(0, 2, 3, 1), (4, 5, 7, 6), (0, 1, 5, 4), (2, 6, 7, 3), (0, 4, 6, 2), (1, 3, 7, 5)]
    tris = [t for a, b, c, d in quads for t in ((v[a], v[b], v[c]), (v[a], v[c], v[d]))]
    if not binary:
        body = "".join("facet normal 0 0 0\nouter loop\n" + "".join(f"vertex {x} {y} {z}\n" for x, y, z in t)
                       + "endloop\nendfacet\n" for t in tris)
        return f"solid cube\n{body}endsolid cube\n".encode()
    out = bytearray(b"cube".ljust(80, b" ")) + struct.pack("<I", len(tris))
    for t in tris:
        out += struct.pack("<12fH", 0, 0, 0, *[c for p in t for c in p], 0)
    return bytes(out)


def two_cubes() -> bytes:
    a, b = cube_stl(), cube_stl(offset=(30, 0, 0))
    n = struct.unpack("<I", a[80:84])[0] * 2
    return a[:80] + struct.pack("<I", n) + a[84:] + b[84:]


# --- reading models -----------------------------------------------------------------------

def test_reads_every_format_and_back():
    comps, fmt = read_model("cube.stl", cube_stl())
    assert fmt == "stl" and comps[0].triangles == 12 and len(comps[0].positions) == 8 * 3   # corners merged
    comps, _ = read_model("cube.stl", cube_stl(binary=False))
    assert comps[0].triangles == 12
    obj = b"o Left\nv 0 0 0\nv 1 0 0\nv 1 1 0\nv 0 1 0\nf 1 2 3 4\no Right\nv 2 0 0\nv 3 0 0\nv 3 1 0\nf 5/1/1 6/2/2 7/3/3\n"
    comps, _ = read_model("two.obj", obj)
    assert [c.name for c in comps] == ["Left", "Right"] and [c.triangles for c in comps] == [2, 1]
    ply = b"ply\nformat ascii 1.0\nelement vertex 3\nproperty float x\nproperty float y\nproperty float z\n" \
          b"element face 1\nproperty list uchar int vertex_indices\nend_header\n0 0 0\n1 0 0\n0 1 0\n3 0 1 2\n"
    assert read_model("t.ply", ply)[0][0].triangles == 1
    bp = BlueprintStore.__new__(BlueprintStore)
    rover = {"name": "Rover", "parts": [clean_part({"name": "Box", "size": [1, 2, 3]}),
                                        clean_part({"name": "Wheel", "shape": "cylinder", "size": [0.5, 0.2, 0], "position": [2, 0, 0]})]}
    for fmt in ("glb", "obj", "3mf", "stl"):
        data, name = geom.export(rover, fmt)
        comps, got = read_model(name, data)
        assert got == fmt
        if fmt != "stl":
            assert [c.name for c in comps] == ["Box", "Wheel"], fmt
    z = io.BytesIO()
    with zipfile.ZipFile(z, "w") as zf:
        zf.writestr("readme.txt", "hi")
        zf.writestr("models/cube.stl", cube_stl())
    assert read_model("download.zip", z.getvalue())[0][0].triangles == 12
    with pytest.raises(ModelError):
        read_model("notes.txt", b"just some words")
    with pytest.raises(ModelError):
        read_model("x.gltf", json.dumps({"asset": {"version": "2.0"}, "buffers": [{"uri": "x.bin"}]}).encode())


def test_import_splits_pieces_and_fixes_units_and_axes(tmp_path):
    store = MeshStore(tmp_path)
    parts, facts = import_model(store, "pair.stl", two_cubes())
    assert facts["components"] == 2 and facts["scale"] == 0.001     # 40 mm wide -> guessed millimetres
    assert facts["size_m"] == pytest.approx([0.04, 0.01, 0.01])
    assert all(p["shape"] == "mesh" and p["mesh"]["volume"] == pytest.approx(1e-6, rel=1e-3) for p in parts)
    assert min(p["position"][1] for p in parts) == pytest.approx(0.005)   # resting on the floor
    tall = cube_stl(size=10, binary=True)
    parts, facts = import_model(store, "tower.stl", tall, fit=("height", 330))
    assert facts["size_m"][1] == pytest.approx(330)
    assert store.meta(parts[0]["mesh"]["id"])["triangles"] == 12
    p = clean_part({**parts[0], "infill": 1})
    assert parts[0]["material"] == "pla" and parts[0]["infill"] == 0.2       # a guess, until someone sets it
    assert volume(p) == pytest.approx(330 ** 3, rel=1e-3)
    p["size"] = [x * 2 for x in p["size"]]
    assert volume(p) == pytest.approx(8 * 330 ** 3, rel=1e-3)          # stretching it scales the volume


def test_big_models_are_simplified():
    from array import array
    from corvis.blueprint_geom import _lathe
    from corvis.meshes import _weld
    rows = 120
    sphere = _lathe([(math.sin(math.pi * k / rows), -math.cos(math.pi * k / rows)) for k in range(rows + 1)], 160)
    c = _weld("Ball", array("f", sphere))
    assert c.triangles > 30000
    out = simplify([c], max_triangles=3000)
    assert 0 < sum(x.triangles for x in out) <= 3000
    lo, hi = out[0].bbox()
    assert hi[1] - lo[1] == pytest.approx(2, abs=0.1)   # still the same ball, just coarser


# --- smooth shapes ------------------------------------------------------------------------

def test_smooth_shapes_have_true_volumes():
    lathe = clean_part({"shape": "lathe", "profile": [[0, 0], [0.1, 0], [0.1, 0.2], [0, 0.2]]})
    assert volume(lathe) == pytest.approx(math.pi * 0.01 * 0.2)               # a cylinder, spun from a rectangle
    ext = clean_part({"shape": "extrude", "profile": [[0, 0], [1, 0], [0, 1]], "size": [2, 2, 0.5]})
    assert volume(ext) == pytest.approx(0.5 * 4 * 0.5)
    tube = clean_part({"shape": "tube", "size": [0.1, 1, 0.05]})
    assert volume(tube) == pytest.approx(math.pi * (0.01 - 0.0025))
    with pytest.raises(ValueError, match="profile"):
        clean_part({"shape": "extrude"})
    with pytest.raises(ValueError, match="mesh part"):
        clean_part({"shape": "mesh"})


def test_tessellation_matches_the_shapes():
    for raw, vol in (({"shape": "box", "size": [1, 2, 3]}, 6), ({"shape": "cylinder", "size": [1, 2, 0]}, 2 * math.pi),
                     ({"shape": "sphere", "size": [1, 0, 0]}, 4 / 3 * math.pi),
                     ({"shape": "lathe", "profile": [[0, 0], [1, 0], [1, 1], [0, 1]], "size": [2, 1, 2]}, math.pi)):
        tris = geom.local_triangles(clean_part(raw))
        v = sum((tris[i] * (tris[i + 4] * tris[i + 8] - tris[i + 5] * tris[i + 7])
                 - tris[i + 1] * (tris[i + 3] * tris[i + 8] - tris[i + 5] * tris[i + 6])
                 + tris[i + 2] * (tris[i + 3] * tris[i + 7] - tris[i + 4] * tris[i + 6])) / 6 for i in range(0, len(tris), 9))
        assert abs(v) == pytest.approx(vol, rel=0.01), raw["shape"]


# --- blueprint files ----------------------------------------------------------------------

def test_exports_are_real_files(tmp_path):
    bp = BlueprintStore(tmp_path).create(template="rover")
    stl, name = geom.export(bp, "stl")
    assert name == "Rover.stl" and len(stl) == 84 + 50 * struct.unpack("<I", stl[80:84])[0]
    zs = [struct.unpack_from("<f", stl, 84 + 50 * i + 12 + 4 * 3 * k + 8)[0] for i in range(10) for k in range(3)]
    assert min(zs) >= -0.01   # z up, on the bed, in millimetres
    with zipfile.ZipFile(io.BytesIO(geom.export(bp, "3mf")[0])) as z:
        assert 'unit="millimeter"' in z.read("3D/3dmodel.model").decode()
    glb = geom.export(bp, "glb")[0]
    assert glb[:4] == b"glTF" and struct.unpack_from("<I", glb, 8)[0] == len(glb)
    svg = geom.export(bp, "svg")[0].decode()
    assert "FRONT VIEW" in svg and "TOP VIEW" in svg and "SIDE VIEW" in svg and "SCALE 1:" in svg and "420.0 mm" in svg
    dxf = geom.export(bp, "dxf")[0].decode()
    assert dxf.count("\nLINE\n") > 20 and dxf.rstrip().endswith("EOF")
    with pytest.raises(ValueError):
        geom.export(bp, "exe")


# --- undo and live control ------------------------------------------------------------------

def test_undo_and_live_commands(tmp_path):
    store = BlueprintStore(tmp_path)
    bp = store.create(template="rover")
    first = len(bp["parts"])
    store.edit(bp["id"], remove=["LiDAR"])
    store.edit(bp["id"], remove=["Sensor mast"])
    assert store.can_undo(bp["id"]) == 2
    back = store.undo(bp["id"])
    assert len(back["parts"]) == first - 1 and back["version"] == 4
    assert len(store.undo(bp["id"])["parts"]) == first
    with pytest.raises(ValueError, match="Nothing to undo"):
        store.undo(bp["id"])
    store.command(bp["id"], "split", amount=0.8, say="Splitting")
    live = store.live()
    assert live["command"]["action"] == "split" and live["command"]["seq"] == 1 and live["versions"][bp["id"]] == 5
    assert [b["id"] for b in store.list()] == [bp["id"]]   # the live file isn't a blueprint


# --- the shape library ----------------------------------------------------------------------

def test_shape_library_learns_and_reuses(tmp_path):
    store, lib = MeshStore(tmp_path), ShapeLibrary(tmp_path)
    parts, _ = import_model(store, "wheel rim.stl", two_cubes())
    assert lib.learn(parts, "Wheel rim", {"site": "your file", "kind": "upload"}) == 2
    assert lib.learn(parts, "Wheel rim") == 0                       # the same pieces aren't filed twice
    hits = lib.search("rim")
    assert hits and hits[0]["learned_from"] == "Wheel rim"
    part = lib.to_part(hits[0]["id"], {"position": [1, 2, 3], "name": "Front rim"})
    assert part["shape"] == "mesh" and part["position"] == [1, 2, 3] and part["name"] == "Front rim"
    assert lib.get(hits[0]["id"])["uses"] == 1
    lib.add(clean_part({"shape": "torus", "size": [0.3, 0.05, 0]}), "Tyre", "rubber, wheel")
    assert lib.search("tyre")[0]["tags"] == ["rubber", "wheel"]


# --- finding models online, honestly --------------------------------------------------------

def test_honesty_rules():
    assert "classified" in finder.assess("F-35 blueprints")["notes"][0].lower()
    assert "factory cad" in finder.assess("Lamborghini Aventador")["notes"][0].lower()
    assert finder.assess("3d printed pistol frame")["blocked"]
    assert finder.assess("ghost gun receiver")["blocked"]
    assert not finder.assess("nerf gun blaster")["blocked"]
    assert not finder.assess("Eiffel Tower")["blocked"] and not finder.assess("Eiffel Tower")["notes"]


class FakeResp:
    def __init__(self, data=None, status=200, body=b"", ctype="application/octet-stream", headers=None):
        self._data, self.status_code, self.body = data, status, body
        self.headers = {"Content-Type": ctype, **(headers or {})}
        self.is_redirect = status in (301, 302)

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise finder.requests.HTTPError(f"{self.status_code}")

    def iter_content(self, n):
        yield self.body

    def close(self):
        pass


COMMONS = {"query": {"pages": {"1": {"index": 1, "title": "File:Eiffel Tower (model).stl", "imageinfo": [{
    "url": "https://upload.wikimedia.org/eiffel.stl", "descriptionurl": "https://commons.wikimedia.org/wiki/File:Eiffel.stl",
    "size": 1234, "extmetadata": {"LicenseShortName": {"value": "CC BY-SA 4.0"}, "Artist": {"value": "<a href='x'>Jane</a>"}}}]}}}}


def test_find_reports_sources_and_problems(tmp_path, monkeypatch):
    def fake_get(url, **kw):
        if "wikimedia" in url:
            return FakeResp(COMMONS)
        return FakeResp(status=403)
    monkeypatch.setattr(finder.requests, "get", fake_get)
    monkeypatch.setattr(finder, "web_search", lambda q, cfg, limit=6: [
        {"title": "Eiffel on Printables", "url": "https://www.printables.com/model/1", "snippet": ""},
        {"title": "direct", "url": "https://example.com/files/tower.3mf", "snippet": ""}])
    r = finder.find("pull up the Eiffel Tower blueprint", {}, tmp_path)
    assert r["search"] == "Eiffel Tower"
    first = r["results"][0]
    assert first["site"] == "Wikimedia Commons" and first["license"] == "CC BY-SA 4.0" and first["author"] == "Jane"
    assert first["kind"] == "community"
    assert any(x["format"] == "3mf" for x in r["results"]) and r["pages"][0]["title"] == "Eiffel on Printables"
    assert any("NASA" in p for p in r["problems"])                 # failures are reported, not hidden
    monkeypatch.setattr(finder.requests, "get", lambda url, **kw: FakeResp({"query": {}}))
    monkeypatch.setattr(finder, "web_search", lambda q, cfg, limit=6: [])
    r = finder.find("Death Star", {}, tmp_path)
    assert not r["results"] and "couldn't find a downloadable 3D model" in r["notes"][-1]
    r = finder.find("Eiffel Tower", {"internet": {"enabled": False}}, tmp_path)
    assert "turned off" in r["problems"][0]
    assert finder.find("AR-15 lower receiver", {}, tmp_path)["blocked"]


def test_download_refuses_pages_and_private_addresses(monkeypatch):
    with pytest.raises(finder.WebError):
        finder.download("http://127.0.0.1/model.stl", {})
    monkeypatch.setattr(finder, "check_url", lambda url, allow=False: url)
    monkeypatch.setattr(finder.requests.Session, "get", lambda self, url, **kw: FakeResp(body=b"<html>", ctype="text/html"))
    with pytest.raises(finder.WebError, match="web page"):
        finder.download("https://example.com/model", {})
    monkeypatch.setattr(finder.requests.Session, "get", lambda self, url, **kw: FakeResp(body=cube_stl()))
    name, data = finder.download("https://example.com/files/My%20Cube.stl", {})
    assert name == "My Cube.stl" and data == cube_stl()


# --- Corvis's tools -------------------------------------------------------------------------

def test_corvis_finds_imports_steers_and_exports(tmp_path, monkeypatch):
    cfg = {"data_dir": str(tmp_path / "data"), "memory": {"enabled": False}, "computer": {"enabled": False}}
    agent = build_agent(tmp_path / "ws", cfg, approver=lambda _: True, on_event=lambda *_: None, llm=LLM(),
                        conversation_id="c1")
    run = agent.registry.run
    monkeypatch.setattr(finder, "find", lambda q, c, d: {
        "query": q, "search": "Eiffel Tower", "blocked": None, "notes": [], "pages": [], "problems": [],
        "results": [{"title": "Eiffel Tower", "url": "https://x/e.stl", "page": "https://x", "site": "Wikimedia Commons",
                     "format": "stl", "kind": "community", "license": "CC BY-SA 4.0", "author": "Jane"}]})
    monkeypatch.setattr(finder, "download", lambda url, c: ("e.stl", two_cubes()))
    found = run("find_blueprint", {"query": "Eiffel Tower"})
    assert "1. Eiffel Tower [STL] from Wikimedia Commons — community-made; licence: CC BY-SA 4.0" in found
    out = run("import_blueprint", {"result": 1, "real_height_m": 330})
    assert "Pulled 'Eiffel Tower' into the hologram" in out and "community-made" in out and "2 new shapes" in out
    store = BlueprintStore(tmp_path / "data")
    bp = store.get(store.list()[0]["id"])
    assert bp["source"]["license"] == "CC BY-SA 4.0" and len(bp["parts"]) == 2
    assert store.live()["command"]["action"] == "open"
    assert "Done: split" in run("hologram", {"action": "split", "amount": 0.8})
    assert store.live()["command"]["amount"] == 0.8
    shapes = run("find_shapes", {"query": "eiffel"})
    sid = shapes.split("(id ")[1].split(";")[0]
    run("edit_blueprint", {"blueprint": bp["id"], "add_parts": [{"from_library": sid, "name": "Copy", "position": [500, 0, 0]}]})
    bp = store.get(bp["id"])
    assert any(p["name"] == "Copy" and p["shape"] == "mesh" for p in bp["parts"])
    assert store.live()["command"]["action"] == "highlight"
    assert "Exported" in run("export_blueprint", {"blueprint": bp["id"], "format": "stl"})
    assert (tmp_path / "ws" / "blueprint_exports" / "Eiffel_Tower.stl").stat().st_size > 84
    assert "Undid" in run("undo_blueprint", {"blueprint": bp["id"]})
    assert len(store.get(bp["id"])["parts"]) == 2


# --- the app --------------------------------------------------------------------------------

def test_model_api(tmp_path):
    cfg = {"data_dir": str(tmp_path), "web": {"default_workspace": str(tmp_path / "ws")},
           "memory": {"enabled": False}, "computer": {"enabled": False}}
    with TestClient(create_app(cfg, tmp_path), base_url="http://127.0.0.1") as c:
        r = c.post("/api/blueprints/import?name=two_cubes.stl", headers=H, content=two_cubes())
        assert r.status_code == 201
        d = r.json()
        bp = d["blueprint"]
        assert bp["name"] == "Two cubes" and bp["source"]["kind"] == "upload" and d["learned"] == 2
        aid = bp["parts"][0]["mesh"]["id"]
        a = c.get(f"/api/blueprints/assets/{aid}", headers=H)
        assert a.status_code == 200 and a.headers["x-content-type-options"] == "nosniff"
        assert c.get(f"/api/blueprints/assets/{aid}").status_code == 403      # the X-Corvis rule
        assert c.get("/api/blueprints/assets/../../x", headers=H).status_code == 404
        ex = c.get(f"/api/blueprints/{bp['id']}/export?format=svg", headers=H)
        assert ex.headers["content-disposition"] == 'attachment; filename="Two_cubes.svg"' and b"FRONT VIEW" in ex.content
        assert c.get(f"/api/blueprints/{bp['id']}/export?format=bad", headers=H).status_code == 400
        parts = bp["parts"][:1]
        saved = c.put(f"/api/blueprints/{bp['id']}", headers=H, json={"parts": parts, "version": 1}).json()
        assert saved["can_undo"] == 1
        back = c.post(f"/api/blueprints/{bp['id']}/undo", headers=H).json()
        assert len(back["blueprint"]["parts"]) == 2 and back["can_undo"] == 0
        shapes = c.get("/api/shapes?q=cubes", headers=H).json()["shapes"]
        assert len(shapes) == 2
        part = c.post(f"/api/shapes/{shapes[0]['id']}/use", headers=H).json()
        assert part["shape"] == "mesh"
        assert c.delete(f"/api/shapes/{shapes[0]['id']}", headers=H).json()["ok"]
        assert c.get("/api/blueprints/live", headers=H).json()["versions"][bp["id"]] == 3
        bad = c.post("/api/blueprints/import?name=x.stl", headers=H, content=b"nonsense")
        assert bad.status_code == 400
