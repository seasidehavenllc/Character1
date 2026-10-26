"""3D model import for blueprints: read real models and turn them into hologram parts.

Reads STL (binary and text), OBJ, glTF/GLB, PLY (text and binary) and 3MF without any extra
libraries. A model becomes components: named meshes (glTF nodes, OBJ objects, 3MF objects),
or, for a single solid like most STL files, the separate pieces it's made of. Each component
is stored as its own small STL file in data/blueprints/assets/ so the hologram can show it,
split it off, move it, and export it again.

Everything is converted to metres with y up, resting on the floor (y = 0).
"""
from __future__ import annotations

import base64
import io
import json
import math
import os
import re
import struct
import threading
import time
import uuid
import zipfile
import xml.etree.ElementTree as ET
from array import array
from pathlib import Path

FORMATS = ("stl", "obj", "glb", "gltf", "ply", "3mf")
MAX_BYTES = 80 * 1024 * 1024
MAX_TRIANGLES = 400_000      # above this a model is simplified so it stays smooth to work with
MAX_COMPONENTS = 80
UNITS = {"mm": 0.001, "cm": 0.01, "m": 1.0, "in": 0.0254, "ft": 0.3048}


class ModelError(ValueError):
    pass


class Component:
    """One mesh: flat xyz positions and triangle indices."""

    def __init__(self, name: str, positions=None, indices=None):
        self.name = name
        self.positions = positions if positions is not None else array("f")
        self.indices = indices if indices is not None else array("I")

    @property
    def triangles(self) -> int:
        return len(self.indices) // 3

    def bbox(self) -> tuple[list[float], list[float]]:
        p = self.positions
        if not len(p):
            return [0, 0, 0], [0, 0, 0]
        lo = [min(p[i::3]) for i in range(3)]
        hi = [max(p[i::3]) for i in range(3)]
        return lo, hi


# --- reading ------------------------------------------------------------------------------

def detect_format(name: str, data: bytes) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if data[:4] == b"glTF":
        return "glb"
    if data[:2] == b"PK":
        return "3mf" if ext != "zip" else "zip"
    if data[:3] == b"ply":
        return "ply"
    if ext in FORMATS:
        return ext
    head = data[:2000].lstrip()
    if head.startswith(b"{") and b'"asset"' in data[:20000]:
        return "gltf"
    if head.startswith(b"solid") or (len(data) > 84 and 84 + 50 * struct.unpack("<I", data[80:84])[0] == len(data)):
        return "stl"
    if re.search(rb"^\s*v\s+-?[\d.]", data[:20000], re.M):
        return "obj"
    raise ModelError("That doesn't look like a 3D model Corvis can read (STL, OBJ, GLB/glTF, PLY or 3MF).")


def _weld(name: str, flat: array) -> Component:
    """Triangle soup -> indexed mesh (shared corners merged)."""
    c = Component(name)
    seen: dict[tuple, int] = {}
    for i in range(0, len(flat), 3):
        key = (round(flat[i], 6), round(flat[i + 1], 6), round(flat[i + 2], 6))
        idx = seen.get(key)
        if idx is None:
            idx = seen[key] = len(seen)
            c.positions.extend(key)
        c.indices.append(idx)
    return c


def read_stl(data: bytes, name: str = "Model") -> list[Component]:
    if len(data) >= 84:
        n = struct.unpack("<I", data[80:84])[0]
        if 84 + 50 * n == len(data):
            flat = array("f")
            for i in range(n):
                off = 84 + 50 * i + 12
                flat.extend(struct.unpack_from("<9f", data, off))
            return [_weld(name, flat)]
    text = data.decode("utf-8", errors="replace")
    nums = re.findall(r"vertex\s+(\S+)\s+(\S+)\s+(\S+)", text)
    if not nums:
        raise ModelError("This STL file has no triangles.")
    flat = array("f", (float(v) for xyz in nums for v in xyz))
    flat = flat[: len(flat) - len(flat) % 9]
    m = re.match(r"\s*solid\s+(.+)", text)
    return [_weld((m.group(1).strip()[:60] if m else "") or name, flat)]


def read_obj(data: bytes, name: str = "Model") -> list[Component]:
    verts: list[tuple[float, float, float]] = []
    groups: list[tuple[str, list[int]]] = []
    current: list[int] | None = None
    cname = name
    for raw in data.decode("utf-8", errors="replace").splitlines():
        line = raw.strip()
        if line.startswith("v "):
            parts = line.split()
            try:
                verts.append((float(parts[1]), float(parts[2]), float(parts[3])))
            except (IndexError, ValueError):
                continue
        elif line.startswith(("o ", "g ")):
            cname = line[2:].strip().replace("_", " ")[:60] or cname
            current = None
        elif line.startswith("f "):
            if current is None:
                current = []
                groups.append((cname, current))
            idx = []
            for tok in line.split()[1:]:
                try:
                    k = int(tok.split("/")[0])
                except ValueError:
                    continue
                idx.append(k - 1 if k > 0 else len(verts) + k)
            for j in range(1, len(idx) - 1):   # fan: polygons become triangles
                current.extend((idx[0], idx[j], idx[j + 1]))
    if not groups:
        raise ModelError("This OBJ file has no faces.")
    comps = []
    for gname, tri in groups:
        remap: dict[int, int] = {}
        c = Component(gname)
        for k in tri:
            if not 0 <= k < len(verts):
                continue
            if k not in remap:
                remap[k] = len(remap)
                c.positions.extend(verts[k])
            c.indices.append(remap[k])
        c.indices = c.indices[: len(c.indices) - len(c.indices) % 3]
        if c.triangles:
            comps.append(c)
    return _merge_same_names(comps)


def _merge_same_names(comps: list[Component]) -> list[Component]:
    out: dict[str, Component] = {}
    for c in comps:
        if c.name in out:
            base = len(out[c.name].positions) // 3
            out[c.name].positions.extend(c.positions)
            out[c.name].indices.extend(i + base for i in c.indices)
        else:
            out[c.name] = c
    return list(out.values())


# glTF ------------------------------------------------------------------------------------
_CTYPES = {5120: ("b", 1), 5121: ("B", 1), 5122: ("h", 2), 5123: ("H", 2), 5125: ("I", 4), 5126: ("f", 4)}
_NCOMP = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def _mat_mul(a: list[float], b: list[float]) -> list[float]:   # column-major 4x4
    return [sum(a[r + 4 * k] * b[k + 4 * c] for k in range(4)) for c in range(4) for r in range(4)]


def _node_matrix(node: dict) -> list[float]:
    if "matrix" in node:
        return [float(v) for v in node["matrix"]]
    tx, ty, tz = node.get("translation", [0, 0, 0])
    qx, qy, qz, qw = node.get("rotation", [0, 0, 0, 1])
    sx, sy, sz = node.get("scale", [1, 1, 1])
    r = [1 - 2 * (qy * qy + qz * qz), 2 * (qx * qy + qz * qw), 2 * (qx * qz - qy * qw), 0,
         2 * (qx * qy - qz * qw), 1 - 2 * (qx * qx + qz * qz), 2 * (qy * qz + qx * qw), 0,
         2 * (qx * qz + qy * qw), 2 * (qy * qz - qx * qw), 1 - 2 * (qx * qx + qy * qy), 0, 0, 0, 0, 1]
    s = [sx, 0, 0, 0, 0, sy, 0, 0, 0, 0, sz, 0, 0, 0, 0, 1]
    t = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, tx, ty, tz, 1]
    return _mat_mul(t, _mat_mul(r, s))


def read_gltf(data: bytes, name: str = "Model") -> list[Component]:
    bin_chunk = b""
    if data[:4] == b"glTF":
        length = struct.unpack_from("<I", data, 8)[0]
        off, doc = 12, None
        while off < min(length, len(data)):
            clen, ctype = struct.unpack_from("<II", data, off)
            chunk = data[off + 8: off + 8 + clen]
            if ctype == 0x4E4F534A:
                doc = json.loads(chunk.decode("utf-8"))
            elif ctype == 0x004E4942:
                bin_chunk = chunk
            off += 8 + clen
        if doc is None:
            raise ModelError("This GLB file has no scene description.")
    else:
        doc = json.loads(data.decode("utf-8"))
    buffers = []
    for b in doc.get("buffers", []):
        uri = b.get("uri")
        if uri is None:
            buffers.append(bin_chunk)
        elif uri.startswith("data:"):
            buffers.append(base64.b64decode(uri.split(",", 1)[1]))
        else:
            raise ModelError("This .gltf file keeps its data in a separate file. Upload the .glb version instead.")

    def accessor(i: int) -> list:
        acc = doc["accessors"][i]
        view = doc["bufferViews"][acc["bufferView"]]
        fmt, size = _CTYPES[acc["componentType"]]
        n = _NCOMP[acc["type"]]
        buf = buffers[view["buffer"]]
        start = view.get("byteOffset", 0) + acc.get("byteOffset", 0)
        stride = view.get("byteStride") or size * n
        if stride == size * n:
            out = array(fmt)
            out.frombytes(buf[start: start + acc["count"] * stride])
            return list(out)
        vals = []
        for k in range(acc["count"]):
            vals.extend(struct.unpack_from(f"<{n}{fmt}", buf, start + k * stride))
        return vals

    comps: list[Component] = []

    def visit(ni: int, parent: list[float], depth: int = 0) -> None:
        if depth > 64:
            return
        node = doc["nodes"][ni]
        m = _mat_mul(parent, _node_matrix(node))
        if "mesh" in node:
            mesh = doc["meshes"][node["mesh"]]
            c = Component((node.get("name") or mesh.get("name") or f"Part {len(comps) + 1}")[:60])
            for prim in mesh.get("primitives", []):
                if prim.get("mode", 4) != 4 or "POSITION" not in prim.get("attributes", {}):
                    continue
                pos = accessor(prim["attributes"]["POSITION"])
                base = len(c.positions) // 3
                for k in range(0, len(pos), 3):
                    x, y, z = pos[k], pos[k + 1], pos[k + 2]
                    c.positions.extend((m[0] * x + m[4] * y + m[8] * z + m[12], m[1] * x + m[5] * y + m[9] * z + m[13],
                                        m[2] * x + m[6] * y + m[10] * z + m[14]))
                idx = accessor(prim["indices"]) if "indices" in prim else list(range(len(pos) // 3))
                c.indices.extend(base + int(i) for i in idx[: len(idx) - len(idx) % 3])
            if c.triangles:
                comps.append(c)
        for child in node.get("children", []):
            visit(child, m, depth + 1)

    identity = [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    scenes = doc.get("scenes") or [{"nodes": list(range(len(doc.get("nodes", []))))}]
    for ni in scenes[doc.get("scene", 0)].get("nodes", []):
        visit(ni, identity)
    if not comps:
        raise ModelError("This glTF model has no triangle meshes.")
    return _merge_same_names(comps)


def read_ply(data: bytes, name: str = "Model") -> list[Component]:
    end = data.find(b"end_header")
    if end < 0:
        raise ModelError("This PLY file has no header.")
    header = data[:end].decode("ascii", errors="replace").splitlines()
    body = data[data.index(b"\n", end) + 1:]
    fmt = "ascii"
    elements: list[tuple[str, int, list]] = []
    for line in header:
        t = line.split()
        if not t:
            continue
        if t[0] == "format":
            fmt = t[1]
        elif t[0] == "element":
            elements.append((t[1], int(t[2]), []))
        elif t[0] == "property" and elements:
            elements[-1][2].append(t[1:])
    types = {"char": "b", "int8": "b", "uchar": "B", "uint8": "B", "short": "h", "int16": "h", "ushort": "H",
             "uint16": "H", "int": "i", "int32": "i", "uint": "I", "uint32": "I", "float": "f", "float32": "f",
             "double": "d", "float64": "d"}
    end_ch = "<" if fmt != "binary_big_endian" else ">"
    verts: list[tuple] = []
    c = Component(name)
    tokens = iter(body.decode("ascii", errors="replace").split()) if fmt == "ascii" else None
    off = 0
    for ename, count, props in elements:
        for _ in range(count):
            row = {}
            for prop in props:
                if prop[0] == "list":
                    if tokens is not None:
                        n = int(next(tokens))
                        vals = [int(float(next(tokens))) for _ in range(n)]
                    else:
                        cf, vf = types[prop[1]], types[prop[2]]
                        n = struct.unpack_from(end_ch + cf, body, off)[0]
                        off += struct.calcsize(cf)
                        vals = list(struct.unpack_from(f"{end_ch}{n}{vf}", body, off))
                        off += n * struct.calcsize(vf)
                    row[prop[-1]] = vals
                else:
                    if tokens is not None:
                        row[prop[-1]] = float(next(tokens))
                    else:
                        f = types[prop[0]]
                        row[prop[-1]] = struct.unpack_from(end_ch + f, body, off)[0]
                        off += struct.calcsize(f)
            if ename == "vertex":
                verts.append((row.get("x", 0.0), row.get("y", 0.0), row.get("z", 0.0)))
            elif ename == "face":
                idx = row.get("vertex_indices") or row.get("vertex_index") or []
                for j in range(1, len(idx) - 1):
                    c.indices.extend((idx[0], idx[j], idx[j + 1]))
    for v in verts:
        c.positions.extend(v)
    if not c.triangles:
        raise ModelError("This PLY file has no faces (it may be a point cloud).")
    return [c]


def read_3mf(data: bytes, name: str = "Model") -> list[Component]:
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ModelError("This 3MF file is damaged.") from e
    model_name = next((n for n in z.namelist() if n.lower().endswith(".model")), None)
    if not model_name or z.getinfo(model_name).file_size > MAX_BYTES * 4:
        raise ModelError("This 3MF file has no model inside.")
    root = ET.fromstring(z.read(model_name))
    ns = {"m": root.tag.split("}")[0].strip("{")} if root.tag.startswith("{") else {"m": ""}
    q = (lambda tag: f"m:{tag}") if ns["m"] else (lambda tag: tag)
    objects = {}
    for obj in root.iter(f"{{{ns['m']}}}object" if ns["m"] else "object"):
        mesh = obj.find(q("mesh"), ns)
        if mesh is None:
            continue
        c = Component((obj.get("name") or f"Part {obj.get('id')}")[:60])
        for v in mesh.find(q("vertices"), ns):
            c.positions.extend((float(v.get("x")), float(v.get("y")), float(v.get("z"))))
        for t in mesh.find(q("triangles"), ns):
            c.indices.extend((int(t.get("v1")), int(t.get("v2")), int(t.get("v3"))))
        objects[obj.get("id")] = c
    comps = []
    build = root.find(q("build"), ns)
    for item in (build if build is not None else []):
        c = objects.get(item.get("objectid"))
        if c is None:
            continue
        t = [float(x) for x in (item.get("transform") or "1 0 0 0 1 0 0 0 1 0 0 0").split()]
        moved = Component(c.name, array("f"), array("I", c.indices))
        p = c.positions
        for k in range(0, len(p), 3):
            x, y, zz = p[k], p[k + 1], p[k + 2]
            moved.positions.extend((x * t[0] + y * t[3] + zz * t[6] + t[9], x * t[1] + y * t[4] + zz * t[7] + t[10],
                                    x * t[2] + y * t[5] + zz * t[8] + t[11]))
        comps.append(moved)
    comps = comps or list(objects.values())
    if not comps:
        raise ModelError("This 3MF file has no meshes.")
    return _merge_same_names(comps)


def unzip_model(data: bytes) -> tuple[str, bytes]:
    """A .zip download: pick the model file inside (the biggest readable one)."""
    try:
        z = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise ModelError("That zip file is damaged.") from e
    best = None
    for info in z.infolist():
        ext = info.filename.rsplit(".", 1)[-1].lower()
        if ext in FORMATS and ext != "gltf" and info.file_size <= MAX_BYTES and (best is None or info.file_size > best.file_size):
            best = info
    if best is None:
        raise ModelError("That zip has no STL, OBJ, GLB, PLY or 3MF model inside.")
    return Path(best.filename).name, z.read(best)


READERS = {"stl": read_stl, "obj": read_obj, "glb": read_gltf, "gltf": read_gltf, "ply": read_ply, "3mf": read_3mf}


def read_model(name: str, data: bytes) -> tuple[list[Component], str]:
    """The model's components, and its format."""
    if len(data) > MAX_BYTES:
        raise ModelError(f"That model is over {MAX_BYTES // (1024 * 1024)} MB.")
    if not data:
        raise ModelError("That file is empty.")
    fmt = detect_format(name, data)
    if fmt == "zip":
        name, data = unzip_model(data)
        fmt = detect_format(name, data)
    stem = re.sub(r"[_-]+", " ", Path(name).stem).strip()[:60] or "Model"
    try:
        return READERS[fmt](data, stem), fmt
    except ModelError:
        raise
    except Exception as e:   # a damaged file shouldn't crash anything
        raise ModelError(f"Couldn't read that {fmt.upper()} file: {type(e).__name__}: {e}") from e


# --- shaping the model ---------------------------------------------------------------------

def split_pieces(c: Component, limit: int = MAX_COMPONENTS) -> list[Component]:
    """A single solid made of separate pieces -> one component per piece (biggest first)."""
    n = len(c.positions) // 3
    parent = list(range(n))

    def find(a: int) -> int:
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    idx = c.indices
    for i in range(0, len(idx), 3):
        a, b, d = find(idx[i]), find(idx[i + 1]), find(idx[i + 2])
        parent[b] = a
        parent[find(d)] = a
    tris: dict[int, list[int]] = {}
    for i in range(0, len(idx), 3):
        tris.setdefault(find(idx[i]), []).append(i)
    if len(tris) <= 1:
        return [c]
    groups = sorted(tris.values(), key=len, reverse=True)
    keep, rest = groups[: limit - 1], [t for g in groups[limit - 1:] for t in g]
    out = []
    for k, g in enumerate(keep + ([rest] if rest else [])):
        piece = Component(f"{c.name} · part {k + 1}" if k < len(keep) else f"{c.name} · small details")
        remap: dict[int, int] = {}
        for t in g:
            for v in idx[t: t + 3]:
                if v not in remap:
                    remap[v] = len(remap)
                    piece.positions.extend(c.positions[v * 3: v * 3 + 3])
                piece.indices.append(remap[v])
        out.append(piece)
    return out


def simplify(comps: list[Component], max_triangles: int = MAX_TRIANGLES) -> list[Component]:
    """Vertex clustering: snap corners to a grid and drop collapsed triangles until it fits."""
    total = sum(c.triangles for c in comps)
    if total <= max_triangles:
        return comps
    lo = [min(c.bbox()[0][i] for c in comps) for i in range(3)]
    hi = [max(c.bbox()[1][i] for c in comps) for i in range(3)]
    span = max(hi[i] - lo[i] for i in range(3)) or 1.0
    for cells in (1024, 768, 512, 384, 256, 192, 128, 96, 64, 48, 32, 24, 16):
        cell = span / cells
        out = []
        for c in comps:
            s = Component(c.name)
            snap: dict[tuple, int] = {}
            p = c.positions
            mapped = []
            for v in range(len(p) // 3):
                key = (round((p[v * 3] - lo[0]) / cell), round((p[v * 3 + 1] - lo[1]) / cell), round((p[v * 3 + 2] - lo[2]) / cell))
                k = snap.get(key)
                if k is None:
                    k = snap[key] = len(snap)
                    s.positions.extend((lo[0] + key[0] * cell, lo[1] + key[1] * cell, lo[2] + key[2] * cell))
                mapped.append(k)
            seen = set()
            for i in range(0, len(c.indices), 3):
                a, b, d = mapped[c.indices[i]], mapped[c.indices[i + 1]], mapped[c.indices[i + 2]]
                if a == b or b == d or a == d:
                    continue
                key = tuple(sorted((a, b, d)))
                if key in seen:
                    continue
                seen.add(key)
                s.indices.extend((a, b, d))
            if s.triangles:
                out.append(s)
        if sum(c.triangles for c in out) <= max_triangles:
            return out
    return out


def normalise(comps: list[Component], units: str = "auto", up: str = "auto", fmt: str = "stl",
              fit: tuple[str, float] | None = None) -> float:
    """In place: z-up files turned y-up, scaled to metres (or to a known real size), centred on
    the floor. Returns the scale used."""
    up = up if up in ("y", "z") else ("y" if fmt in ("glb", "gltf") else "z")
    if up == "z":
        for c in comps:
            p = c.positions
            for k in range(0, len(p), 3):
                p[k + 1], p[k + 2] = p[k + 2], -p[k + 1]
    lo = [min(c.bbox()[0][i] for c in comps) for i in range(3)]
    hi = [max(c.bbox()[1][i] for c in comps) for i in range(3)]
    dims = [hi[i] - lo[i] for i in range(3)]
    if fit and fit[1] > 0:
        axis = {"height": 1, "length": None, "width": None}.get(fit[0], 1)
        current = dims[1] if axis == 1 else (max(dims[0], dims[2]) if fit[0] == "length" else min(dims[0], dims[2]))
        scale = fit[1] / current if current else 1.0
    elif units in UNITS:
        scale = UNITS[units]
    elif fmt in ("glb", "gltf"):   # glTF is always in metres
        scale = 1.0
    else:   # guess: models for printing are in millimetres; bigger numbers are surely not metres
        biggest = max(dims) or 1
        scale = 0.001 if biggest > 20 else 1.0
    cx, cz = (lo[0] + hi[0]) / 2, (lo[2] + hi[2]) / 2
    for c in comps:
        p = c.positions
        for k in range(0, len(p), 3):
            p[k] = (p[k] - cx) * scale
            p[k + 1] = (p[k + 1] - lo[1]) * scale
            p[k + 2] = (p[k + 2] - cz) * scale
    return scale


def mesh_volume(c: Component) -> float:
    """Enclosed volume (signed tetrahedra; exact for closed meshes, a good estimate otherwise)."""
    p, idx, v = c.positions, c.indices, 0.0
    for i in range(0, len(idx), 3):
        a, b, d = idx[i] * 3, idx[i + 1] * 3, idx[i + 2] * 3
        v += (p[a] * (p[b + 1] * p[d + 2] - p[b + 2] * p[d + 1])
              - p[a + 1] * (p[b] * p[d + 2] - p[b + 2] * p[d])
              + p[a + 2] * (p[b] * p[d + 1] - p[b + 1] * p[d])) / 6
    return abs(v)


def stl_bytes(triangles: list | array, name: str = "corvis") -> bytes:
    """Binary STL from a flat list of 9 floats per triangle (normals are computed)."""
    n = len(triangles) // 9
    out = bytearray(name.encode("ascii", "replace")[:80].ljust(80, b" "))
    out += struct.pack("<I", n)
    for i in range(n):
        x1, y1, z1, x2, y2, z2, x3, y3, z3 = triangles[i * 9: i * 9 + 9]
        ux, uy, uz, vx, vy, vz = x2 - x1, y2 - y1, z2 - z1, x3 - x1, y3 - y1, z3 - z1
        nx, ny, nz = uy * vz - uz * vy, uz * vx - ux * vz, ux * vy - uy * vx
        ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
        out += struct.pack("<12fH", nx / ln, ny / ln, nz / ln, x1, y1, z1, x2, y2, z2, x3, y3, z3, 0)
    return bytes(out)


def soup(c: Component, offset: list[float] | None = None) -> array:
    ox, oy, oz = offset or (0.0, 0.0, 0.0)
    p, out = c.positions, array("f")
    for i in c.indices:
        out.extend((p[i * 3] - ox, p[i * 3 + 1] - oy, p[i * 3 + 2] - oz))
    return out


# --- storage ------------------------------------------------------------------------------

class MeshStore:
    """Mesh assets: one centred binary STL per component, plus its facts."""

    def __init__(self, data_dir: str | Path):
        self.root = Path(data_dir) / "blueprints" / "assets"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def path(self, aid: str) -> Path:
        if not re.fullmatch(r"[a-f0-9]{14}", aid or ""):
            raise KeyError(aid)
        return self.root / f"{aid}.stl"

    def meta(self, aid: str) -> dict:
        try:
            return json.loads(self.path(aid).with_suffix(".json").read_text(encoding="utf-8"))
        except FileNotFoundError:
            raise KeyError(aid) from None

    def triangles(self, aid: str) -> array:
        data = self.path(aid).read_bytes()
        n = struct.unpack("<I", data[80:84])[0]
        out = array("f")
        for i in range(n):
            out.extend(struct.unpack_from("<9f", data, 84 + 50 * i + 12))
        return out

    def save(self, c: Component, source: dict | None = None) -> dict:
        """Store a component centred on its own middle; returns its facts (and where it sat)."""
        lo, hi = c.bbox()
        centre = [(lo[i] + hi[i]) / 2 for i in range(3)]
        tris = soup(c, centre)
        aid = uuid.uuid4().hex[:14]
        meta = {"id": aid, "name": c.name, "triangles": c.triangles,
                "bbox": [round(max(hi[i] - lo[i], 1e-5), 6) for i in range(3)],
                "volume": mesh_volume(c), "source": source or {}, "created": time.time()}
        with self._lock:
            tmp = self.path(aid).with_suffix(".tmp")
            tmp.write_bytes(stl_bytes(tris, c.name))
            os.replace(tmp, self.path(aid))
            self.path(aid).with_suffix(".json").write_text(json.dumps(meta), encoding="utf-8")
        return {**meta, "centre": centre}


def import_model(store: MeshStore, name: str, data: bytes, units: str = "auto", up: str = "auto",
                 fit: tuple[str, float] | None = None, source: dict | None = None) -> tuple[list[dict], dict]:
    """Read a model file and store its components. Returns (parts-to-be, facts about the import)."""
    comps, fmt = read_model(name, data)
    if len(comps) == 1:
        comps = split_pieces(comps[0])
    elif len(comps) > MAX_COMPONENTS:
        comps.sort(key=lambda c: c.triangles, reverse=True)
        rest = Component("Small details")
        for c in comps[MAX_COMPONENTS - 1:]:
            base = len(rest.positions) // 3
            rest.positions.extend(c.positions)
            rest.indices.extend(i + base for i in c.indices)
        comps = comps[:MAX_COMPONENTS - 1] + [rest]
    original = sum(c.triangles for c in comps)
    comps = simplify(comps)
    scale = normalise(comps, units, up, fmt, fit)
    parts = []
    for c in comps:
        m = store.save(c, source)
        # material and fill are a guess (a 3D print in PLA); the owner or Corvis can set the real ones
        parts.append({"name": c.name[:60], "shape": "mesh", "material": "pla", "infill": 0.2,
                      "position": [round(v, 5) for v in m["centre"]],
                      "size": m["bbox"], "mesh": {"id": m["id"], "bbox": m["bbox"], "volume": m["volume"]}})
    lo = [min(c.bbox()[0][i] for c in comps) for i in range(3)]
    hi = [max(c.bbox()[1][i] for c in comps) for i in range(3)]
    facts = {"components": len(parts), "triangles": sum(c.triangles for c in comps), "original_triangles": original,
             "simplified": original > MAX_TRIANGLES, "scale": scale,
             "size_m": [round(hi[i] - lo[i], 4) for i in range(3)]}
    return parts, facts
