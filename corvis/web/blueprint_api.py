"""Hologram workshop API beyond the basics in server.py: importing models (uploaded or found
online), the live channel Corvis uses to steer the hologram, undo, blueprint files and the
shape library."""
from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response
from starlette.routing import Route

from .. import blueprint_finder as finder
from .. import blueprint_geom as geom
from .. import blueprint_sim
from ..blueprints import BlueprintStore
from ..internet import WebError
from ..meshes import MAX_BYTES, MeshStore, ModelError, import_model
from ..shape_library import ShapeLibrary


def blueprint_routes(cfg: dict, data_dir: Path, store: BlueprintStore) -> list[Route]:
    meshes = MeshStore(data_dir)
    library = ShapeLibrary(data_dir)

    def body(data, status: int = 200):
        return JSONResponse(data, status_code=status)

    def error(message: str, status: int = 400):
        return JSONResponse({"error": message}, status_code=status)

    def fit_from(q) -> tuple[str, float] | None:
        for key, axis in (("real_height_m", "height"), ("real_length_m", "length"), ("height", "height"), ("length", "length")):
            try:
                v = float(q.get(key) or 0)
            except (TypeError, ValueError):
                v = 0
            if v > 0:
                return axis, v
        return None

    def finish_import(name: str, data: bytes, q, source: dict) -> dict:
        parts, facts = import_model(meshes, name, data, units=str(q.get("units") or "auto"),
                                    up=str(q.get("up") or "auto"), fit=fit_from(q), source=source)
        label = (str(q.get("label") or q.get("title") or "").strip() or source.get("title") or name.rsplit(".", 1)[0])[:80]
        into = str(q.get("into") or "")
        if into:
            bp = store.edit(into, add=parts)
        else:
            bp = store.create(label, "blank", f"Imported from {source.get('site') or 'a file'}.", parts, source=source)
        learned = library.learn(bp["parts"][-len(parts):], label, source)
        return {"blueprint": bp, "summary": blueprint_sim.summary(bp), "facts": facts, "learned": learned}

    async def live(request: Request):
        return body(store.live())

    async def upload_model(request: Request):
        q = request.query_params
        received = bytearray()
        async for chunk in request.stream():
            received.extend(chunk)
            if len(received) > MAX_BYTES:
                return error(f"That model is over {MAX_BYTES // (1024 * 1024)} MB.", 413)
        name = str(q.get("name") or "model.stl")
        title = " ".join(name.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").split()).capitalize()[:80] or "Model"
        source = {"title": title, "site": "your file", "kind": "upload"}
        try:
            return body(await asyncio.to_thread(finish_import, name, bytes(received), q, source), 201)
        except (ModelError, KeyError, ValueError) as e:
            return error(str(e.args[0] if e.args else e))

    async def find(request: Request):
        data = await request.json()
        return body(await asyncio.to_thread(finder.find, str(data.get("query") or ""), cfg, data_dir))

    async def import_url(request: Request):
        data = await request.json()
        url = str(data.get("url") or "")
        if not url:
            return error("Give the model's web address.")
        src = data.get("source") if isinstance(data.get("source"), dict) else {}
        source = {"title": src.get("title") or "", "url": src.get("page") or url, "site": src.get("site") or "",
                  "author": src.get("author") or "", "license": src.get("license") or "unknown",
                  "kind": src.get("kind") if src.get("kind") in ("official", "community") else "community"}
        try:
            name, raw = await asyncio.to_thread(finder.download, url, cfg)
            return body(await asyncio.to_thread(finish_import, name, raw, data, source), 201)
        except (WebError, ModelError, KeyError, ValueError) as e:
            return error(str(e.args[0] if e.args else e))

    async def asset(request: Request):
        try:
            path = meshes.path(request.path_params["aid"])
        except KeyError:
            return error("Not found.", 404)
        if not path.is_file():
            return error("Not found.", 404)
        return FileResponse(path, media_type="application/octet-stream",
                            headers={"X-Content-Type-Options": "nosniff", "Cache-Control": "private, max-age=31536000, immutable"})

    async def undo(request: Request):
        try:
            bp = store.undo(request.path_params["bid"])
        except KeyError:
            return error("Blueprint not found.", 404)
        except ValueError as e:
            return error(str(e))
        return body({"blueprint": bp, "summary": blueprint_sim.summary(bp), "can_undo": store.can_undo(bp["id"])})

    async def export(request: Request):
        try:
            bp = store.get(request.path_params["bid"])
        except KeyError:
            return error("Blueprint not found.", 404)
        fmt = str(request.query_params.get("format") or "stl")
        parts = [p for p in str(request.query_params.get("parts") or "").split(",") if p] or None
        try:
            data, name = await asyncio.to_thread(geom.export, bp, fmt, meshes, parts)
        except ValueError as e:
            return error(str(e))
        return Response(data, media_type="application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="{name}"', "X-Content-Type-Options": "nosniff"})

    async def list_shapes(request: Request):
        return body({"shapes": library.search(str(request.query_params.get("q") or ""), limit=200)})

    async def save_shape(request: Request):
        data = await request.json()
        try:
            bp = store.get(str(data.get("blueprint") or ""))
            part = next(p for p in bp["parts"] if p["id"] == data.get("part"))
            s = library.add(part, str(data.get("name") or part["name"]), str(data.get("tags") or ""), bp.get("source"),
                            learned_from=bp["name"])
        except (KeyError, StopIteration):
            return error("That part wasn't found.", 404)
        except ValueError as e:
            return error(str(e))
        return body(s, 201)

    async def use_shape(request: Request):
        try:
            return body(library.to_part(request.path_params["sid"], {}))
        except KeyError as e:
            return error(str(e.args[0]), 404)

    async def delete_shape(request: Request):
        try:
            library.delete(request.path_params["sid"])
        except KeyError:
            return error("Shape not found.", 404)
        return body({"ok": True})

    return [
        Route("/api/blueprints/live", live),
        Route("/api/blueprints/import", upload_model, methods=["POST"]),
        Route("/api/blueprints/find", find, methods=["POST"]),
        Route("/api/blueprints/import-url", import_url, methods=["POST"]),
        Route("/api/blueprints/assets/{aid}", asset),
        Route("/api/blueprints/{bid}/undo", undo, methods=["POST"]),
        Route("/api/blueprints/{bid}/export", export),
        Route("/api/shapes", list_shapes),
        Route("/api/shapes", save_shape, methods=["POST"]),
        Route("/api/shapes/{sid}/use", use_shape, methods=["POST"]),
        Route("/api/shapes/{sid}", delete_shape, methods=["DELETE"]),
    ]
