"""Corvis web app: the chat page, served at http://127.0.0.1:8765.

Security:
- Every API call must carry an `X-Corvis: 1` header. Other websites can't add it
  without the browser asking this server first (which it refuses), so they can't
  send Corvis commands through your browser.
- Host header check blocks DNS-rebinding tricks.
- PC only (default): no password; only this computer can connect.
- Remote access (remote.enabled in config.yaml, for your phone): every device must
  sign in with the owner password, except this PC's own browser, which the launcher
  signs in automatically with a one-time token.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import socket
import threading
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

import requests
import uvicorn
from starlette.applications import Starlette
from starlette.middleware import Middleware
from starlette.datastructures import MutableHeaders
from starlette.requests import Request
from starlette.responses import (FileResponse, JSONResponse, PlainTextResponse, RedirectResponse, Response,
                                 StreamingResponse)
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from .. import __version__
from ..config import CORVIS_HOME, agent_name, data_dir as default_data_dir, memory_cfg
from ..internet import internet_cfg
from ..attachments import MAX_FILES_PER_MESSAGE, MAX_UPLOAD_BYTES, AttachmentStore
from ..memory import Memory
from .. import computer as computer_mod
from ..bots import ABILITIES, LEAD_ID
from ..routines import RoutineStore, Scheduler
from .. import pc as pcmod
from ..vision import vision_cfg
from .. import voice as voicemod
from ..conversations.store import ConversationStore
from .auth import SESSION_DAYS, Auth
from ..nodes import NodeHub
from ..studio import CreativeStudio
from ..graphify_integration import GraphifyIntegration
from ..workspace_features import WorkspaceStore
from ..model_compare import inventory as model_inventory, compare as compare_models
from .. import blueprint_sim
from .. import connectors as connectors_mod
from ..blueprints import MATERIALS as BP_MATERIALS, SHAPES as BP_SHAPES, TEMPLATES as BP_TEMPLATES, BlueprintStore
from ..plugin_store import NeedsCodeApproval, PluginError, PluginStore
from .runs import RunManager

STATIC = Path(__file__).parent / "static"
RESTART_EXIT_CODE = 3
LOCAL_HOSTS = {"127.0.0.1", "localhost", "[::1]"}
COOKIE = "corvis_session"
PUBLIC_PATHS = {"/login", "/api/login", "/sw.js", "/manifest.webmanifest", "/offline.html"}


# --- helpers ------------------------------------------------------------------
def web_cfg(cfg: dict) -> dict:
    w = cfg.get("web", {}) or {}
    return {
        "host": w.get("host", "127.0.0.1"),
        "port": int(w.get("port", 8765)),
        "open_browser": w.get("open_browser", True),
        "default_workspace": str(Path(w.get("default_workspace", "~/CorvisProjects")).expanduser()),
    }


def remote_cfg(cfg: dict) -> dict:
    r = cfg.get("remote", {}) or {}
    hosts = [str(h).strip().lower().rstrip(".") for h in (r.get("allowed_hosts") or []) if str(h).strip()]
    return {"enabled": bool(r.get("enabled", False)), "allowed_hosts": hosts}


def resolve_folder(path: str) -> Path:
    return Path(path.strip().strip('"')).expanduser().resolve()


_model_cache: dict = {}


def model_status(cfg: dict) -> dict:
    llm = cfg.get("llm", {})
    base = llm.get("base_url", "http://localhost:11434/v1").rstrip("/")
    model = llm.get("model", "qwen3-coder:30b")
    cloud = not any(h in base for h in ("localhost", "127.0.0.1", "0.0.0.0"))
    hit = _model_cache.get((base, model))
    if cloud and hit and time.time() - hit[0] < 300:  # a cloud model list is big: check every 5 minutes
        return hit[1]
    try:
        r = requests.get(f"{base}/models", timeout=5 if cloud else 2)
        online = r.status_code == 200
        installed = None
        if online:
            ids = [m.get("id", "") for m in r.json().get("data", [])]
            installed = (model in ids) if ids else None
    except (requests.RequestException, ValueError):
        online, installed = False, None
    out = {"model": model, "server": base, "online": online, "installed": installed, "cloud": cloud}
    if online:
        _model_cache[(base, model)] = (time.time(), out)
    return out


def body(data: dict, status: int = 200) -> JSONResponse:
    return JSONResponse(data, status_code=status, headers={"Cache-Control": "no-store"})


def error(message: str, status: int = 400) -> JSONResponse:
    return body({"error": message}, status)


def is_https(request: Request) -> bool:
    return request.url.scheme == "https" or request.headers.get("x-forwarded-proto", "") == "https"


def set_session_cookie(response, request: Request, token: str) -> None:
    response.set_cookie(COOKIE, token, max_age=SESSION_DAYS * 86400, httponly=True,
                        samesite="lax", secure=is_https(request), path="/")


class Guard:
    """Host check, the X-Corvis header rule, and (with remote access on) sign-in.

    A plain ASGI middleware on purpose: Starlette's BaseHTTPMiddleware sits between every
    response and the network, which can hold back long streamed replies (the live chat)."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        request = Request(scope, receive)
        blocked = self.check(request)
        if blocked is not None:
            return await blocked(scope, receive, send)

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                headers.setdefault("X-Frame-Options", "DENY")
                headers.setdefault("Referrer-Policy", "no-referrer")
            await send(message)
        await self.app(scope, receive, send_with_headers)

    @staticmethod
    def check(request: Request):
        """Returns a response to send instead, or None to let the request through."""
        state = request.app.state
        path = request.url.path
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].lower().rstrip(".")
        if state.remote:
            allowed = LOCAL_HOSTS | set(state.allowed_hosts)
            if state.allowed_hosts and host not in allowed:
                return PlainTextResponse("Unknown address. Add it to remote.allowed_hosts in config.yaml.",
                                         status_code=403)
        elif host not in LOCAL_HOSTS | set(state.extra_hosts):
            return PlainTextResponse("Corvis only answers on this computer. To use him from your "
                                     "phone, turn on remote access (see the README).", status_code=403)
        if path.startswith("/api/") and request.headers.get("x-corvis") != "1":
            return PlainTextResponse("Missing X-Corvis header.", status_code=403)

        if path.startswith("/api/node/"):  # PC nodes sign in with their own pairing token
            auth_header = request.headers.get("authorization", "")
            token = auth_header[7:] if auth_header.lower().startswith("bearer ") else None
            node_id = state.node_hub.authenticate(token)
            if not node_id:
                return JSONResponse({"error": "This PC isn't linked (or was unlinked). Link it again."},
                                    status_code=401)
            request.state.node_id = node_id
            return None

        if state.remote and not (path in PUBLIC_PATHS or path.startswith("/static/")):
            auth: Auth = state.auth
            launch = request.query_params.get("launch")
            if path == "/" and launch:
                if auth.use_launch_token(launch):
                    resp = RedirectResponse("/", status_code=303)
                    set_session_cookie(resp, request, auth.new_session("This PC"))
                    return resp
                return RedirectResponse("/login", status_code=303)
            if not auth.valid(request.cookies.get(COOKIE)):
                if path.startswith("/api/"):
                    return JSONResponse({"error": "Sign in first.", "login": True}, status_code=401)
                return RedirectResponse("/login", status_code=303)
        return None


# --- app ----------------------------------------------------------------------
def create_app(cfg: dict, data_dir: Path | None = None, manager: RunManager | None = None) -> Starlette:
    wcfg = web_cfg(cfg)
    data_dir = Path(data_dir or default_data_dir(cfg))
    cfg = {**cfg, "data_dir": str(data_dir)}  # agents and the server share one data folder
    store = manager.store if manager else ConversationStore(data_dir / "conversations")
    node_hub = (manager.node_hub if manager and getattr(manager, "node_hub", None) else NodeHub(data_dir))
    manager = manager or RunManager(store, cfg, node_hub=node_hub)
    manager.node_hub = node_hub
    memory = Memory(data_dir)
    files = AttachmentStore(data_dir)
    auth = Auth(data_dir)
    rcfg = remote_cfg(cfg)
    pcpol = pcmod.PCPolicy(cfg, CORVIS_HOME, data_dir)
    bots = manager.bots
    routines = RoutineStore(data_dir)
    owner_file = data_dir / "owner.json"
    plugin_store = PluginStore(data_dir)
    blueprints = BlueprintStore(data_dir)
    conns = connectors_mod.shared(data_dir, extra=plugin_store.connectors)
    ccfg = cfg.get("computer") or {}
    computer = (computer_mod.shared(data_dir, allow_private=bool(ccfg.get("allow_private")))
                if ccfg.get("enabled", True) is not False and computer_mod.available() else None)

    def owner_tz() -> str:
        try:
            return json.loads(owner_file.read_text(encoding="utf-8")).get("tz") or "UTC"
        except (OSError, ValueError):
            return str(cfg.get("timezone") or "UTC")

    manager.extra_state.update(routines=routines, owner_tz=owner_tz)
    from ..brain import shared as brain_shared
    brain = brain_shared(cfg, data_dir, conversations=store)
    if brain is not None:
        manager.extra_state["brain"] = brain
        brain.busy = manager.any_active   # background learning and summaries wait while you chat
    studio = CreativeStudio(data_dir, wcfg["default_workspace"], cfg)
    workspace_store = WorkspaceStore(data_dir)
    if computer is not None:
        manager.extra_state["computer"] = computer

    def fire_routine(r: dict) -> str:
        """Start a routine's run in its own chat (made on first run, reused after), or in a
        fresh chat every time when the task asks for that."""
        conv = None if r.get("fresh") else conv_or_404(r.get("conversation_id") or "")
        if conv is None:
            ws = resolve_folder(wcfg["default_workspace"])
            ws.mkdir(parents=True, exist_ok=True)
            conv = store.create(str(ws), "project", bot=r["bot"])
            conv["routine"] = r["id"]
            if r.get("fresh"):
                conv["title"] = f"{r['name']} · {time.strftime('%d %b %H:%M')}"
            store.save(conv)
            routines.update(r["id"], {"conversation_id": conv["id"]})
        if manager.active(conv["id"]):
            status = "skipped: the last run was still going"
        else:
            manager.start(conv["id"], r["prompt"], bot_id=r["bot"], routine=r)
            status = "started"
        routines.update(r["id"], {"run": {"ts": time.time(), "status": status, "conversation_id": conv["id"]}})
        return status

    scheduler = Scheduler(routines, fire_routine)

    def conv_or_404(conv_id: str) -> dict | None:
        try:
            return store.get(conv_id)
        except KeyError:
            return None

    def public(conv: dict) -> dict:
        run = manager.active(conv["id"])
        out = {k: v for k, v in conv.items() if k not in ("llm_history", "bot_history", "seen")}
        out["running"] = bool(run)
        return out

    def pop_notice() -> str:
        """A one-time message for the owner (e.g. 'I undid my last update')."""
        f = data_dir / "notice.json"
        try:
            text = json.loads(f.read_text(encoding="utf-8")).get("text", "")
            f.unlink()
            return text
        except (OSError, ValueError):
            return ""

    # info --------------------------------------------------------------------
    async def info(request: Request):
        status = await asyncio.to_thread(model_status, cfg)
        recent: list[str] = []
        for c in store.list():
            if c["mode"] == "project" and c["workspace"] not in recent:
                recent.append(c["workspace"])
        return body({
            "name": agent_name(cfg), "version": __version__, "model": status,
            "default_workspace": wcfg["default_workspace"], "corvis_home": str(CORVIS_HOME),
            "recent_workspaces": recent[:6], "busy": manager.any_active(),
            "memory": memory_cfg(cfg)["enabled"],
            "vision": bool(vision_cfg(cfg)),
            "remote": rcfg["enabled"],
            "pc_access": pcpol.enabled or bool(node_hub.online()),
            "nodes": node_hub.paired(),
            "bots": bots.list(),
            "abilities": ABILITIES,
            "computer": computer is not None,
            "connectors": (cfg.get("connectors") or {}).get("enabled", True) is not False,
            "plugins": (cfg.get("plugins") or {}).get("enabled", True) is not False,
            "owner_tz": owner_tz(),
            "notice": pop_notice(),
            "voice": {"speech_to_text": voicemod.engine(cfg)},
            "max_upload_mb": MAX_UPLOAD_BYTES // (1024 * 1024),
            "internet": {k: v for k, v in internet_cfg(cfg).items() if k in ("enabled", "provider")},
        })

    # memory ------------------------------------------------------------------
    async def list_memory(request: Request):
        names = {b["id"]: b["name"] for b in bots.list()}
        facts = memory.facts.list()
        for f in facts:
            if f.get("bot"):
                f["bot_name"] = names.get(f["bot"], "a deleted bot")
        return body({"facts": facts})

    async def add_memory(request: Request):
        data = await request.json()
        try:
            fact, created = memory.facts.add(str(data.get("text", "")))
        except ValueError as e:
            return error(str(e))
        return body({"fact": fact, "created": created}, 201 if created else 200)

    async def delete_memory(request: Request):
        removed = memory.facts.remove(request.path_params["mid"])
        return body({"ok": True}) if removed else error("That memory no longer exists.", 404)

    # folders -----------------------------------------------------------------
    async def check_folder(request: Request):
        data = await request.json()
        raw = str(data.get("path", "")).strip()
        if not raw:
            return error("Type or paste a folder path.")
        p = resolve_folder(raw)
        if data.get("create") and not p.exists():
            try:
                p.mkdir(parents=True)
            except OSError as e:
                return error(f"Couldn't create that folder: {e}")
        return body({
            "path": str(p), "exists": p.is_dir(), "is_file": p.is_file(),
            "is_corvis": p == CORVIS_HOME,
        })

    # conversations -----------------------------------------------------------
    async def list_conversations(request: Request):
        convs = store.list()
        for c in convs:
            c["running"] = bool(manager.active(c["id"]))
        return body({"conversations": convs})

    def pick_workspace(raw: str | None) -> str:
        """A project folder Corvis may work in (made if it's the default one). Raises ValueError."""
        p = resolve_folder(raw or wcfg["default_workspace"])
        if p == CORVIS_HOME:
            raise ValueError("That's Corvis's own folder. Choose 'Improve Corvis' instead, "
                             "so changes go through a safe branch with tests.")
        if not p.exists() and p == resolve_folder(wcfg["default_workspace"]):
            p.mkdir(parents=True, exist_ok=True)
        if not p.is_dir():
            raise ValueError(f"Folder not found: {p}")
        return str(p)

    async def create_conversation(request: Request):
        data = await request.json() if await request.body() else {}
        mode = data.get("mode", "project")
        if mode not in {"project", "self"}:
            return error("Mode must be 'project' or 'self'.")
        if mode == "self":
            workspace = str(CORVIS_HOME)
        else:
            p = resolve_folder(data.get("workspace") or wcfg["default_workspace"])
            if p == CORVIS_HOME:
                return error("That's Corvis's own folder. Choose 'Improve Corvis' instead, "
                             "so changes go through a safe branch with tests.")
            if not p.exists() and p == resolve_folder(wcfg["default_workspace"]):
                p.mkdir(parents=True, exist_ok=True)
            if not p.is_dir():
                return error(f"Folder not found: {p}")
            workspace = str(p)
        bot_id = str(data.get("bot") or LEAD_ID)
        try:
            bots.get(bot_id)
        except KeyError:
            return error("That bot doesn't exist any more.", 404)
        return body(public(store.create(workspace, mode, bot=bot_id)), 201)

    async def get_conversation(request: Request):
        conv = conv_or_404(request.path_params["cid"])
        if conv and conv.get("unread"):
            conv["unread"] = False
            store.save(conv)
        return body(public(conv)) if conv else error("Chat not found.", 404)

    async def update_conversation(request: Request):
        conv = conv_or_404(request.path_params["cid"])
        if not conv:
            return error("Chat not found.", 404)
        data = await request.json()
        if "title" in data:
            title = " ".join(str(data["title"]).split())[:80]
            if title:
                conv["title"] = title
        if "workspace" in data:
            if conv["messages"]:
                return error("This chat already started. Start a new chat to use another folder.")
            p = resolve_folder(str(data["workspace"]))
            if p == CORVIS_HOME:
                return error("That's Corvis's own folder. Choose 'Improve Corvis' instead.")
            if not p.is_dir():
                return error(f"Folder not found: {p}")
            conv["workspace"], conv["mode"] = str(p), "project"
            manager.forget(conv["id"])
        store.save(conv)
        return body(public(conv))

    async def delete_conversation(request: Request):
        cid = request.path_params["cid"]
        if manager.active(cid):
            return error("Corvis is working in this chat. Stop him first.", 409)
        store.delete(cid)
        manager.forget(cid)
        return body({"ok": True})

    # messages & live events --------------------------------------------------
    async def send_message(request: Request):
        cid = request.path_params["cid"]
        if not conv_or_404(cid):
            return error("Chat not found.", 404)
        data = await request.json()
        text = str(data.get("text", "")).strip()
        ids = data.get("attachments") or []
        if not isinstance(ids, list) or len(ids) > MAX_FILES_PER_MESSAGE:
            return error(f"Attach at most {MAX_FILES_PER_MESSAGE} files per message.")
        attached = []
        for aid in ids:
            try:
                meta = files.get(str(aid))
            except KeyError:
                return error("One of the attachments is missing. Try attaching it again.")
            attached.append({k: meta[k] for k in ("id", "name", "size", "kind", "mime")})
        if not text and not attached:
            return error("Message is empty.")
        try:
            run = manager.start(cid, text, attached, bot_id=data.get("bot") or None)
        except RuntimeError as e:
            return error(str(e), 409)
        return body({"run": run.id}, 202)

    async def events(request: Request):
        cid = request.path_params["cid"]
        after = int(request.query_params.get("after", 0))

        async def stream():
            idx, last_beat = after, time.monotonic()
            while True:
                run = manager.runs.get(cid)
                if run is None:
                    yield f"data: {json.dumps({'kind': 'end', 'text': 'idle'})}\n\n"
                    return
                evs = run.events
                while idx < len(evs):
                    yield f"data: {json.dumps(evs[idx])}\n\n"
                    idx += 1
                if run.done and idx >= len(run.events):
                    return
                if time.monotonic() - last_beat > 10:
                    last_beat = time.monotonic()
                    yield ": ping\n\n"   # keeps proxies from timing out; tells the page the line is alive
                await asyncio.sleep(0.12)

        return StreamingResponse(stream(), media_type="text/event-stream",
                                 headers={"Cache-Control": "no-store, no-transform", "X-Accel-Buffering": "no",
                                          "Content-Encoding": "identity"})

    async def run_status(request: Request):
        """Tiny check the page uses as a backstop in case live events get held up on the way."""
        cid = request.path_params["cid"]
        run = manager.runs.get(cid)
        return body({"running": bool(manager.active(cid)), "events": len(run.events) if run else 0})

    async def stop(request: Request):
        run = manager.stop(request.path_params["cid"])
        return body({"ok": True, "was_running": bool(run)})

    async def approve(request: Request):
        aid = request.path_params["aid"]
        data = await request.json()
        run = manager.find_approval(aid)
        if not run or not run.answer(aid, bool(data.get("allow"))):
            return error("That request already expired.", 404)
        return body({"ok": True})

    # attachments ---------------------------------------------------------------
    async def upload(request: Request):
        name = request.query_params.get("name", "file")
        received = bytearray()
        async for chunk in request.stream():
            received.extend(chunk)
            if len(received) > MAX_UPLOAD_BYTES:
                return error(f"That file is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.", 413)
        try:
            meta = files.save(name, bytes(received), request.headers.get("content-type", ""))
        except ValueError as e:
            return error(str(e))
        return body(meta, 201)

    async def serve_file(request: Request):
        try:
            meta = files.get(request.path_params["aid"])
        except KeyError:
            return PlainTextResponse("Not found.", status_code=404)
        # Only real photos display in the page. Everything else downloads, so an attached
        # HTML or SVG file can never run inside Corvis's page.
        inline = meta["kind"] == "image"
        disposition = "inline" if inline else "attachment"
        return FileResponse(files.path(meta), media_type=meta["mime"] if inline else "application/octet-stream",
                            filename=meta["name"], content_disposition_type=disposition,
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Content-Security-Policy": "default-src 'none'; sandbox",
                                     "Cache-Control": "private, max-age=86400"})

    # files on the PC (the Files browser) -------------------------------------
    IMAGE_EXT = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
                 ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp"}

    async def pc_list(request: Request):
        path = request.query_params.get("path", "")
        if not pcpol.enabled:  # the hub: browse the owner's PC through the node
            try:
                out = await asyncio.to_thread(node_rpc, "list", {"path": path})
            except (ConnectionError, TimeoutError) as e:
                return error(str(e), 503)
            return body(out) if "error" not in out else error(out["error"], 403)
        try:
            listing = await asyncio.to_thread(pcmod.list_dir, pcpol, path)
        except (PermissionError, NotADirectoryError, FileNotFoundError) as e:
            return error(str(e), 403 if isinstance(e, PermissionError) else 404)
        listing["is_corvis"] = bool(listing["path"]) and Path(listing["path"]) == CORVIS_HOME
        return body(listing)

    async def pc_preview(request: Request):
        if not pcpol.enabled:
            try:
                out = await asyncio.to_thread(node_rpc, "preview", {"path": request.query_params.get("path", "")})
            except (ConnectionError, TimeoutError) as e:
                return error(str(e), 503)
            return body(out) if "error" not in out else error(out["error"], 403)
        try:
            p = pcpol.check(request.query_params.get("path", ""), "read")
        except PermissionError as e:
            return error(str(e), 403)
        if not p.is_file():
            return error("That file doesn't exist.", 404)
        size = p.stat().st_size
        info = {"name": p.name, "path": str(p), "size": size, "modified": p.stat().st_mtime}
        if p.suffix.lower() in IMAGE_EXT:
            return body({**info, "kind": "image"})
        try:
            text = await asyncio.to_thread(pcmod.read_text, p, 0, 200_000)
        except (ValueError, OSError) as e:
            return body({**info, "kind": "other", "note": str(e)})
        if " has no text to read." in text.splitlines()[0]:
            return body({**info, "kind": "other", "note": text})
        first_break = text.find("\n\n")
        return body({**info, "kind": "text", "text": text[first_break + 2:] if first_break >= 0 else text})

    async def pc_file(request: Request):
        if not pcpol.enabled:
            import base64
            try:
                out = await asyncio.to_thread(node_rpc, "file", {"path": request.query_params.get("path", "")})
            except (ConnectionError, TimeoutError) as e:
                return PlainTextResponse(str(e), status_code=503)
            if "error" in out:
                return PlainTextResponse(out["error"], status_code=403)
            mime = IMAGE_EXT.get(Path(out["name"]).suffix.lower())
            inline = bool(mime) and request.query_params.get("download") != "1"
            from starlette.responses import Response
            from urllib.parse import quote
            disp = "inline" if inline else "attachment"
            return Response(base64.b64decode(out["b64"]), media_type=mime if inline else "application/octet-stream",
                            headers={"Content-Disposition": f"{disp}; filename*=UTF-8''{quote(out['name'])}",
                                     "X-Content-Type-Options": "nosniff",
                                     "Content-Security-Policy": "default-src 'none'; sandbox",
                                     "Cache-Control": "private, no-store"})
        try:
            p = pcpol.check(request.query_params.get("path", ""), "read")
        except PermissionError as e:
            return PlainTextResponse(str(e), status_code=403)
        if not p.is_file():
            return PlainTextResponse("Not found.", status_code=404)
        mime = IMAGE_EXT.get(p.suffix.lower())
        inline = bool(mime) and request.query_params.get("download") != "1"
        return FileResponse(p, media_type=mime if inline else "application/octet-stream", filename=p.name,
                            content_disposition_type="inline" if inline else "attachment",
                            headers={"X-Content-Type-Options": "nosniff",
                                     "Content-Security-Policy": "default-src 'none'; sandbox",
                                     "Cache-Control": "private, no-store"})

    # bots ---------------------------------------------------------------------
    async def list_bots(request: Request):
        return body({"bots": bots.list(), "abilities": ABILITIES})

    async def create_bot(request: Request):
        try:
            return body(bots.create(await request.json()), 201)
        except ValueError as e:
            return error(str(e))

    async def update_bot(request: Request):
        try:
            return body(bots.update(request.path_params["bid"], await request.json()))
        except KeyError:
            return error("That bot doesn't exist.", 404)
        except ValueError as e:
            return error(str(e))

    async def delete_bot(request: Request):
        bid = request.path_params["bid"]
        try:
            ok = bots.delete(bid)
        except ValueError as e:
            return error(str(e))
        for r in routines.list():  # its routines go with it
            if r["bot"] == bid:
                routines.delete(r["id"])
        return body({"ok": ok})

    # routines -------------------------------------------------------------------
    async def list_routines(request: Request):
        return body({"routines": routines.list(), "tz": owner_tz()})

    async def create_routine(request: Request):
        data = await request.json()
        try:
            bots.get(str(data.get("bot") or LEAD_ID))
            r = routines.create(data.get("name", ""), str(data.get("bot") or LEAD_ID), data.get("prompt", ""),
                                data.get("schedule") or {}, data.get("tz") or owner_tz())
        except KeyError:
            return error("That bot doesn't exist.", 404)
        except ValueError as e:
            return error(str(e))
        return body(r, 201)

    async def update_routine(request: Request):
        try:
            return body(routines.update(request.path_params["rid"], await request.json()))
        except KeyError:
            return error("That routine doesn't exist.", 404)
        except ValueError as e:
            return error(str(e))

    async def delete_routine(request: Request):
        return body({"ok": routines.delete(request.path_params["rid"])})

    async def run_routine_now(request: Request):
        try:
            r = routines.get(request.path_params["rid"])
        except KeyError:
            return error("That routine doesn't exist.", 404)
        status = await asyncio.to_thread(fire_routine, r)
        routines.update(r["id"], {"last_run": time.time(), "last_status": status})
        return body({"status": status, "conversation_id": routines.get(r["id"]).get("conversation_id")})

    async def set_owner(request: Request):
        data = await request.json()
        tz = str(data.get("tz") or "")
        from ..routines import zone
        if tz and str(zone(tz)) == tz and tz != owner_tz():
            owner_file.write_text(json.dumps({"tz": tz}), encoding="utf-8")
        return body({"tz": owner_tz()})

    # the bots' computer (live view) ---------------------------------------------------
    async def computer_status(request: Request):
        if computer is None:
            return error("The computer is turned off in config.yaml.", 404)
        return body(await asyncio.to_thread(computer.status))

    async def computer_screen(request: Request):
        if computer is None:
            return error("The computer is turned off.", 404)
        try:
            img = await asyncio.to_thread(computer.screen, request.query_params.get("tab") or None)
        except Exception as e:
            return error(f"The computer couldn't show its screen: {e}", 503)
        return Response(img, media_type="image/jpeg", headers={"Cache-Control": "no-store"})

    async def computer_act(request: Request):
        if computer is None:
            return error("The computer is turned off.", 404)
        data = await request.json()
        action = str(data.pop("action", ""))
        tab = data.pop("tab", None)
        try:
            await asyncio.to_thread(lambda: computer.owner(action, tab, **data))
        except (PermissionError, ValueError, KeyError) as e:
            return error(str(e))
        except Exception as e:
            return error(f"That didn't work: {str(e).splitlines()[0][:200]}", 502)
        return body({"ok": True})

    # PC nodes ------------------------------------------------------------------
    async def node_hello(request: Request):
        data = await request.json()
        node_hub.hello(request.state.node_id, str(data.get("name", "PC")), list(data.get("tools") or []),
                       dict(data.get("info") or {}))
        return body({"ok": True, "node_id": request.state.node_id, "hub": agent_name(cfg)})

    async def node_poll(request: Request):
        if request.state.node_id not in node_hub.nodes:  # e.g. the hub restarted
            return body({"job": None, "hello": True})
        job = await asyncio.to_thread(node_hub.poll, request.state.node_id, 25.0)
        if job is None:
            return body({"job": None})
        return body({"job": {"id": job.id, "kind": job.kind, "name": job.name, "args": job.args}})

    async def node_result(request: Request):
        data = await request.json()
        ok = node_hub.result(request.state.node_id, str(data.get("job_id")), data.get("output"))
        return body({"ok": ok})

    async def node_ask(request: Request):
        data = await request.json()
        allowed = await asyncio.to_thread(node_hub.ask, request.state.node_id, str(data.get("job_id")),
                                          str(data.get("prompt", ""))[:4000])
        return body({"allow": allowed})

    async def list_nodes(request: Request):
        return body({"nodes": node_hub.paired()})

    async def pair_node(request: Request):
        data = await request.json() if await request.body() else {}
        node_id, token = node_hub.pair(str(data.get("name") or "My PC"))
        return body({"node_id": node_id, "token": token}, 201)

    async def unpair_node(request: Request):
        return body({"ok": node_hub.unpair(request.path_params["nid"])})

    def node_rpc(name: str, args: dict):
        live = node_hub.online()
        if not live:
            raise ConnectionError("Your PC is offline. Turn it on and start Corvis Node.")
        return node_hub.call(live[0].id, "rpc", name, args, timeout=120)

    # voice -------------------------------------------------------------------
    async def transcribe(request: Request):
        audio = bytearray()
        async for chunk in request.stream():
            audio.extend(chunk)
            if len(audio) > MAX_UPLOAD_BYTES:
                return error("That recording is too long.", 413)
        if len(audio) < 200:
            return error("The recording was empty. Hold the mic a little longer.")
        ctype = request.headers.get("content-type", "")
        suffix = ".mp4" if "mp4" in ctype or "aac" in ctype else ".ogg" if "ogg" in ctype else ".webm"
        try:
            text = await asyncio.to_thread(voicemod.transcribe, bytes(audio), cfg, suffix)
        except Exception as e:  # missing package, model download failed, unreadable audio
            return error(f"Couldn't understand the recording: {e}", 500)
        return body({"text": text})

    # restart -----------------------------------------------------------------
    async def restart(request: Request):
        if manager.any_active():
            return error("Corvis is still working. Stop him first, then restart.", 409)
        app.state.exit_code = RESTART_EXIT_CODE
        server = app.state.server
        if server is None:
            return error("Restart only works when Corvis was started with the launcher.", 409)
        asyncio.get_running_loop().call_later(0.3, lambda: setattr(server, "should_exit", True))
        return body({"ok": True})

    # sign in -------------------------------------------------------------------
    async def login_page(request: Request):
        return FileResponse(STATIC / "login.html", headers={"Cache-Control": "no-store"})

    async def login(request: Request):
        if not auth.has_password():
            return error("No owner password is set yet. On the PC, run Set_Corvis_Password.bat.", 409)
        wait = auth.locked_for()
        if wait:
            return error(f"Too many wrong tries. Wait {wait} seconds.", 429)
        data = await request.json()
        device = request.headers.get("user-agent", "")
        token = await asyncio.to_thread(auth.login, str(data.get("password", "")), device)
        if not token:
            wait = auth.locked_for()
            return error(f"Too many wrong tries. Wait {wait} seconds." if wait else "Wrong password.",
                         429 if wait else 401)
        resp = body({"ok": True})
        set_session_cookie(resp, request, token)
        return resp

    async def logout(request: Request):
        auth.logout(request.cookies.get(COOKIE))
        resp = body({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    async def logout_everywhere(request: Request):
        auth.logout_everywhere()
        resp = body({"ok": True})
        resp.delete_cookie(COOKIE, path="/")
        return resp

    # page --------------------------------------------------------------------
    async def index(request: Request):
        return FileResponse(STATIC / "index.html", headers={"Cache-Control": "no-store"})

    async def service_worker(request: Request):
        return FileResponse(STATIC / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache", "Service-Worker-Allowed": "/"})

    async def manifest(request: Request):
        return FileResponse(STATIC / "manifest.webmanifest", media_type="application/manifest+json",
                            headers={"Cache-Control": "no-cache"})

    async def offline(request: Request):
        return FileResponse(STATIC / "offline.html", headers={"Cache-Control": "no-cache"})

    # Creative Studio / Mission Control ---------------------------------------
    async def studio_page(request: Request):
        return FileResponse(STATIC / "studio.html", headers={"Cache-Control": "no-store"})

    async def studio_status(request: Request):
        snap = studio.snapshot()
        try:
            snap["nodes"] = node_hub.paired()
            snap["online_nodes"] = node_hub.online()
        except Exception:
            snap["nodes"] = []
            snap["online_nodes"] = []
        # Current chat runs are real execution activity; do not fabricate worker progress.
        snap["active_runs"] = [{"conversation_id": cid, "run_id": run.id,
                                 "bot": run.bot.get("name", "Corvis"),
                                 "status": "running" if not run.done else "completed",
                                 "events": len(run.events)}
                                for cid, run in manager.runs.items() if not run.done]
        return body(snap)

    async def studio_create(request: Request):
        try:
            payload = await request.json()
            job = studio.create_job(payload if isinstance(payload, dict) else {})
            return body({"job": job}, 201)
        except ValueError as exc:
            return error(str(exc), 400)
        except Exception:
            return error("Could not create the project. Check the brief and workspace configuration.", 400)

    async def studio_job(request: Request):
        job = studio.get(request.path_params["jid"])
        return body({"job": job}) if job else error("Project not found.", 404)

    async def studio_cancel(request: Request):
        job = studio.cancel(request.path_params["jid"])
        return body({"job": job}) if job else error("Project not found.", 404)

    async def studio_approve(request: Request):
        # Approval currently moves a planned project into a visible waiting state only.
        # Actual execution is enabled per adapter in a future/installed integration.
        jid = request.path_params["jid"]
        job = studio.get(jid)
        if not job: return error("Project not found.", 404)
        if job["status"] not in {"planned", "waiting_approval"}:
            return error("Only a planned project can be approved.", 409)
        return body({"job": studio.update_status(jid, "waiting_approval",
                    "Approval recorded. Execution remains blocked until a compatible model/application adapter is configured.")})

    # Productivity workspace: local notes, tasks, calendar, documents and email drafts.
    async def workspace_page(request: Request):
        return FileResponse(STATIC / "workspace.html", headers={"Cache-Control": "no-store"})

    async def workspace_summary(request: Request):
        return body({"summary": workspace_store.summary(), "collections": {k: workspace_store.list(k) for k in sorted(workspace_store.COLLECTIONS)}, "models": model_inventory(cfg)})

    async def workspace_list(request: Request):
        collection = request.path_params["collection"]
        try: return body({"items": workspace_store.list(collection)})
        except ValueError as exc: return error(str(exc), 404)

    async def workspace_create(request: Request):
        collection = request.path_params["collection"]
        try:
            payload = await request.json()
            return body({"item": workspace_store.create(collection, payload)}, 201)
        except ValueError as exc: return error(str(exc), 400)

    async def workspace_update(request: Request):
        try:
            payload = await request.json()
            item = workspace_store.update(request.path_params["collection"], request.path_params["item_id"], payload)
            return body({"item": item}) if item else error("Item not found.", 404)
        except ValueError as exc: return error(str(exc), 400)

    async def workspace_delete(request: Request):
        try:
            ok = workspace_store.delete(request.path_params["collection"], request.path_params["item_id"])
            return body({"ok": True}) if ok else error("Item not found.", 404)
        except ValueError as exc: return error(str(exc), 400)

    async def model_catalog(request: Request):
        return body(model_inventory(cfg))

    async def model_compare(request: Request):
        try:
            payload = await request.json()
            result = await asyncio.to_thread(compare_models, cfg, payload.get("prompt", ""), payload.get("models", []))
            return body(result)
        except ValueError as exc: return error(str(exc), 400)

    # Graphify integration: explicit local indexing/query actions, confined to workspace.
    graphify = GraphifyIntegration(wcfg["default_workspace"])

    async def graphify_status(request: Request):
        try:
            return body(graphify.status(request.query_params.get("project", ".")))
        except ValueError as exc:
            return error(str(exc), 400)

    async def graphify_build(request: Request):
        try:
            payload = await request.json()
            project = payload.get("project", ".") if isinstance(payload, dict) else "."
            result = await asyncio.to_thread(graphify.build, project)
            return body(result)
        except ValueError as exc:
            return error(str(exc), 400)
        except RuntimeError as exc:
            return error(str(exc), 503)

    async def graphify_query(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict): payload = {}
            result = await asyncio.to_thread(graphify.query, payload.get("question", ""), payload.get("project", "."))
            return body(result)
        except ValueError as exc:
            return error(str(exc), 400)
        except RuntimeError as exc:
            return error(str(exc), 503)

    async def graphify_explain(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict): payload = {}
            result = await asyncio.to_thread(graphify.explain, payload.get("concept", ""), payload.get("project", "."))
            return body(result)
        except ValueError as exc:
            return error(str(exc), 400)
        except RuntimeError as exc:
            return error(str(exc), 503)

    async def graphify_path(request: Request):
        try:
            payload = await request.json()
            if not isinstance(payload, dict): payload = {}
            result = await asyncio.to_thread(graphify.path, payload.get("source", ""), payload.get("target", ""), payload.get("project", "."))
            return body(result)
        except ValueError as exc:
            return error(str(exc), 400)
        except RuntimeError as exc:
            return error(str(exc), 503)

    # connectors ----------------------------------------------------------------
    def connector_view(c: dict) -> dict:
        view = {**connectors_mod.public(c), "status": conns.status(c["id"])}
        if view["status"].get("state") == "connected":
            view["tools"] = [{"name": t.get("name"), "description": (t.get("description") or "")[:200],
                              "read_only": (t.get("annotations") or {}).get("readOnlyHint") is True}
                             for t in conns._tools.get(c["id"], [])]
        return view

    def connectors_body() -> dict:
        return {"connectors": [connector_view(c) for c in conns.all()], "catalog": connectors_mod.CATALOG,
                "approval_modes": connectors_mod.APPROVAL_MODES}

    async def list_connectors(request: Request):
        return body(connectors_body())

    async def add_connector(request: Request):
        data = await request.json()
        tpl = next((t for t in connectors_mod.CATALOG if t["id"] == data.get("template")), None)
        if tpl:
            folder = str(data.get("folder") or "").strip()
            if "folder" in tpl.get("asks", []) and not folder:
                return error("Choose the folder this connector may use.")
            data = {**{k: v for k, v in tpl.items() if k in ("name", "kind", "url", "command")},
                    "args": [a.replace("{folder}", folder) for a in tpl.get("args", [])],
                    "token": data.get("token"), "env": data.get("env") or {}, "approval": data.get("approval")}
        try:
            conn = conns.store.add(data)
        except ValueError as e:
            return error(str(e))
        with contextlib.suppress(Exception):
            await asyncio.to_thread(conns.connect, conn, True)
        return body({**connectors_body(), "added": conn["id"]})

    async def update_connector(request: Request):
        cid = request.path_params["cid"]
        try:
            conn = conns.find(cid)
        except KeyError:
            return error("Connector not found.", 404)
        if conn.get("source", "you") != "you":
            return error("This connector comes from a plugin. Turn the plugin on or off instead.")
        data = await request.json()
        try:
            conn = conns.store.update(cid, data)
        except (KeyError, ValueError) as e:
            return error(str(e))
        conns.disconnect(cid)  # settings changed: reconnect on next use
        if conn.get("enabled"):
            with contextlib.suppress(Exception):
                await asyncio.to_thread(conns.connect, conn, True)
        return body(connectors_body())

    async def delete_connector(request: Request):
        cid = request.path_params["cid"]
        try:
            conn = conns.find(cid)
        except KeyError:
            return error("Connector not found.", 404)
        if conn.get("source", "you") != "you":
            return error("This connector comes from a plugin. Remove the plugin instead.")
        conns.disconnect(cid)
        conns.store.remove(cid)
        return body(connectors_body())

    async def test_connector(request: Request):
        try:
            conn = conns.find(request.path_params["cid"])
        except KeyError:
            return error("Connector not found.", 404)
        try:
            await asyncio.to_thread(conns.connect, conn, True)
        except Exception as e:
            return body({**connectors_body(), "error": str(e)[:600]})
        return body(connectors_body())

    # plugins -------------------------------------------------------------------
    def plugins_body() -> dict:
        markets = []
        for name, m in plugin_store.markets().items():
            try:
                items = plugin_store.market_plugins(name)
            except PluginError:
                items = []
            markets.append({"name": name, "source": m.get("source", ""), "plugins": items})
        return {"plugins": plugin_store.list(), "marketplaces": markets,
                "commands": [{k: c[k] for k in ("name", "plugin", "description", "hint")}
                             for c in plugin_store.commands()]}

    def drop_plugin_connectors(name: str) -> None:
        for cid in list(conns._status):
            if cid.startswith(f"plg-{name}-"):
                conns.disconnect(cid)

    async def list_plugins(request: Request):
        return body(plugins_body())

    async def install_plugin(request: Request):
        data = await request.json()
        allow = bool(data.get("allow_code"))
        try:
            if data.get("market"):
                info = await asyncio.to_thread(plugin_store.install_from_market, str(data["market"]),
                                               str(data.get("plugin") or ""), allow)
            elif data.get("upload"):
                meta = files.get(str(data["upload"]))
                blob = files.path(meta).read_bytes()
                info = await asyncio.to_thread(plugin_store.install, "", blob, allow, meta["name"])
            else:
                info = await asyncio.to_thread(plugin_store.install, str(data.get("source") or ""), None, allow)
        except NeedsCodeApproval as e:
            return body({"error": str(e), "needs_code_approval": True}, 409)
        except (PluginError, KeyError) as e:
            return error(str(e).strip("'\""))
        drop_plugin_connectors(info["name"])
        return body({**plugins_body(), "installed": info["name"]})

    async def update_plugin(request: Request):
        name = request.path_params["name"]
        data = await request.json()
        try:
            plugin_store.set_enabled(name, bool(data.get("enabled")))
        except KeyError:
            return error("Plugin not found.", 404)
        drop_plugin_connectors(name)
        return body(plugins_body())

    async def delete_plugin(request: Request):
        name = request.path_params["name"]
        drop_plugin_connectors(name)
        try:
            plugin_store.remove(name)
        except KeyError:
            return error("Plugin not found.", 404)
        return body(plugins_body())

    async def add_marketplace(request: Request):
        data = await request.json()
        try:
            await asyncio.to_thread(plugin_store.add_marketplace, str(data.get("source") or ""))
        except PluginError as e:
            return error(str(e))
        return body(plugins_body())

    async def delete_marketplace(request: Request):
        try:
            plugin_store.remove_marketplace(request.path_params["name"])
        except KeyError:
            return error("Marketplace not found.", 404)
        return body(plugins_body())

    # blueprints ----------------------------------------------------------------
    async def blueprints_page(request: Request):
        return FileResponse(STATIC / "blueprints.html", headers={"Cache-Control": "no-store"})

    async def list_blueprints(request: Request):
        return body({"blueprints": blueprints.list(),
                     "templates": {k: {"name": v["name"], "description": v["description"]} for k, v in BP_TEMPLATES.items()},
                     "materials": BP_MATERIALS, "shapes": list(BP_SHAPES), "situations": blueprint_sim.SITUATIONS})

    async def create_blueprint(request: Request):
        data = await request.json()
        try:
            bp = blueprints.create(str(data.get("name") or ""), str(data.get("template") or "blank"))
        except ValueError as e:
            return error(str(e))
        return body({"blueprint": bp, "summary": blueprint_sim.summary(bp)}, 201)

    async def get_blueprint(request: Request):
        try:
            bp = blueprints.get(request.path_params["bid"])
        except KeyError:
            return error("Blueprint not found.", 404)
        return body({"blueprint": bp, "summary": blueprint_sim.summary(bp), "can_undo": blueprints.can_undo(bp["id"])})

    async def save_blueprint(request: Request):
        data = await request.json()
        version = data.get("version")
        try:
            bp = blueprints.save(request.path_params["bid"], data, int(version) if version is not None else None)
        except KeyError:
            return error("Blueprint not found.", 404)
        except ValueError as e:
            return error(str(e), 409 if "changed since" in str(e) else 400)
        return body({"blueprint": bp, "summary": blueprint_sim.summary(bp), "can_undo": blueprints.can_undo(bp["id"])})

    async def delete_blueprint(request: Request):
        try:
            blueprints.delete(request.path_params["bid"])
        except KeyError:
            return error("Blueprint not found.", 404)
        return body({"blueprints": blueprints.list()})

    async def test_blueprint(request: Request):
        data = await request.json()
        try:
            bp = blueprints.get(request.path_params["bid"])
            return body(blueprint_sim.run(bp, str(data.get("situation") or ""), data.get("params") or {}))
        except KeyError:
            return error("Blueprint not found.", 404)
        except ValueError as e:
            return error(str(e))

    from .hub_api import hub_routes
    from .blueprint_api import blueprint_routes
    from .brain_api import brain_routes
    routes = brain_routes(brain) + blueprint_routes(cfg, data_dir, blueprints) + hub_routes(store=store, manager=manager, data_dir=data_dir, pick_workspace=pick_workspace,
                        public=public, routines=routines, fire_routine=fire_routine, bots=bots,
                        owner_tz=owner_tz, lead_id=LEAD_ID) + [
        Route("/", index),
        Route("/studio", studio_page),
        Route("/blueprints", blueprints_page),
        Route("/api/blueprints", list_blueprints),
        Route("/api/blueprints", create_blueprint, methods=["POST"]),
        Route("/api/blueprints/{bid}", get_blueprint),
        Route("/api/blueprints/{bid}", save_blueprint, methods=["PUT"]),
        Route("/api/blueprints/{bid}", delete_blueprint, methods=["DELETE"]),
        Route("/api/blueprints/{bid}/test", test_blueprint, methods=["POST"]),
        Route("/workspace", workspace_page),
        Route("/api/workspace", workspace_summary),
        Route("/api/workspace/{collection}", workspace_list),
        Route("/api/workspace/{collection}", workspace_create, methods=["POST"]),
        Route("/api/workspace/{collection}/{item_id}", workspace_update, methods=["PATCH"]),
        Route("/api/workspace/{collection}/{item_id}", workspace_delete, methods=["DELETE"]),
        Route("/api/models", model_catalog),
        Route("/api/models/compare", model_compare, methods=["POST"]),
        Route("/api/studio", studio_status),
        Route("/api/studio/jobs", studio_create, methods=["POST"]),
        Route("/api/studio/jobs/{jid}", studio_job),
        Route("/api/studio/jobs/{jid}/cancel", studio_cancel, methods=["POST"]),
        Route("/api/studio/jobs/{jid}/approve", studio_approve, methods=["POST"]),
        Route("/api/graphify", graphify_status),
        Route("/api/graphify/build", graphify_build, methods=["POST"]),
        Route("/api/graphify/query", graphify_query, methods=["POST"]),
        Route("/api/graphify/explain", graphify_explain, methods=["POST"]),
        Route("/api/graphify/path", graphify_path, methods=["POST"]),
        Route("/login", login_page),
        Route("/api/login", login, methods=["POST"]),
        Route("/api/logout", logout, methods=["POST"]),
        Route("/api/logout-everywhere", logout_everywhere, methods=["POST"]),
        Route("/sw.js", service_worker),
        Route("/manifest.webmanifest", manifest),
        Route("/offline.html", offline),
        Route("/api/info", info),
        Route("/api/folders/check", check_folder, methods=["POST"]),
        Route("/api/conversations", list_conversations),
        Route("/api/conversations", create_conversation, methods=["POST"]),
        Route("/api/conversations/{cid}", get_conversation),
        Route("/api/conversations/{cid}", update_conversation, methods=["PATCH"]),
        Route("/api/conversations/{cid}", delete_conversation, methods=["DELETE"]),
        Route("/api/conversations/{cid}/messages", send_message, methods=["POST"]),
        Route("/api/conversations/{cid}/events", events),
        Route("/api/conversations/{cid}/stop", stop, methods=["POST"]),
        Route("/api/conversations/{cid}/status", run_status),
        Route("/api/approvals/{aid}", approve, methods=["POST"]),
        Route("/api/restart", restart, methods=["POST"]),
        Route("/api/uploads", upload, methods=["POST"]),
        Route("/files/{aid}/{name}", serve_file),
        Route("/api/transcribe", transcribe, methods=["POST"]),
        Route("/api/node/hello", node_hello, methods=["POST"]),
        Route("/api/node/poll", node_poll),
        Route("/api/node/result", node_result, methods=["POST"]),
        Route("/api/node/ask", node_ask, methods=["POST"]),
        Route("/api/nodes", list_nodes),
        Route("/api/nodes/pair", pair_node, methods=["POST"]),
        Route("/api/nodes/{nid}", unpair_node, methods=["DELETE"]),
        Route("/api/pc/list", pc_list),
        Route("/api/pc/preview", pc_preview),
        Route("/pcfile", pc_file),
        Route("/api/bots", list_bots),
        Route("/api/bots", create_bot, methods=["POST"]),
        Route("/api/bots/{bid}", update_bot, methods=["PATCH"]),
        Route("/api/bots/{bid}", delete_bot, methods=["DELETE"]),
        Route("/api/routines", list_routines),
        Route("/api/routines", create_routine, methods=["POST"]),
        Route("/api/routines/{rid}", update_routine, methods=["PATCH"]),
        Route("/api/routines/{rid}", delete_routine, methods=["DELETE"]),
        Route("/api/routines/{rid}/run", run_routine_now, methods=["POST"]),
        Route("/api/owner", set_owner, methods=["POST"]),
        Route("/api/computer", computer_status),
        Route("/api/computer/screen", computer_screen),
        Route("/api/computer", computer_act, methods=["POST"]),
        Route("/api/connectors", list_connectors),
        Route("/api/connectors", add_connector, methods=["POST"]),
        Route("/api/connectors/{cid}", update_connector, methods=["PATCH"]),
        Route("/api/connectors/{cid}", delete_connector, methods=["DELETE"]),
        Route("/api/connectors/{cid}/test", test_connector, methods=["POST"]),
        Route("/api/plugins", list_plugins),
        Route("/api/plugins", install_plugin, methods=["POST"]),
        Route("/api/plugins/marketplaces", add_marketplace, methods=["POST"]),
        Route("/api/plugins/marketplaces/{name}", delete_marketplace, methods=["DELETE"]),
        Route("/api/plugins/{name}", update_plugin, methods=["PATCH"]),
        Route("/api/plugins/{name}", delete_plugin, methods=["DELETE"]),
        Route("/api/memory", list_memory),
        Route("/api/memory", add_memory, methods=["POST"]),
        Route("/api/memory/{mid}", delete_memory, methods=["DELETE"]),
        Mount("/static", StaticFiles(directory=STATIC), name="static"),
    ]
    @contextlib.asynccontextmanager
    async def lifespan(_app):
        scheduler.start()   # routines run while Corvis is up
        if brain is not None:
            brain.start()   # pull from GitHub, catch up on unsummarised chats, daily upkeep
        try:
            yield
        finally:
            scheduler.stop()
            if brain is not None:
                await asyncio.to_thread(brain.stop)   # write the last session summaries, push

    app = Starlette(routes=routes, middleware=[Middleware(Guard)], lifespan=lifespan)
    app.state.extra_hosts = []
    app.state.auth = auth
    app.state.node_hub = node_hub
    app.state.remote = rcfg["enabled"]
    app.state.allowed_hosts = rcfg["allowed_hosts"]
    app.state.server = None
    app.state.exit_code = 0
    app.state.manager = manager
    app.state.scheduler = scheduler
    app.state.routines = routines
    app.state.computer = computer
    app.state.studio = studio
    app.state.workspace_store = workspace_store
    app.state.brain = brain
    return app


# --- launching ----------------------------------------------------------------
def _port_free(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        return s.connect_ex((host, port)) != 0


def _is_corvis(host: str, port: int) -> bool:
    req = urllib.request.Request(f"http://{host}:{port}/api/info", headers={"X-Corvis": "1"})
    try:
        with urllib.request.urlopen(req, timeout=3) as r:
            return "name" in json.loads(r.read())
    except urllib.error.HTTPError as e:  # Corvis with remote access on asks for sign-in
        try:
            return e.code == 401 and json.loads(e.read()).get("login") is True
        except Exception:
            return False
    except Exception:
        return False


def lan_addresses() -> list[str]:
    """This PC's address(es) on the home network, for opening Corvis on a phone."""
    found = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent; just picks the main interface
            found.append(s.getsockname()[0])
    except OSError:
        pass
    return [a for a in found if not a.startswith("127.")]


def run_web(cfg: dict, open_browser: bool | None = None, port: int | None = None) -> int:
    wcfg = web_cfg(cfg)
    host = wcfg["host"]
    port = port or wcfg["port"]
    should_open = wcfg["open_browser"] if open_browser is None else open_browser
    browse_host = "127.0.0.1" if host in {"0.0.0.0", "::"} else host

    if not _port_free(browse_host, port):
        if _is_corvis(browse_host, port):
            print(f"Corvis is already running. Opening http://{browse_host}:{port}")
            if should_open:
                webbrowser.open(f"http://{browse_host}:{port}/")
            return 0
        for candidate in range(port + 1, port + 20):
            if _port_free(browse_host, candidate):
                print(f"Port {port} is in use by another program; using {candidate}.")
                port = candidate
                break

    app = create_app(cfg)
    rcfg = remote_cfg(cfg)
    if rcfg["enabled"] and not app.state.auth.has_password():
        print("\n  Remote access is turned on, but there's no owner password yet.\n"
              "  Run Set_Corvis_Password.bat (or: python -m corvis set-password), then start Corvis again.\n")
        return 1
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port, log_level="warning",
                                           proxy_headers=True, forwarded_allow_ips="127.0.0.1"))
    app.state.server = server
    url = f"http://{browse_host}:{port}/"

    def announce():
        while not server.started:
            time.sleep(0.1)
        print(f"\n  {agent_name(cfg)} is running at {url}")
        if rcfg["enabled"]:
            if host in {"0.0.0.0", "::"}:
                for ip in lan_addresses():
                    print(f"  On your phone (same Wi-Fi): http://{ip}:{port}")
            for h in rcfg["allowed_hosts"]:
                print(f"  From anywhere: https://{h}")
            print("  Other devices need the owner password. This PC signs in automatically.")
        print("  Keep this window open. Close it to shut Corvis down.\n")
        if should_open:
            launch = f"?launch={app.state.auth.launch_token()}" if rcfg["enabled"] else ""
            webbrowser.open(url + launch)

    threading.Thread(target=announce, daemon=True).start()
    server.run()
    return app.state.exit_code
