"""Blueprint geometry and blueprint files.

Turns every part (basic solids, extruded and lathed outlines, imported meshes) into triangles
the same way the hologram draws them, then writes real files from them:

- STL and 3MF for 3D printing (millimetres, z up, the way slicers expect)
- OBJ and GLB for Blender, Unity, Unreal, Fusion and friends (metres, y up; one object per part)
- DXF and SVG blueprint sheets: front, top and side views with overall dimensions and a title
  block (DXF at true size in millimetres for CAD; SVG drawn to a standard scale on an A3 sheet)
"""
from __future__ import annotations

import datetime as dt
import io
import json
import math
import struct
import zipfile
from html import escape

from .blueprints import MATERIALS, _profile_scale
from .meshes import MeshStore, stl_bytes

SEG = 48          # segments round a circle (the hologram uses the same)
FORMATS = {
    "stl": "STL for 3D printing (mm)", "3mf": "3MF for 3D printing (mm, one object per part)",
    "obj": "OBJ for 3D apps (metres, one object per part)", "glb": "GLB / glTF for 3D apps, games and AR (metres)",
    "dxf": "DXF 2D blueprint for CAD (front, top and side views, true size in mm)",
    "svg": "SVG blueprint sheet (front, top and side views with dimensions)",
}
MIME = {"stl": "model/stl", "3mf": "model/3mf", "obj": "text/plain", "glb": "model/gltf-binary", "dxf": "image/vnd.dxf",
        "svg": "image/svg+xml"}
COLORS = {"aluminum": "#b8c2cc", "steel": "#7d8792", "titanium": "#a9a39a", "carbon_fiber": "#2b2f36", "abs": "#e6e1d6",
          "pla": "#e8e8e8", "nylon": "#f1ede4", "rubber": "#262626", "wood": "#b8864b", "glass": "#bfe6ff",
          "copper": "#c87533", "electronics": "#2f7d4f", "battery": "#3a4a6b"}


# --- tessellation (local coordinates, y up, centred like three.js geometries) -------------

def _ring(r: float, y: float, n: int = SEG) -> list[tuple[float, float, float]]:
    return [(r * math.sin(2 * math.pi * k / n), y, r * math.cos(2 * math.pi * k / n)) for k in range(n)]


def _quad(out: list, a, b, c, d) -> None:
    """Two triangles; a corner that collapses (e.g. on the spin axis) leaves just one."""
    for t in ((a, b, c), (a, c, d)):
        if t[0] != t[1] and t[1] != t[2] and t[0] != t[2]:
            out.extend((*t[0], *t[1], *t[2]))


def _lathe(points: list[tuple[float, float]], n: int = SEG) -> list[float]:
    """Spin an outline of (radius, y) points around the y axis (like THREE.LatheGeometry)."""
    out: list[float] = []
    rings = [_ring(r, y, n) for r, y in points]
    for a, b in zip(rings, rings[1:]):
        for k in range(n):
            k2 = (k + 1) % n
            _quad(out, a[k], b[k], b[k2], a[k2])
    return out


def _disc(r: float, y: float, up: bool, n: int = SEG) -> list[float]:
    ring, out, c = _ring(r, y, n), [], (0.0, y, 0.0)
    for k in range(n):
        a, b = ring[k], ring[(k + 1) % n]
        out.extend((*c, *b, *a) if up else (*c, *a, *b))
    return out


def _box(x: float, y: float, z: float) -> list[float]:
    hx, hy, hz = x / 2, y / 2, z / 2
    v = [(-hx, -hy, -hz), (hx, -hy, -hz), (hx, hy, -hz), (-hx, hy, -hz),
         (-hx, -hy, hz), (hx, -hy, hz), (hx, hy, hz), (-hx, hy, hz)]
    out: list[float] = []
    for a, b, c, d in ((0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (3, 7, 6, 2), (1, 2, 6, 5), (0, 4, 7, 3)):
        _quad(out, v[a], v[b], v[c], v[d])
    return out


def _triangulate(poly: list[tuple[float, float]]) -> list[tuple[int, int, int]]:
    """Ear clipping for a simple polygon (any winding)."""
    n = len(poly)
    area = sum(poly[i][0] * poly[(i + 1) % n][1] - poly[(i + 1) % n][0] * poly[i][1] for i in range(n))
    idx = list(range(n)) if area > 0 else list(range(n))[::-1]
    tris, guard = [], 0

    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    while len(idx) > 3 and guard < n * n:
        guard += 1
        for i in range(len(idx)):
            a, b, c = idx[i - 1], idx[i], idx[(i + 1) % len(idx)]
            if cross(poly[a], poly[b], poly[c]) <= 1e-12:
                continue
            if any(cross(poly[a], poly[b], poly[p]) >= 0 and cross(poly[b], poly[c], poly[p]) >= 0
                   and cross(poly[c], poly[a], poly[p]) >= 0 for p in idx if p not in (a, b, c)):
                continue
            tris.append((a, b, c))
            idx.pop(i)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    return tris


def _extrude(profile: list[list[float]], depth: float) -> list[float]:
    poly = [(p[0], p[1]) for p in profile]
    if poly[0] == poly[-1]:
        poly = poly[:-1]
    out: list[float] = []
    zb, zf = -depth / 2, depth / 2
    for a, b, c in _triangulate(poly):
        out.extend((*poly[a], zf, *poly[b], zf, *poly[c], zf))
        out.extend((*poly[a], zb, *poly[c], zb, *poly[b], zb))
    for i in range(len(poly)):
        p, q = poly[i], poly[(i + 1) % len(poly)]
        _quad(out, (*p, zb), (*q, zb), (*q, zf), (*p, zf))
    return out


def _centre(tris: list[float]) -> list[float]:
    lo = [min(tris[i::3]) for i in range(3)]
    hi = [max(tris[i::3]) for i in range(3)]
    c = [(lo[i] + hi[i]) / 2 for i in range(3)]
    return [v - c[i % 3] for i, v in enumerate(tris)]


def local_triangles(part: dict, meshes: MeshStore | None = None) -> list[float]:
    x, y, z = part["size"]
    s = part["shape"]
    if s == "box":
        return _box(x, y, z)
    if s in ("cylinder", "cone"):
        top = x if s == "cylinder" else 0.0
        return _lathe([(0, -y / 2), (x, -y / 2), (top, y / 2), (0, y / 2)])
    if s == "tube":
        ri = min(z, x * 0.999)
        return _lathe([(ri, -y / 2), (x, -y / 2), (x, y / 2), (ri, y / 2), (ri, -y / 2)])
    if s == "sphere":
        n = SEG // 2
        return _lathe([(x * math.sin(math.pi * k / n), -x * math.cos(math.pi * k / n)) for k in range(n + 1)])
    if s == "capsule":
        n = SEG // 4
        bottom = [(x * math.sin(math.pi / 2 * k / n), -y / 2 - x * math.cos(math.pi / 2 * k / n)) for k in range(n + 1)]
        top = [(x * math.cos(math.pi / 2 * k / n), y / 2 + x * math.sin(math.pi / 2 * k / n)) for k in range(n + 1)]
        return _lathe(bottom + top)
    if s == "torus":   # in the x-y plane, like THREE.TorusGeometry
        out: list[float] = []
        n1, n2 = SEG, SEG // 2

        def pt(i, j):
            u, v = 2 * math.pi * i / n1, 2 * math.pi * j / n2
            return ((x + y * math.cos(v)) * math.cos(u), (x + y * math.cos(v)) * math.sin(u), y * math.sin(v))
        for i in range(n1):
            for j in range(n2):
                _quad(out, pt(i, j), pt(i + 1, j), pt(i + 1, j + 1), pt(i, j + 1))
        return out
    if s == "extrude":
        sx, sy, _ = _profile_scale(part)
        prof = [[p[0] * sx, p[1] * sy] for p in part["profile"]]
        return _centre(_extrude(prof, z))
    if s == "lathe":
        sx, sy, sz = _profile_scale(part)
        tris = _centre(_lathe([(p[0], p[1]) for p in part["profile"]]))
        return [v * (sx, sy, sz)[i % 3] for i, v in enumerate(tris)]
    if s == "mesh":
        if meshes is None:
            return _box(x, y, z)
        try:
            raw = meshes.triangles(part["mesh"]["id"])
        except (KeyError, OSError):
            return _box(x, y, z)   # the model file is missing; keep its place
        bx, by, bz = part["mesh"]["bbox"]
        k = (x / bx, y / by, z / bz)
        return [v * k[i % 3] for i, v in enumerate(raw)]
    return _box(x, y, z)


def _rotation(deg: list[float]) -> list[list[float]]:
    """Euler XYZ (three.js default): R = Rx · Ry · Rz."""
    a, b, c = (math.radians(d) for d in deg)
    ca, sa, cb, sb, cc, sc = math.cos(a), math.sin(a), math.cos(b), math.sin(b), math.cos(c), math.sin(c)
    return [[cb * cc, -cb * sc, sb],
            [ca * sc + sa * sb * cc, ca * cc - sa * sb * sc, -sa * cb],
            [sa * sc - ca * sb * cc, sa * cc + ca * sb * sc, ca * cb]]


def world_triangles(part: dict, meshes: MeshStore | None = None) -> list[float]:
    tris = local_triangles(part, meshes)
    r = _rotation(part["rotation"])
    px, py, pz = part["position"]
    out = []
    for i in range(0, len(tris), 3):
        x, y, z = tris[i], tris[i + 1], tris[i + 2]
        out.extend((r[0][0] * x + r[0][1] * y + r[0][2] * z + px, r[1][0] * x + r[1][1] * y + r[1][2] * z + py,
                    r[2][0] * x + r[2][1] * y + r[2][2] * z + pz))
    return out


def all_triangles(bp: dict, meshes: MeshStore | None = None, parts: list[str] | None = None) -> list[tuple[dict, list[float]]]:
    chosen = [p for p in bp["parts"] if not parts or p["id"] in parts]
    if not chosen:
        raise ValueError("This blueprint has no parts to export.")
    return [(p, world_triangles(p, meshes)) for p in chosen]


# --- files ---------------------------------------------------------------------------------

def _z_up_mm(tris: list[float]) -> list[float]:
    out = []
    for i in range(0, len(tris), 3):
        out.extend((tris[i] * 1000, -tris[i + 2] * 1000, tris[i + 1] * 1000))
    return out


def to_stl(bp, meshes=None, parts=None) -> bytes:
    tris = [v for _, t in all_triangles(bp, meshes, parts) for v in t]
    return stl_bytes(_z_up_mm(tris), bp["name"][:70])


def _indexed(tris: list[float], digits: int = 6) -> tuple[list[tuple], list[int]]:
    seen: dict[tuple, int] = {}
    verts, idx = [], []
    for i in range(0, len(tris), 3):
        key = (round(tris[i], digits), round(tris[i + 1], digits), round(tris[i + 2], digits))
        k = seen.get(key)
        if k is None:
            k = seen[key] = len(verts)
            verts.append(key)
        idx.append(k)
    return verts, idx


def _safe(name: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:60] or "part"


def to_obj(bp, meshes=None, parts=None) -> bytes:
    lines = [f"# {bp['name']} — exported by Corvis (metres, y up)", f"# {len(bp['parts'])} parts"]
    base = 1
    for p, tris in all_triangles(bp, meshes, parts):
        verts, idx = _indexed(tris)
        lines.append(f"o {_safe(p['name'])}")
        lines.extend(f"v {x:.6f} {y:.6f} {z:.6f}" for x, y, z in verts)
        lines.extend(f"f {idx[i] + base} {idx[i + 1] + base} {idx[i + 2] + base}" for i in range(0, len(idx), 3))
        base += len(verts)
    return ("\n".join(lines) + "\n").encode("utf-8")


def to_3mf(bp, meshes=None, parts=None) -> bytes:
    objects, items = [], []
    for n, (p, tris) in enumerate(all_triangles(bp, meshes, parts), 1):
        verts, idx = _indexed(_z_up_mm(tris), 4)
        v = "".join(f'<vertex x="{x:.4f}" y="{y:.4f}" z="{z:.4f}"/>' for x, y, z in verts)
        t = "".join(f'<triangle v1="{idx[i]}" v2="{idx[i + 1]}" v3="{idx[i + 2]}"/>' for i in range(0, len(idx), 3))
        objects.append(f'<object id="{n}" type="model" name="{escape(p["name"])}"><mesh><vertices>{v}</vertices>'
                       f'<triangles>{t}</triangles></mesh></object>')
        items.append(f'<item objectid="{n}"/>')
    model = ('<?xml version="1.0" encoding="UTF-8"?><model unit="millimeter" xml:lang="en-US" '
             'xmlns="http://schemas.microsoft.com/3dmanufacturing/core/2015/02">'
             f'<metadata name="Title">{escape(bp["name"])}</metadata><metadata name="Application">Corvis</metadata>'
             f'<resources>{"".join(objects)}</resources><build>{"".join(items)}</build></model>')
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", '<?xml version="1.0" encoding="UTF-8"?><Types xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/'
                   'vnd.openxmlformats-package.relationships+xml"/><Default Extension="model" ContentType="application/'
                   'vnd.ms-package.3dmanufacturing-3dmodel+xml"/></Types>')
        z.writestr("_rels/.rels", '<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.'
                   'openxmlformats.org/package/2006/relationships"><Relationship Target="/3D/3dmodel.model" Id="rel0" '
                   'Type="http://schemas.microsoft.com/3dmanufacturing/2013/01/3dmodel"/></Relationships>')
        z.writestr("3D/3dmodel.model", model)
    return buf.getvalue()


def to_glb(bp, meshes=None, parts=None) -> bytes:
    binary = bytearray()
    doc = {"asset": {"version": "2.0", "generator": "Corvis"}, "scene": 0, "scenes": [{"name": bp["name"], "nodes": []}],
           "nodes": [], "meshes": [], "materials": [], "accessors": [], "bufferViews": [], "buffers": []}
    mats: dict[str, int] = {}
    for p, tris in all_triangles(bp, meshes, parts):
        normals = []
        for i in range(0, len(tris), 9):
            ax, ay, az, bx, by, bz, cx, cy, cz = tris[i:i + 9]
            ux, uy, uz, vx, vy, vz = bx - ax, by - ay, bz - az, cx - ax, cy - ay, cz - az
            nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
            ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
            normals.extend((nx / ln, ny / ln, nz / ln) * 3)
        key = p.get("color") or COLORS.get(p["material"], "#cccccc")
        if key not in mats:
            r, g, b = (int(key[k:k + 2], 16) / 255 for k in (1, 3, 5))
            mats[key] = len(doc["materials"])
            doc["materials"].append({"name": MATERIALS[p["material"]]["label"] if not p.get("color") else key,
                                     "pbrMetallicRoughness": {"baseColorFactor": [r ** 2.2, g ** 2.2, b ** 2.2, 1],
                                                              "metallicFactor": 0.3, "roughnessFactor": 0.6}})
        acc = []
        for data, mn_mx in ((tris, True), (normals, False)):
            off = len(binary)
            binary += struct.pack(f"<{len(data)}f", *data)
            doc["bufferViews"].append({"buffer": 0, "byteOffset": off, "byteLength": len(data) * 4, "target": 34962})
            a = {"bufferView": len(doc["bufferViews"]) - 1, "componentType": 5126, "count": len(data) // 3, "type": "VEC3"}
            if mn_mx:
                a["min"] = [min(data[i::3]) for i in range(3)]
                a["max"] = [max(data[i::3]) for i in range(3)]
            doc["accessors"].append(a)
            acc.append(len(doc["accessors"]) - 1)
        doc["meshes"].append({"name": p["name"], "primitives": [{"attributes": {"POSITION": acc[0], "NORMAL": acc[1]},
                                                                 "material": mats[key]}]})
        doc["nodes"].append({"name": p["name"], "mesh": len(doc["meshes"]) - 1})
        doc["scenes"][0]["nodes"].append(len(doc["nodes"]) - 1)
    doc["buffers"].append({"byteLength": len(binary)})
    js = json.dumps(doc, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    binary += b"\0" * (-len(binary) % 4)
    total = 12 + 8 + len(js) + 8 + len(binary)
    return (struct.pack("<4sII", b"glTF", 2, total) + struct.pack("<II", len(js), 0x4E4F534A) + js
            + struct.pack("<II", len(binary), 0x004E4942) + bytes(binary))


# --- 2D views (for the DXF and SVG blueprints) ---------------------------------------------

VIEWS = {   # name: (how a 3D point lands on the drawing, the direction the viewer looks from)
    "front": (lambda x, y, z: (x, y), (0, 0, 1)),
    "top": (lambda x, y, z: (x, -z), (0, 1, 0)),
    "side": (lambda x, y, z: (-z, y), (1, 0, 0)),
}


def _edges(tris: list[float], view_dir: tuple, angle: float = 30.0) -> list[tuple]:
    """Outline edges: sharp folds, open edges and silhouettes as seen from view_dir."""
    verts, idx = _indexed(tris, 5)
    normals = []
    for i in range(0, len(idx), 3):
        a, b, c = verts[idx[i]], verts[idx[i + 1]], verts[idx[i + 2]]
        u = [b[k] - a[k] for k in range(3)]
        v = [c[k] - a[k] for k in range(3)]
        n = (u[1] * v[2] - u[2] * v[1], u[2] * v[0] - u[0] * v[2], u[0] * v[1] - u[1] * v[0])
        ln = math.sqrt(sum(x * x for x in n))
        normals.append(tuple(x / ln for x in n) if ln > 1e-14 else None)
    faces: dict[tuple, list[int]] = {}
    for f in range(len(idx) // 3):
        tri = idx[f * 3: f * 3 + 3]
        if normals[f] is None:   # a collapsed sliver adds no outline
            continue
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            faces.setdefault((min(a, b), max(a, b)), []).append(f)
    cos_lim = math.cos(math.radians(angle))
    out = []
    for (a, b), fs in faces.items():
        keep = len(fs) != 2
        if not keep:
            n1, n2 = normals[fs[0]], normals[fs[1]]
            dot = sum(n1[k] * n2[k] for k in range(3))
            d1 = sum(n1[k] * view_dir[k] for k in range(3))
            d2 = sum(n2[k] * view_dir[k] for k in range(3))
            keep = dot < cos_lim or (d1 > 0) != (d2 > 0)
        if keep:
            out.append((verts[a], verts[b]))
    return out


def view_lines(bp: dict, meshes=None, parts=None) -> dict:
    """{view: [(x1, y1, x2, y2), ...]} in metres, plus the drawing's extent per view."""
    shapes = all_triangles(bp, meshes, parts)
    out = {}
    for name, (proj, d) in VIEWS.items():
        seen, lines = set(), []
        for _, tris in shapes:
            for a, b in _edges(tris, d):
                p, q = proj(*a), proj(*b)
                key = tuple(round(v, 4) for v in (p + q)) if p <= q else tuple(round(v, 4) for v in (q + p))
                if key in seen or (abs(p[0] - q[0]) < 1e-7 and abs(p[1] - q[1]) < 1e-7):
                    continue
                seen.add(key)
                lines.append((*p, *q))
        xs = [v for l in lines for v in (l[0], l[2])] or [0]
        ys = [v for l in lines for v in (l[1], l[3])] or [0]
        out[name] = {"lines": lines, "box": (min(xs), min(ys), max(xs), max(ys))}
    return out


def _fmt_len(m: float) -> str:
    if m >= 10:
        return f"{m:,.1f} m"
    if m >= 1:
        return f"{m:.3f} m"
    return f"{m * 1000:.1f} mm"


def to_dxf(bp, meshes=None, parts=None) -> bytes:
    views = view_lines(bp, meshes, parts)
    fx0, fy0, fx1, fy1 = views["front"]["box"]
    tx0, ty0, tx1, ty1 = views["top"]["box"]
    sx0, sy0, sx1, sy1 = views["side"]["box"]
    gap = max(fx1 - fx0, fy1 - fy0, 0.01) * 0.25
    # third-angle layout: top view above the front view, right side view to its right
    place = {"front": (-fx0, -fy0), "top": (-tx0, (fy1 - fy0) + gap - ty0),
             "side": ((fx1 - fx0) + gap - sx0, -sy0)}
    out = ["0", "SECTION", "2", "HEADER", "9", "$INSUNITS", "70", "4", "0", "ENDSEC", "0", "SECTION", "2", "ENTITIES"]
    for name, v in views.items():
        ox, oy = place[name]
        for x1, y1, x2, y2 in v["lines"]:
            out += ["0", "LINE", "8", name.upper(), "10", f"{(x1 + ox) * 1000:.3f}", "20", f"{(y1 + oy) * 1000:.3f}", "30", "0",
                    "11", f"{(x2 + ox) * 1000:.3f}", "21", f"{(y2 + oy) * 1000:.3f}", "31", "0"]
        x0, y0, x1, y1 = v["box"]
        h = max((y1 - y0), (x1 - x0)) * 1000 * 0.04 or 5
        label = f"{name.upper()}  {_fmt_len(x1 - x0)} x {_fmt_len(y1 - y0)}"
        out += ["0", "TEXT", "8", "TEXT", "10", f"{(x0 + ox) * 1000:.3f}", "20", f"{(y0 + oy) * 1000 - h * 2:.3f}", "30", "0",
                "40", f"{h:.3f}", "1", label]
    out += ["0", "TEXT", "8", "TEXT", "10", "0", "20", f"{-(fy1 - fy0) * 1000 * 0.25:.3f}", "30", "0",
            "40", f"{max(fx1 - fx0, 0.01) * 1000 * 0.05:.3f}", "1", f"{bp['name']} - Corvis blueprint - units: mm"]
    out += ["0", "ENDSEC", "0", "EOF"]
    return ("\n".join(out) + "\n").encode("ascii", "replace")


def _nice_scale(span_m: float, room_mm: float) -> int:
    """The smallest standard 1:N scale that makes span_m fit in room_mm."""
    need = span_m * 1000 / room_mm
    for mag in range(0, 9):
        for step in (1, 2, 5):
            n = step * 10 ** mag
            if n >= need:
                return n
    return 10 ** 9


def to_svg(bp, meshes=None, parts=None) -> bytes:
    views = view_lines(bp, meshes, parts)
    W, H, M = 420.0, 297.0, 14.0   # A3 landscape, mm
    fx0, fy0, fx1, fy1 = views["front"]["box"]
    tx0, ty0, tx1, ty1 = views["top"]["box"]
    sx0, sy0, sx1, sy1 = views["side"]["box"]
    width_m = (fx1 - fx0) + (sx1 - sx0)
    height_m = (fy1 - fy0) + (ty1 - ty0)
    n = max(_nice_scale(width_m, (W - 2 * M - 40) * 0.8), _nice_scale(height_m, (H - 2 * M - 70) * 0.8), 1)
    k = 1000 / n                         # metres -> sheet mm
    gap = 22.0
    fw, fh, th, sw = (fx1 - fx0) * k, (fy1 - fy0) * k, (ty1 - ty0) * k, (sx1 - sx0) * k
    left = M + 14 + max((W - 2 * M - 28 - (fw + gap + sw)) / 2, 0)
    bottom = M + 20 + th + gap + fh + max((H - 2 * M - 70 - (th + gap + fh)) / 2, 0)   # front view's lowest line
    # third-angle layout: top view above the front view, right side view to its right
    origin = {"front": (left - fx0 * k, bottom + fy0 * k),
              "top": (left - tx0 * k, bottom - fh - gap + ty0 * k),
              "side": (left + fw + gap - sx0 * k, bottom + sy0 * k)}

    def pt(view, x, y):
        ox, oy = origin[view]
        return ox + x * k, oy - y * k

    body = []
    for view, v in views.items():
        d = "".join(f"M{pt(view, l[0], l[1])[0]:.2f} {pt(view, l[0], l[1])[1]:.2f}"
                    f"L{pt(view, l[2], l[3])[0]:.2f} {pt(view, l[2], l[3])[1]:.2f}" for l in v["lines"])
        body.append(f'<path d="{d}" class="ln"/>')
        x0, y0, x1, y1 = v["box"]
        a, b = pt(view, x0, y0), pt(view, x1, y1)   # a: bottom-left, b: top-right on the sheet
        yd = a[1] + 7   # overall width under the view
        body.append(f'<path d="M{a[0]:.2f} {a[1] + 2:.2f}V{yd + 2:.2f}M{b[0]:.2f} {a[1] + 2:.2f}V{yd + 2:.2f}'
                    f'M{a[0]:.2f} {yd:.2f}H{b[0]:.2f}" class="dim" marker-start="url(#a)" marker-end="url(#a)"/>')
        body.append(f'<text x="{(a[0] + b[0]) / 2:.2f}" y="{yd - 1.5:.2f}" class="t" text-anchor="middle">{_fmt_len(x1 - x0)}</text>')
        xd = a[0] - 7   # overall height to its left
        body.append(f'<path d="M{a[0] - 2:.2f} {a[1]:.2f}H{xd - 2:.2f}M{a[0] - 2:.2f} {b[1]:.2f}H{xd - 2:.2f}'
                    f'M{xd:.2f} {a[1]:.2f}V{b[1]:.2f}" class="dim" marker-start="url(#a)" marker-end="url(#a)"/>')
        body.append(f'<text transform="translate({xd - 1.5:.2f} {(a[1] + b[1]) / 2:.2f}) rotate(-90)" class="t" '
                    f'text-anchor="middle">{_fmt_len(y1 - y0)}</text>')
        body.append(f'<text x="{a[0]:.2f}" y="{b[1] - 4:.2f}" class="h">{view.upper()} VIEW</text>')
    src = bp.get("source") or {}
    from .blueprints import SOURCE_KINDS
    srcline = (f"Source: {src.get('site', '')} {('· ' + src['license']) if src.get('license') else ''} "
               f"({SOURCE_KINDS.get(src.get('kind', ''), '')})") if src else "Source: designed in Corvis"
    tb_x, tb_y = W - M - 150, H - M - 30
    title = (f'<rect x="{tb_x}" y="{tb_y}" width="150" height="30" class="frame"/>'
             f'<path d="M{tb_x} {tb_y + 12}H{tb_x + 150}M{tb_x + 75} {tb_y + 12}V{tb_y + 30}" class="frame"/>'
             f'<text x="{tb_x + 3}" y="{tb_y + 8.5}" class="big">{escape(bp["name"][:40])}</text>'
             f'<text x="{tb_x + 3}" y="{tb_y + 18}" class="t">SCALE 1:{n}</text>'
             f'<text x="{tb_x + 3}" y="{tb_y + 25}" class="t">{len(bp["parts"])} PARTS · THIRD-ANGLE</text>'
             f'<text x="{tb_x + 78}" y="{tb_y + 18}" class="t">{dt.date.today().isoformat()}</text>'
             f'<text x="{tb_x + 78}" y="{tb_y + 25}" class="t">DRAWN BY CORVIS</text>'
             f'<text x="{M + 3}" y="{H - M - 3}" class="t">{escape(srcline[:150])}</text>')
    svg = (f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">'
           '<defs><pattern id="g" width="10" height="10" patternUnits="userSpaceOnUse"><path d="M10 0H0V10" fill="none" '
           'stroke="#3d6fb6" stroke-width=".15"/></pattern><marker id="a" viewBox="0 0 6 6" refX="3" refY="3" '
           'markerWidth="4" markerHeight="4" orient="auto-start-reverse"><path d="M0 0L6 3L0 6z" fill="#e8f1ff"/></marker>'
           '<style>.ln{fill:none;stroke:#f2f7ff;stroke-width:.25;stroke-linecap:round}.dim{fill:none;stroke:#bcd3f5;'
           'stroke-width:.18}.frame{fill:none;stroke:#e8f1ff;stroke-width:.5}.t{font:3px monospace;fill:#e8f1ff}'
           '.h{font:bold 3.4px monospace;fill:#e8f1ff;letter-spacing:.3px}.big{font:bold 5px monospace;fill:#fff}</style></defs>'
           f'<rect width="{W}" height="{H}" fill="#123e7c"/><rect width="{W}" height="{H}" fill="url(#g)"/>'
           f'<rect x="{M}" y="{M}" width="{W - 2 * M}" height="{H - 2 * M}" class="frame"/>'
           + "".join(body) + title + "</svg>")
    return svg.encode("utf-8")


WRITERS = {"stl": to_stl, "3mf": to_3mf, "obj": to_obj, "glb": to_glb, "dxf": to_dxf, "svg": to_svg}


def export(bp: dict, fmt: str, meshes: MeshStore | None = None, parts: list[str] | None = None) -> tuple[bytes, str]:
    fmt = fmt.lower().lstrip(".")
    if fmt == "gltf":
        fmt = "glb"
    if fmt not in WRITERS:
        raise ValueError(f"Corvis can export: {', '.join(FORMATS)}.")
    stem = "".join(ch if ch.isalnum() or ch in "-_ " else "" for ch in bp["name"]).strip().replace(" ", "_") or "blueprint"
    return WRITERS[fmt](bp, meshes, parts), f"{stem}.{fmt}"
