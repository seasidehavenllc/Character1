"""Blueprints: 3D designs Corvis and the owner build together, shown as holograms.

A blueprint is a named assembly of parts, each with a size, position, rotation, material and
optional power figures. Parts are basic solids (box, cylinder, sphere, cone, torus, capsule,
tube), smooth shapes made from a 2D outline (extrude: pushed out; lathe: spun around like a
vase or wheel rim), or real meshes imported from 3D model files (see meshes.py).
Stored as JSON in data/blueprints/. The hologram page (/blueprints) draws them, splits them
apart, edits them, and runs the quick tests in blueprint_sim.py.

Units: metres, degrees, kilograms, watts, watt-hours, degrees Celsius.
"""
from __future__ import annotations

import copy
import json
import math
import os
import re
import threading
import time
import uuid
from pathlib import Path

SHAPES = ("box", "cylinder", "sphere", "cone", "torus", "capsule", "tube", "extrude", "lathe", "mesh")
PROFILE_SHAPES = ("extrude", "lathe")
MAX_PARTS = 300
MAX_PROFILE_POINTS = 400
HISTORY_KEPT = 40

# density kg/m3, yield strength MPa, max service temperature C, impact toughness J/cm2 (rough)
MATERIALS = {
    "aluminum":     {"label": "Aluminium 6061", "density": 2700, "yield_mpa": 276, "max_temp_c": 170, "toughness": 3.0},
    "steel":        {"label": "Steel", "density": 7850, "yield_mpa": 250, "max_temp_c": 400, "toughness": 6.0},
    "titanium":     {"label": "Titanium", "density": 4430, "yield_mpa": 880, "max_temp_c": 400, "toughness": 5.0},
    "carbon_fiber": {"label": "Carbon fibre", "density": 1600, "yield_mpa": 600, "max_temp_c": 120, "toughness": 1.5},
    "abs":          {"label": "ABS plastic", "density": 1040, "yield_mpa": 40, "max_temp_c": 85, "toughness": 0.8},
    "pla":          {"label": "PLA (3D print)", "density": 1240, "yield_mpa": 50, "max_temp_c": 55, "toughness": 0.4},
    "nylon":        {"label": "Nylon", "density": 1150, "yield_mpa": 70, "max_temp_c": 100, "toughness": 1.2},
    "rubber":       {"label": "Rubber", "density": 1100, "yield_mpa": 15, "max_temp_c": 90, "toughness": 4.0},
    "wood":         {"label": "Plywood", "density": 600, "yield_mpa": 30, "max_temp_c": 150, "toughness": 0.6},
    "glass":        {"label": "Glass", "density": 2500, "yield_mpa": 35, "max_temp_c": 450, "toughness": 0.05},
    "copper":       {"label": "Copper", "density": 8960, "yield_mpa": 70, "max_temp_c": 200, "toughness": 4.0},
    "electronics":  {"label": "Electronics (PCB)", "density": 1850, "yield_mpa": 60, "max_temp_c": 85, "toughness": 0.3},
    "battery":      {"label": "Li-ion battery pack", "density": 2400, "yield_mpa": 20, "max_temp_c": 60, "toughness": 0.2},
}

_COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


def _num(value, lo: float, hi: float, default: float) -> float:
    try:
        v = float(value)
    except (TypeError, ValueError):
        return default
    if math.isnan(v) or math.isinf(v):
        return default
    return max(lo, min(hi, v))


def _vec(value, lo: float, hi: float, default: list[float]) -> list[float]:
    if not isinstance(value, (list, tuple)) or len(value) != 3:
        return list(default)
    return [round(_num(v, lo, hi, d), 5) for v, d in zip(value, default)]


def clean_part(raw: dict, existing_id: str | None = None) -> dict:
    """Validate one part: unknown shapes/materials are refused, out-of-range numbers are clamped."""
    if not isinstance(raw, dict):
        raise ValueError("Each part must be an object.")
    shape = raw.get("shape", "box")
    if shape not in SHAPES:
        raise ValueError(f"Unknown shape '{shape}'. Use one of: {', '.join(SHAPES)}.")
    material = str(raw.get("material") or "aluminum").strip().lower().replace(" ", "_").replace("-", "_")
    material = {"aluminium": "aluminum", "carbon_fibre": "carbon_fiber", "carbon": "carbon_fiber"}.get(material, material)
    if material not in MATERIALS:
        raise ValueError(f"Unknown material '{material}'. Use one of: {', '.join(MATERIALS)}.")
    profile, mesh_ref, natural = None, None, [0.1, 0.1, 0.1]
    if shape in PROFILE_SHAPES:
        profile = _profile(raw.get("profile"), shape)
        w, h = _bbox2(profile, shape)
        natural = [w, h, 0.05] if shape == "extrude" else [w * 2, h, w * 2]
    elif shape == "mesh":
        m = raw.get("mesh")
        if not isinstance(m, dict) or not re.fullmatch(r"[a-f0-9]{14}", str(m.get("id", ""))):
            raise ValueError("A mesh part needs an imported model (use import_blueprint or a shape from the library).")
        natural = _vec(m.get("bbox"), 1e-5, 100000, [0.1, 0.1, 0.1])
        mesh_ref = {"id": m["id"], "bbox": natural, "volume": max(_num(m.get("volume"), 0, 1e12, 0), 0)}
    part = {
        "id": str(raw.get("id") or existing_id or uuid.uuid4().hex[:8])[:16],
        "name": str(raw.get("name") or shape.title()).strip()[:60] or shape.title(),
        "shape": shape,
        "size": _vec(raw.get("size"), 0.0001, 5000, natural),
        "position": _vec(raw.get("position"), -5000, 5000, [0, 0, 0]),
        "rotation": _vec(raw.get("rotation"), -360, 360, [0, 0, 0]),
        "material": material,
        "group": str(raw.get("group") or "").strip()[:40],
        "power_w": round(_num(raw.get("power_w"), -100000, 100000, 0), 3),
        "battery_wh": round(_num(raw.get("battery_wh"), 0, 1000000, 0), 3),
        "infill": round(_num(raw.get("infill"), 0.05, 1, 1), 3),
        "notes": str(raw.get("notes") or "")[:500],
    }
    if raw.get("color") and _COLOR.match(str(raw["color"])):
        part["color"] = str(raw["color"])
    if profile is not None:
        part["profile"] = profile
    if mesh_ref is not None:
        part["mesh"] = mesh_ref
    return part


def _profile(raw, shape: str) -> list[list[float]]:
    """A 2D outline: [x, y] points (for a lathe, x is the distance from the spin axis)."""
    if not isinstance(raw, (list, tuple)) or len(raw) < (3 if shape == "extrude" else 2):
        raise ValueError(f"A {shape} part needs a 'profile': a list of [x, y] points in metres "
                         f"(at least {3 if shape == 'extrude' else 2}).")
    pts = []
    for pt in list(raw)[:MAX_PROFILE_POINTS]:
        if not isinstance(pt, (list, tuple)) or len(pt) != 2:
            raise ValueError("Each profile point must be [x, y].")
        x, y = _num(pt[0], -1000, 1000, 0), _num(pt[1], -1000, 1000, 0)
        pts.append([round(max(x, 0) if shape == "lathe" else x, 6), round(y, 6)])
    w, h = _bbox2(pts, shape)
    if w <= 0 or h <= 0:
        raise ValueError("That profile is flat. Its points need some width and some height.")
    return pts


def _bbox2(pts: list[list[float]], shape: str) -> tuple[float, float]:
    """Width (for a lathe: the largest radius) and height of an outline."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    return (max(xs) if shape == "lathe" else max(xs) - min(xs)), max(ys) - min(ys)


def _area_centroid(pts: list[list[float]]) -> tuple[float, float]:
    """Area and centroid x of a closed polygon (shoelace)."""
    a = cx = 0.0
    for (x1, y1), (x2, y2) in zip(pts, pts[1:] + pts[:1]):
        cross = x1 * y2 - x2 * y1
        a += cross
        cx += (x1 + x2) * cross
    a /= 2
    return abs(a), (cx / (6 * a) if a else 0.0)


def _profile_scale(part: dict) -> tuple[float, float, float]:
    """How much the outline is stretched to fit the part's size."""
    pts = part["profile"]
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    h = (max(ys) - min(ys)) or 1e-9
    if part["shape"] == "lathe":
        r = max(xs) or 1e-9
        return part["size"][0] / (2 * r), part["size"][1] / h, part["size"][2] / (2 * r)
    w = (max(xs) - min(xs)) or 1e-9
    return part["size"][0] / w, part["size"][1] / h, 1.0


def volume(part: dict) -> float:
    """Solid volume in m3 (x = width/radius, y = height/tube, z = depth, depending on shape)."""
    x, y, z = part["size"]
    shape = part["shape"]
    if shape == "box":
        v = x * y * z
    elif shape == "cylinder":
        v = math.pi * x * x * y
    elif shape == "sphere":
        v = 4 / 3 * math.pi * x ** 3
    elif shape == "cone":
        v = math.pi * x * x * y / 3
    elif shape == "torus":
        v = 2 * math.pi ** 2 * x * y * y
    elif shape == "tube":   # outer radius, height, inner radius
        v = math.pi * max(x * x - min(z, x * 0.999) ** 2, 0) * y
    elif shape == "extrude":
        sx, sy, _ = _profile_scale(part)
        v = _area_centroid(part["profile"])[0] * sx * sy * z
    elif shape == "lathe":   # Pappus: the outline's area swept round the axis
        pts = part["profile"]
        closed = pts + [[0.0, pts[-1][1]], [0.0, pts[0][1]]]
        area, cx = _area_centroid(closed)
        sx, sy, sz = _profile_scale(part)
        v = 2 * math.pi * abs(cx) * area * sx * sy * sz
    elif shape == "mesh":
        bx, by, bz = part["mesh"]["bbox"]
        v = part["mesh"]["volume"] * (x / bx) * (y / by) * (z / bz)
    else:  # capsule: cylinder of length y plus two half spheres
        v = math.pi * x * x * y + 4 / 3 * math.pi * x ** 3
    return v * part.get("infill", 1)


def mass(part: dict) -> float:
    return volume(part) * MATERIALS[part["material"]]["density"]


def footprint(part: dict) -> float:
    """Horizontal cross-section area in m2 (what carries vertical load)."""
    x, y, z = part["size"]
    shape = part["shape"]
    if shape == "box":
        return x * z
    if shape in ("cylinder", "cone", "sphere", "capsule"):
        return math.pi * x * x
    if shape == "tube":
        return math.pi * max(x * x - min(z, x * 0.999) ** 2, 0)
    if shape in ("extrude", "lathe", "mesh"):   # average cross-section
        return max(volume(part) / max(part.get("infill", 1), 1e-9) / max(y, 1e-9), 1e-9)
    return math.pi * ((x + y) ** 2 - max(x - y, 0) ** 2)  # torus lying flat


def frontal_area(part: dict) -> float:
    """Area facing a wind blowing along x, in m2."""
    x, y, z = part["size"]
    shape = part["shape"]
    if shape == "box":
        return y * z
    if shape in ("cylinder", "tube"):
        return 2 * x * y
    if shape in ("extrude", "lathe", "mesh"):
        return max(volume(part) / max(part.get("infill", 1), 1e-9) / max(x, 1e-9), 1e-9)
    if shape == "sphere":
        return math.pi * x * x
    if shape == "cone":
        return x * y
    if shape == "torus":
        return 2 * (x + y) * 2 * y
    return 2 * x * (y + 2 * x)


def half_extent(part: dict) -> list[float]:
    """Half the bounding-box size along x, y, z (ignores rotation)."""
    x, y, z = part["size"]
    shape = part["shape"]
    if shape == "box":
        return [x / 2, y / 2, z / 2]
    if shape in ("cylinder", "cone", "tube"):
        return [x, y / 2, x]
    if shape in ("extrude", "lathe", "mesh"):
        return [x / 2, y / 2, z / 2]
    if shape == "sphere":
        return [x, x, x]
    if shape == "torus":
        return [x + y, y, x + y]
    return [x, y / 2 + x, x]


TEMPLATES: dict[str, dict] = {
    "blank": {"name": "New blueprint", "description": "", "parts": []},
    "rover": {
        "name": "Rover", "description": "Four-wheel robot rover with a sensor mast.",
        "parts": [
            {"name": "Chassis", "shape": "box", "size": [0.40, 0.06, 0.28], "position": [0, 0.10, 0], "material": "aluminum", "group": "Frame", "infill": 0.08},
            {"name": "Battery pack", "shape": "box", "size": [0.16, 0.05, 0.10], "position": [0, 0.155, 0], "material": "battery", "group": "Power", "battery_wh": 74},
            {"name": "Controller", "shape": "box", "size": [0.10, 0.02, 0.07], "position": [0.11, 0.14, 0], "material": "electronics", "group": "Electronics", "power_w": 6},
            {"name": "Wheel FL", "shape": "cylinder", "size": [0.06, 0.04, 0], "position": [0.15, 0.06, 0.17], "rotation": [90, 0, 0], "material": "rubber", "group": "Drive"},
            {"name": "Wheel FR", "shape": "cylinder", "size": [0.06, 0.04, 0], "position": [0.15, 0.06, -0.17], "rotation": [90, 0, 0], "material": "rubber", "group": "Drive"},
            {"name": "Wheel RL", "shape": "cylinder", "size": [0.06, 0.04, 0], "position": [-0.15, 0.06, 0.17], "rotation": [90, 0, 0], "material": "rubber", "group": "Drive"},
            {"name": "Wheel RR", "shape": "cylinder", "size": [0.06, 0.04, 0], "position": [-0.15, 0.06, -0.17], "rotation": [90, 0, 0], "material": "rubber", "group": "Drive"},
            {"name": "Motor L", "shape": "cylinder", "size": [0.018, 0.06, 0], "position": [0.08, 0.06, 0.11], "rotation": [90, 0, 0], "material": "steel", "group": "Drive", "power_w": 12},
            {"name": "Motor R", "shape": "cylinder", "size": [0.018, 0.06, 0], "position": [0.08, 0.06, -0.11], "rotation": [90, 0, 0], "material": "steel", "group": "Drive", "power_w": 12},
            {"name": "Sensor mast", "shape": "cylinder", "size": [0.012, 0.22, 0], "position": [0.14, 0.24, 0], "material": "carbon_fiber", "group": "Sensors"},
            {"name": "LiDAR", "shape": "cylinder", "size": [0.04, 0.04, 0], "position": [0.14, 0.37, 0], "material": "electronics", "group": "Sensors", "power_w": 3},
        ],
    },
    "robot_arm": {
        "name": "Robot arm", "description": "Three-joint desktop robot arm with a gripper.",
        "parts": [
            {"name": "Base", "shape": "cylinder", "size": [0.09, 0.04, 0], "position": [0, 0.02, 0], "material": "steel", "group": "Base", "infill": 0.25},
            {"name": "Shoulder servo", "shape": "box", "size": [0.06, 0.05, 0.04], "position": [0, 0.065, 0], "material": "electronics", "group": "Joints", "power_w": 8},
            {"name": "Upper arm", "shape": "box", "size": [0.04, 0.22, 0.03], "position": [0, 0.20, 0], "material": "aluminum", "group": "Links", "infill": 0.3},
            {"name": "Elbow servo", "shape": "box", "size": [0.06, 0.05, 0.04], "position": [0, 0.33, 0], "material": "electronics", "group": "Joints", "power_w": 6},
            {"name": "Forearm", "shape": "box", "size": [0.18, 0.03, 0.03], "position": [0.11, 0.33, 0], "material": "aluminum", "group": "Links", "infill": 0.3},
            {"name": "Wrist", "shape": "cylinder", "size": [0.02, 0.04, 0], "position": [0.22, 0.33, 0], "rotation": [0, 0, 90], "material": "steel", "group": "Joints", "power_w": 3},
            {"name": "Gripper finger A", "shape": "box", "size": [0.05, 0.01, 0.01], "position": [0.265, 0.345, 0], "material": "pla", "group": "Gripper"},
            {"name": "Gripper finger B", "shape": "box", "size": [0.05, 0.01, 0.01], "position": [0.265, 0.315, 0], "material": "pla", "group": "Gripper"},
        ],
    },
    "drone": {
        "name": "Quad drone", "description": "250-class quadcopter frame with four rotors.",
        "parts": [
            {"name": "Body", "shape": "box", "size": [0.10, 0.04, 0.10], "position": [0, 0.10, 0], "material": "carbon_fiber", "group": "Frame", "infill": 0.15},
            {"name": "Battery", "shape": "box", "size": [0.075, 0.03, 0.035], "position": [0, 0.135, 0], "material": "battery", "group": "Power", "battery_wh": 22},
            {"name": "Flight controller", "shape": "box", "size": [0.036, 0.008, 0.036], "position": [0, 0.084, 0], "material": "electronics", "group": "Electronics", "power_w": 2},
            {"name": "Arm 1", "shape": "box", "size": [0.18, 0.008, 0.02], "position": [0.07, 0.10, 0.07], "rotation": [0, -45, 0], "material": "carbon_fiber", "group": "Frame"},
            {"name": "Arm 2", "shape": "box", "size": [0.18, 0.008, 0.02], "position": [-0.07, 0.10, 0.07], "rotation": [0, 45, 0], "material": "carbon_fiber", "group": "Frame"},
            {"name": "Arm 3", "shape": "box", "size": [0.18, 0.008, 0.02], "position": [-0.07, 0.10, -0.07], "rotation": [0, -45, 0], "material": "carbon_fiber", "group": "Frame"},
            {"name": "Arm 4", "shape": "box", "size": [0.18, 0.008, 0.02], "position": [0.07, 0.10, -0.07], "rotation": [0, 45, 0], "material": "carbon_fiber", "group": "Frame"},
            {"name": "Rotor 1", "shape": "torus", "size": [0.06, 0.004, 0], "position": [0.125, 0.115, 0.125], "rotation": [90, 0, 0], "material": "nylon", "group": "Propulsion"},
            {"name": "Rotor 2", "shape": "torus", "size": [0.06, 0.004, 0], "position": [-0.125, 0.115, 0.125], "rotation": [90, 0, 0], "material": "nylon", "group": "Propulsion"},
            {"name": "Rotor 3", "shape": "torus", "size": [0.06, 0.004, 0], "position": [-0.125, 0.115, -0.125], "rotation": [90, 0, 0], "material": "nylon", "group": "Propulsion"},
            {"name": "Rotor 4", "shape": "torus", "size": [0.06, 0.004, 0], "position": [0.125, 0.115, -0.125], "rotation": [90, 0, 0], "material": "nylon", "group": "Propulsion"},
            {"name": "Motor 1", "shape": "cylinder", "size": [0.014, 0.016, 0], "position": [0.125, 0.10, 0.125], "material": "copper", "group": "Propulsion", "power_w": 90, "infill": 0.5},
            {"name": "Motor 2", "shape": "cylinder", "size": [0.014, 0.016, 0], "position": [-0.125, 0.10, 0.125], "material": "copper", "group": "Propulsion", "power_w": 90, "infill": 0.5},
            {"name": "Motor 3", "shape": "cylinder", "size": [0.014, 0.016, 0], "position": [-0.125, 0.10, -0.125], "material": "copper", "group": "Propulsion", "power_w": 90, "infill": 0.5},
            {"name": "Motor 4", "shape": "cylinder", "size": [0.014, 0.016, 0], "position": [0.125, 0.10, -0.125], "material": "copper", "group": "Propulsion", "power_w": 90, "infill": 0.5},
        ],
    },
    "arc_reactor": {
        "name": "Arc reactor", "description": "Display prop: rings, coils and a glowing core.",
        "parts": [
            {"name": "Core", "shape": "cylinder", "size": [0.025, 0.02, 0], "position": [0, 0.1, 0], "rotation": [90, 0, 0], "material": "glass", "group": "Core", "power_w": 4},
            {"name": "Inner ring", "shape": "torus", "size": [0.04, 0.006, 0], "position": [0, 0.1, 0], "material": "aluminum", "group": "Rings"},
            {"name": "Outer ring", "shape": "torus", "size": [0.07, 0.01, 0], "position": [0, 0.1, 0], "material": "aluminum", "group": "Rings", "infill": 0.5},
            {"name": "Coil 1", "shape": "box", "size": [0.014, 0.022, 0.012], "position": [0.055, 0.1, 0], "material": "copper", "group": "Coils"},
            {"name": "Coil 2", "shape": "box", "size": [0.014, 0.022, 0.012], "position": [-0.055, 0.1, 0], "material": "copper", "group": "Coils"},
            {"name": "Coil 3", "shape": "box", "size": [0.022, 0.014, 0.012], "position": [0, 0.155, 0], "material": "copper", "group": "Coils"},
            {"name": "Coil 4", "shape": "box", "size": [0.022, 0.014, 0.012], "position": [0, 0.045, 0], "material": "copper", "group": "Coils"},
            {"name": "LED driver", "shape": "box", "size": [0.03, 0.03, 0.008], "position": [0, 0.1, -0.02], "material": "electronics", "group": "Electronics", "power_w": 1.5},
            {"name": "Cell", "shape": "cylinder", "size": [0.009, 0.065, 0], "position": [0, 0.1, -0.035], "rotation": [0, 0, 90], "material": "battery", "group": "Power", "battery_wh": 11},
        ],
    },
}


class BlueprintStore:
    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "blueprints"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def _path(self, bid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{12}", bid or ""):
            raise KeyError(bid)
        return self.root / f"{bid}.json"

    def _write(self, bp: dict, remember: bool = True) -> None:
        path = self._path(bp["id"])
        if remember and path.exists():   # keep the old version so it can be undone
            hist = self.root / "history" / bp["id"]
            hist.mkdir(parents=True, exist_ok=True)
            old = json.loads(path.read_text(encoding="utf-8"))
            (hist / f"{old.get('version', 1):06d}.json").write_text(json.dumps(old), encoding="utf-8")
            for stale in sorted(hist.glob("*.json"))[:-HISTORY_KEPT]:
                stale.unlink()
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(bp, indent=1), encoding="utf-8")
        os.replace(tmp, path)

    def undo(self, bid: str) -> dict:
        """Go back to the version before the last change (Corvis's or the owner's)."""
        with self._lock:
            current = self.get(bid)
            hist = sorted((self.root / "history" / bid).glob("*.json")) if (self.root / "history" / bid).is_dir() else []
            if not hist:
                raise ValueError("Nothing to undo.")
            old = json.loads(hist[-1].read_text(encoding="utf-8"))
            hist[-1].unlink()
            old["version"] = current.get("version", 1) + 1
            old["updated"] = time.time()
            self._write(old, remember=False)
            return old

    def can_undo(self, bid: str) -> int:
        hist = self.root / "history" / bid
        return len(list(hist.glob("*.json"))) if hist.is_dir() else 0

    # --- live control: Corvis steering the hologram the owner is looking at ----------------
    def command(self, bid: str | None, action: str, parts: list[str] | None = None, amount: float | None = None,
                say: str = "") -> dict:
        path = self.root / "live.state"
        with self._lock:
            try:
                seq = json.loads(path.read_text(encoding="utf-8")).get("seq", 0)
            except (OSError, ValueError):
                seq = 0
            cmd = {"seq": seq + 1, "blueprint": bid, "action": action, "parts": parts or [], "amount": amount,
                   "say": str(say)[:300], "ts": time.time()}
            path.write_text(json.dumps(cmd), encoding="utf-8")
        return cmd

    def live(self) -> dict:
        try:
            cmd = json.loads((self.root / "live.state").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            cmd = {"seq": 0}
        return {"command": cmd, "versions": {b["id"]: b["version"] for b in self.list()}}

    def list(self) -> list[dict]:
        out = []
        for p in self.root.glob("*.json"):
            if not re.fullmatch(r"[a-f0-9]{12}\.json", p.name):
                continue
            try:
                bp = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({"id": bp["id"], "name": bp["name"], "description": bp.get("description", ""),
                        "parts": len(bp.get("parts", [])), "updated": bp.get("updated", 0),
                        "version": bp.get("version", 1), "source": bp.get("source")})
        return sorted(out, key=lambda b: b["updated"], reverse=True)

    def get(self, bid: str) -> dict:
        try:
            return json.loads(self._path(bid).read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise KeyError(bid) from None

    def find(self, ref: str) -> dict:
        """By id, or by name (case-insensitive; a unique partial match is fine)."""
        ref = (ref or "").strip()
        try:
            return self.get(ref)
        except KeyError:
            pass
        items = self.list()
        exact = [b for b in items if b["name"].lower() == ref.lower()]
        partial = [b for b in items if ref.lower() in b["name"].lower()]
        match = exact or (partial if len(partial) == 1 else [])
        if not match:
            names = ", ".join(b["name"] for b in items) or "none yet"
            raise KeyError(f"No blueprint called '{ref}'. Blueprints: {names}")
        return self.get(match[0]["id"])

    def create(self, name: str = "", template: str = "blank", description: str = "",
               parts: list | None = None, source: dict | None = None) -> dict:
        if template not in TEMPLATES:
            raise ValueError(f"Unknown template '{template}'. Use one of: {', '.join(TEMPLATES)}.")
        base = copy.deepcopy(TEMPLATES[template])
        raw_parts = parts if parts is not None else base["parts"]
        if len(raw_parts) > MAX_PARTS:
            raise ValueError(f"A blueprint can have at most {MAX_PARTS} parts.")
        now = time.time()
        bp = {"id": uuid.uuid4().hex[:12], "name": (name or base["name"]).strip()[:80] or "Blueprint",
              "description": (description or base["description"]).strip()[:1000],
              "created": now, "updated": now, "version": 1, "parts": [clean_part(p) for p in raw_parts]}
        if source:
            bp["source"] = clean_source(source)
        with self._lock:
            self._write(bp)
        return bp

    def save(self, bid: str, data: dict, version: int | None = None) -> dict:
        """Replace name, description and parts (the editor's save)."""
        with self._lock:
            bp = self.get(bid)
            if version is not None and version != bp.get("version", 1):
                raise ValueError("This blueprint changed since you loaded it (Corvis may be editing it). Reload it.")
            parts = data.get("parts", bp["parts"])
            if not isinstance(parts, list) or len(parts) > MAX_PARTS:
                raise ValueError(f"A blueprint can have at most {MAX_PARTS} parts.")
            bp["parts"] = [clean_part(p) for p in parts]
            if "name" in data:
                bp["name"] = str(data["name"]).strip()[:80] or bp["name"]
            if "description" in data:
                bp["description"] = str(data["description"]).strip()[:1000]
            bp["updated"] = time.time()
            bp["version"] = bp.get("version", 1) + 1
            self._write(bp)
            return bp

    def edit(self, bid: str, add: list | None = None, update: list | None = None,
             remove: list | None = None) -> dict:
        """Change parts by name or id: add new ones, update fields of existing ones, remove some."""
        with self._lock:
            bp = self.get(bid)
            parts = bp["parts"]

            def locate(ref: str) -> dict:
                ref = str(ref).strip().lower()
                hits = [p for p in parts if p["id"].lower() == ref] or [p for p in parts if p["name"].lower() == ref]
                if len(hits) != 1:
                    raise KeyError(f"No single part called '{ref}' in {bp['name']}.")
                return hits[0]

            for ref in remove or []:
                parts.remove(locate(ref))
            for change in update or []:
                if not isinstance(change, dict) or not change.get("part"):
                    raise ValueError("Each update needs 'part' (the part's name or id) and the fields to change.")
                old = locate(change["part"])
                merged = {**old, **{k: v for k, v in change.items() if k != "part"}}
                parts[parts.index(old)] = clean_part(merged, existing_id=old["id"])
            for raw in add or []:
                parts.append(clean_part({k: v for k, v in raw.items() if k != "id"}))
            if len(parts) > MAX_PARTS:
                raise ValueError(f"A blueprint can have at most {MAX_PARTS} parts.")
            bp["updated"] = time.time()
            bp["version"] = bp.get("version", 1) + 1
            self._write(bp)
            return bp

    def delete(self, bid: str) -> None:
        with self._lock:
            path = self._path(bid)
            if not path.exists():
                raise KeyError(bid)
            path.unlink()


SOURCE_KINDS = {
    "official": "official model published by the maker",
    "community": "community-made model (not official drawings)",
    "upload": "a file the owner uploaded",
    "corvis": "designed by Corvis and the owner",
}


def clean_source(raw: dict) -> dict:
    """Where a design came from, so the hologram can always say it honestly."""
    out = {k: str(raw.get(k) or "").strip()[:300] for k in ("title", "url", "site", "author", "license", "note")}
    kind = str(raw.get("kind") or "community")
    out["kind"] = kind if kind in SOURCE_KINDS else "community"
    return {k: v for k, v in out.items() if v}


def describe(bp: dict) -> str:
    """A compact text view of a blueprint for Corvis."""
    lines = [f"Blueprint '{bp['name']}' (id {bp['id']}, {len(bp['parts'])} parts). {bp.get('description', '')}".strip()]
    src = bp.get("source")
    if src:
        lines.append(f"Source: {src.get('title') or src.get('url', '')} from {src.get('site', '?')} "
                     f"({SOURCE_KINDS[src['kind']]}{', ' + src['license'] if src.get('license') else ''}).")
    total = 0.0
    for p in bp["parts"]:
        m = mass(p)
        total += m
        extra = []
        if p["power_w"]:
            extra.append(f"{p['power_w']:g} W")
        if p["battery_wh"]:
            extra.append(f"{p['battery_wh']:g} Wh")
        shape = "imported mesh" if p["shape"] == "mesh" else p["shape"]
        lines.append(f"- {p['name']} [{p['id']}]: {shape} size {p['size']} at {p['position']} rot {p['rotation']}, "
                     f"{MATERIALS[p['material']]['label']}, {m * 1000:.0f} g"
                     + (f", {', '.join(extra)}" if extra else "") + (f", group {p['group']}" if p["group"] else ""))
    lines.append(f"Total mass: {total:.3f} kg")
    return "\n".join(lines)
