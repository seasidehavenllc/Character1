"""Quick engineering tests for blueprints: load, heat, drop, wind and power.

These are first-pass estimates to spot weak points while designing, in the spirit of a
hologram workbench, not finite-element analysis. Every result says what it assumed.
Each test returns per-part results with a 0..1+ `ratio` (how close to the limit) so the
hologram can colour parts: under 0.5 is fine, 0.5-1 is a warning, over 1 fails.
"""
from __future__ import annotations

import math

from .blueprints import MATERIALS, footprint, frontal_area, half_extent, mass

G = 9.81
HEAT_SHARE = 0.25   # share of a part's power that becomes heat
CONVECTION = {"still air": 10, "gentle airflow": 40, "fan or propeller wash": 150}  # W/m2K
AIR = 1.225  # kg/m3
SURFACES = {"concrete": 1.0, "wood floor": 0.7, "grass": 0.35, "carpet": 0.3, "foam": 0.1}

SITUATIONS = {
    "load": {"label": "Load / stress", "params": {
        "load_n": {"label": "Load on top (N)", "min": 0, "max": 5000, "step": 10, "default": 200}}},
    "heat": {"label": "Heat", "params": {
        "ambient_c": {"label": "Surroundings (°C)", "min": -40, "max": 200, "step": 1, "default": 25},
        "extra_c": {"label": "Extra heat on everything (°C)", "min": 0, "max": 400, "step": 1, "default": 0},
        "duty": {"label": "How hard it works (%)", "min": 5, "max": 100, "step": 5, "default": 60},
        "airflow": {"label": "Cooling", "options": ["still air", "gentle airflow", "fan or propeller wash"],
                    "default": "gentle airflow"}}},
    "drop": {"label": "Drop test", "params": {
        "height_m": {"label": "Drop height (m)", "min": 0.1, "max": 20, "step": 0.1, "default": 1.0},
        "surface": {"label": "Lands on", "options": list(SURFACES), "default": "concrete"}}},
    "wind": {"label": "Wind", "params": {
        "speed_ms": {"label": "Wind speed (m/s)", "min": 0, "max": 70, "step": 0.5, "default": 10}}},
    "power": {"label": "Power", "params": {
        "duty": {"label": "How hard it works (%)", "min": 5, "max": 100, "step": 5, "default": 60}}},
}


def _status(ratio: float) -> str:
    return "fail" if ratio > 1 else "warn" if ratio > 0.5 else "ok"


def _param(params: dict, situation: str, key: str):
    spec = SITUATIONS[situation]["params"][key]
    value = params.get(key, spec["default"])
    if "options" in spec:
        return value if value in spec["options"] else spec["default"]
    try:
        return max(spec["min"], min(spec["max"], float(value)))
    except (TypeError, ValueError):
        return spec["default"]


def summary(bp: dict) -> dict:
    parts = bp["parts"]
    total = sum(mass(p) for p in parts)
    if total > 0:
        com = [sum(mass(p) * p["position"][i] for p in parts) / total for i in range(3)]
    else:
        com = [0.0, 0.0, 0.0]
    return {"mass_kg": round(total, 4), "center_of_mass": [round(c, 4) for c in com], "parts": len(parts)}


def _overlaps(a: dict, b: dict) -> bool:
    """Does part b sit over part a (their footprints overlap in x/z)?"""
    ha, hb = half_extent(a), half_extent(b)
    return (abs(a["position"][0] - b["position"][0]) <= ha[0] + hb[0]
            and abs(a["position"][2] - b["position"][2]) <= ha[2] + hb[2])


def test_load(bp: dict, params: dict) -> dict:
    load = _param(params, "load", "load_n")
    parts = bp["parts"]
    top = max((p["position"][1] + half_extent(p)[1] for p in parts), default=0)
    results = {}
    for p in parts:
        above = [q for q in parts if q is not p and q["position"][1] > p["position"][1] and _overlaps(p, q)]
        # the external load reaches this part if nothing above it is closer to the top
        carries_load = top - (p["position"][1] + half_extent(p)[1]) < 0.02 or bool(above)
        force = G * sum(mass(q) for q in above) + (load if carries_load else 0)
        stress_mpa = force / max(footprint(p), 1e-6) / 1e6
        ratio = stress_mpa / MATERIALS[p["material"]]["yield_mpa"]
        results[p["id"]] = {"value": round(stress_mpa, 4), "unit": "MPa", "ratio": round(ratio, 4),
                            "status": _status(ratio),
                            "detail": f"carries {force:.0f} N; safety factor {1 / ratio:.1f}" if ratio > 0
                            else "carries no load"}
    worst = max(results.values(), key=lambda r: r["ratio"], default=None)
    note = (f"With {load:.0f} N on top, the most stressed part is at {worst['ratio'] * 100:.0f}% of its limit."
            if worst else "No parts to test.")
    return {"parts": results, "headline": note,
            "assumes": "Load presses straight down; each part carries the weight above it over its "
                       "horizontal cross-section; rotations and bending are ignored."}


def test_heat(bp: dict, params: dict) -> dict:
    ambient = _param(params, "heat", "ambient_c")
    extra = _param(params, "heat", "extra_c")
    duty = _param(params, "heat", "duty") / 100
    h = CONVECTION[_param(params, "heat", "airflow")]
    results = {}
    for p in bp["parts"]:
        x, y, z = p["size"]
        area_m2 = max(2 * (x * y + y * z + x * z) if p["shape"] == "box"
                      else 2 * math.pi * x * (x + y), 1e-5)
        # a part turns about a quarter of its power into heat and sheds it through its surface
        self_heat = max(p["power_w"], 0) * duty * HEAT_SHARE / (h * area_m2)
        temp = ambient + extra + self_heat
        limit = MATERIALS[p["material"]]["max_temp_c"]
        ratio = max(temp, 0) / limit
        results[p["id"]] = {"value": round(temp, 1), "unit": "°C", "ratio": round(ratio, 4),
                            "status": _status(ratio),
                            "detail": f"limit {limit} °C" + (f"; its own {p['power_w']:g} W adds {self_heat:.0f} °C"
                                                              if self_heat >= 1 else "")}
    hottest = max(results.values(), key=lambda r: r["value"], default=None)
    over = [p["name"] for p in bp["parts"] if results[p["id"]]["value"] > MATERIALS[p["material"]]["max_temp_c"]]
    note = ("Too hot: " + ", ".join(over) if over
            else f"Everything stays within limits (hottest part {hottest['value']:.0f} °C)." if hottest else "No parts.")
    return {"parts": results, "headline": note,
            "assumes": "Each part turns a quarter of its power (at the chosen effort) into heat and "
                       "sheds it through its surface with the chosen cooling; no heat sinks or conduction "
                       "between parts."}


def test_drop(bp: dict, params: dict) -> dict:
    height = _param(params, "drop", "height_m")
    surface = _param(params, "drop", "surface")
    hardness = SURFACES[surface]
    parts = bp["parts"]
    low = min((p["position"][1] - half_extent(p)[1] for p in parts), default=0)
    results = {}
    for p in parts:
        energy = mass(p) * G * height * hardness
        # parts nearest the ground take the impact; parts higher up are partly shielded
        nearness = 1 / (1 + 8 * max(p["position"][1] - half_extent(p)[1] - low, 0))
        per_cm2 = energy * (0.35 + 0.65 * nearness) / max(footprint(p) * 1e4, 0.05)
        ratio = per_cm2 / MATERIALS[p["material"]]["toughness"]
        results[p["id"]] = {"value": round(energy, 3), "unit": "J", "ratio": round(ratio, 4),
                            "status": _status(ratio), "detail": f"{per_cm2:.2f} J/cm² at impact"}
    broken = [p["name"] for p in parts if results[p["id"]]["status"] == "fail"]
    note = (f"Dropped {height:g} m onto {surface}: " +
            (f"{', '.join(broken)} would likely break." if broken else "it should survive."))
    return {"parts": results, "headline": note,
            "assumes": "Lands flat; each part absorbs its own impact energy over its footprint; "
                       "softer surfaces absorb more; no cushioning or fasteners modelled."}


def test_wind(bp: dict, params: dict) -> dict:
    speed = _param(params, "wind", "speed_ms")
    parts = bp["parts"]
    q = 0.5 * AIR * speed * speed  # dynamic pressure, Pa
    force, moment, pushes = 0.0, 0.0, {}
    low = min((p["position"][1] - half_extent(p)[1] for p in parts), default=0)
    for p in parts:
        f = q * 1.1 * frontal_area(p)
        force += f
        moment += f * (p["position"][1] - low)
        pushes[p["id"]] = (f, f * (p["position"][1] - low), f / max(footprint(p), 1e-6) / 1e6)
    s = summary(bp)
    results = {}
    if parts:
        xs = [p["position"][0] - half_extent(p)[0] for p in parts] + [p["position"][0] + half_extent(p)[0] for p in parts]
        lever = max(min(abs(s["center_of_mass"][0] - min(xs)), abs(max(xs) - s["center_of_mass"][0])), 1e-3)
        holding = max(s["mass_kg"] * G * lever, 1e-9)
        tips = moment > holding
        for p in parts:   # the whole design tips together; a flimsy part can also be torn off on its own
            f, m, stress_mpa = pushes[p["id"]]
            ratio = max(moment / holding, stress_mpa / MATERIALS[p["material"]]["yield_mpa"])
            share = m / moment * 100 if moment else 0
            results[p["id"]] = {"value": round(f, 3), "unit": "N", "ratio": round(ratio, 4), "status": _status(ratio),
                                "detail": f"pushed with {f:.2f} N, {share:.0f}% of the tipping push"}
        note = (f"At {speed:g} m/s the wind pushes with {force:.1f} N. "
                + (f"It TIPS OVER (wind {moment:.2f} N·m vs weight holding {holding:.2f} N·m)."
                   if tips else f"It stays upright ({moment / holding * 100:.0f}% of tipping)."))
    else:
        tips, note = False, "No parts."
    return {"parts": results, "headline": note, "tips": tips, "force_n": round(force, 3),
            "assumes": "Wind along +x; drag coefficient 1.1 on each part's face; tipping about the "
                       "downwind edge; parts don't shelter each other. The % is how close the whole design is to "
                       "tipping (or a part to tearing)."}


def test_power(bp: dict, params: dict) -> dict:
    duty = _param(params, "power", "duty") / 100
    parts = bp["parts"]
    draw = sum(max(p["power_w"], 0) for p in parts) * duty
    supply = sum(-min(p["power_w"], 0) for p in parts)
    battery = sum(p["battery_wh"] for p in parts)
    net = draw - supply
    results = {}
    for p in parts:
        w = max(p["power_w"], 0) * duty
        share = w / draw if draw else 0
        results[p["id"]] = {"value": round(w, 2), "unit": "W", "ratio": round(share, 4),
                            "status": "warn" if share > 0.4 else "ok",
                            "detail": f"{share * 100:.0f}% of total draw" if w else "draws no power"}
    if net <= 0:
        note = f"Uses {draw:.1f} W and makes {supply:.1f} W: it can run indefinitely."
        runtime = None
    elif battery:
        runtime = battery * 0.85 / net
        note = f"Uses {draw:.1f} W at {duty * 100:.0f}% effort: about {runtime * 60:.0f} minutes on {battery:g} Wh."
    else:
        runtime = 0
        note = f"Uses {draw:.1f} W but has no battery or power source."
    return {"parts": results, "headline": note, "runtime_h": None if runtime is None else round(runtime, 3),
            "assumes": "Each part draws its rated power times the effort level; 85% of battery capacity usable."}


TESTS = {"load": test_load, "heat": test_heat, "drop": test_drop, "wind": test_wind, "power": test_power}


def run(bp: dict, situation: str, params: dict | None = None) -> dict:
    if situation not in TESTS:
        raise ValueError(f"Unknown test '{situation}'. Use one of: {', '.join(TESTS)}.")
    result = TESTS[situation](bp, params or {})
    return {"situation": situation, **summary(bp), **result}


def report(result: dict, bp: dict, limit: int = 8) -> str:
    """Text for Corvis: the headline, then the parts closest to their limits."""
    names = {p["id"]: p["name"] for p in bp["parts"]}
    worst = sorted(result["parts"].items(), key=lambda kv: kv[1]["ratio"], reverse=True)[:limit]
    lines = [result["headline"], f"(Assumes: {result['assumes']})", "Parts closest to their limits:"]
    for pid, r in worst:
        lines.append(f"- {names.get(pid, pid)}: {r['value']} {r['unit']}, {r['ratio'] * 100:.0f}% of limit "
                     f"[{r['status']}] {r['detail']}")
    return "\n".join(lines)
