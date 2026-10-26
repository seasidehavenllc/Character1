"""Blueprints: 3D designs Corvis and the owner build together, shown as holograms.

A blueprint is a named assembly of simple parts (boxes, cylinders, spheres, cones, tori,
capsules), each with a size, position, rotation, material and optional power figures.
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

SHAPES = ("box", "cylinder", "sphere", "cone", "torus", "capsule")
MAX_PARTS = 300

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
    part = {
        "id": str(raw.get("id") or existing_id or uuid.uuid4().hex[:8])[:16],
        "name": str(raw.get("name") or shape.title()).strip()[:60] or shape.title(),
        "shape": shape,
        "size": _vec(raw.get("size"), 0.001, 100, [0.1, 0.1, 0.1]),
        "position": _vec(raw.get("position"), -500, 500, [0, 0, 0]),
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
    return part


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
    return math.pi * ((x + y) ** 2 - max(x - y, 0) ** 2)  # torus lying flat


def frontal_area(part: dict) -> float:
    """Area facing a wind blowing along x, in m2."""
    x, y, z = part["size"]
    shape = part["shape"]
    if shape == "box":
        return y * z
    if shape == "cylinder":
        return 2 * x * y
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
    if shape in ("cylinder", "cone"):
        return [x, y / 2, x]
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

    def _write(self, bp: dict) -> None:
        tmp = self._path(bp["id"]).with_suffix(".tmp")
        tmp.write_text(json.dumps(bp, indent=1), encoding="utf-8")
        os.replace(tmp, self._path(bp["id"]))

    def list(self) -> list[dict]:
        out = []
        for p in self.root.glob("*.json"):
            try:
                bp = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                continue
            out.append({"id": bp["id"], "name": bp["name"], "description": bp.get("description", ""),
                        "parts": len(bp.get("parts", [])), "updated": bp.get("updated", 0),
                        "version": bp.get("version", 1)})
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
               parts: list | None = None) -> dict:
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


def describe(bp: dict) -> str:
    """A compact text view of a blueprint for Corvis."""
    lines = [f"Blueprint '{bp['name']}' (id {bp['id']}, {len(bp['parts'])} parts). {bp.get('description', '')}".strip()]
    total = 0.0
    for p in bp["parts"]:
        m = mass(p)
        total += m
        extra = []
        if p["power_w"]:
            extra.append(f"{p['power_w']:g} W")
        if p["battery_wh"]:
            extra.append(f"{p['battery_wh']:g} Wh")
        lines.append(f"- {p['name']} [{p['id']}]: {p['shape']} size {p['size']} at {p['position']} rot {p['rotation']}, "
                     f"{MATERIALS[p['material']]['label']}, {m * 1000:.0f} g"
                     + (f", {', '.join(extra)}" if extra else "") + (f", group {p['group']}" if p["group"] else ""))
    lines.append(f"Total mass: {total:.3f} kg")
    return "\n".join(lines)
