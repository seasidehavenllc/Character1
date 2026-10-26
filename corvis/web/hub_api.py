"""API for Projects, Code sessions, Artifacts and Scheduled tasks (the Claude-style sections).

create_app() in server.py calls hub_routes() with what it shares (the chat store, the run
manager, ...) and adds the routes it returns.
"""
from __future__ import annotations

import asyncio
import html
import time
from pathlib import Path
from typing import Callable

from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from .. import code_sessions
from ..artifacts import ArtifactStore
from ..projects import KNOWLEDGE_IN_PROMPT, ProjectStore

# Model-made pages run in a sandbox: an opaque origin (so no cookies and no same-origin
# access to Corvis), no network at all, and only Corvis's bundled libraries as outside scripts.
ARTIFACT_CSP = ("sandbox allow-scripts allow-forms allow-modals allow-popups allow-pointer-lock; "
                "default-src 'none'; script-src 'unsafe-inline' 'unsafe-eval' blob: {origin}/static/vendor/; "
                "style-src 'unsafe-inline'; img-src data: blob:; font-src data:; media-src data: blob:; "
                "worker-src blob:; connect-src 'none'; form-action 'none'; base-uri 'none'; frame-ancestors 'self'")


def hub_routes(*, store, manager, data_dir: Path, pick_workspace: Callable[[str | None], str],
               public: Callable[[dict], dict], routines, fire_routine: Callable[[dict], str],
               bots, owner_tz: Callable[[], str], lead_id: str) -> list[Route]:
    projects = ProjectStore(data_dir)
    artifacts = ArtifactStore(data_dir)

    def body(data, status: int = 200):
        return JSONResponse(data, status_code=status)

    def error(message: str, status: int = 400):
        return JSONResponse({"error": message}, status_code=status)

    def chats_in(pid: str) -> list[dict]:
        out = []
        for c in store.list():
            if c.get("project") == pid:
                c["running"] = bool(manager.active(c["id"]))
                out.append(c)
        return out

    def project_view(p: dict, chats: list[dict] | None = None) -> dict:
        used = projects.knowledge_chars(p)
        return {**p, "chats": chats if chats is not None else chats_in(p["id"]),
                "knowledge": {"chars": used, "limit": KNOWLEDGE_IN_PROMPT, "in_full": used <= KNOWLEDGE_IN_PROMPT,
                              "percent": round(100 * used / KNOWLEDGE_IN_PROMPT)}}

    # projects -----------------------------------------------------------------
    async def list_projects(request: Request):
        convs = store.list()
        out = []
        for p in projects.list():
            chats = [c for c in convs if c.get("project") == p["id"]]
            v = project_view(p, chats)
            v["chat_count"] = len(chats)
            v["last_active"] = max([p["updated"]] + [c["updated"] for c in chats])
            v.pop("chats")
            out.append(v)
        return body({"projects": out})

    async def create_project(request: Request):
        data = await request.json()
        try:
            ws = pick_workspace(data["workspace"]) if data.get("workspace") else None
            p = projects.create(data.get("name", ""), data.get("description", ""), data.get("instructions", ""), ws)
        except ValueError as e:
            return error(str(e))
        return body(project_view(p, []), 201)

    def project_or_404(pid: str):
        try:
            return projects.get(pid)
        except KeyError:
            return None

    async def get_project(request: Request):
        p = project_or_404(request.path_params["pid"])
        if not p:
            return error("Project not found.", 404)
        v = project_view(p)
        v["artifacts"] = artifacts.list(project=p["id"])
        return body(v)

    async def update_project(request: Request):
        pid = request.path_params["pid"]
        data = await request.json()
        try:
            if data.get("workspace"):
                data["workspace"] = pick_workspace(data["workspace"])
            return body(project_view(projects.update(pid, data)))
        except KeyError:
            return error("Project not found.", 404)
        except ValueError as e:
            return error(str(e))

    async def delete_project(request: Request):
        pid = request.path_params["pid"]
        chats = chats_in(pid)
        if any(c["running"] for c in chats):
            return error("Corvis is working in one of this project's chats. Stop him first.", 409)
        try:
            projects.delete(pid)
        except KeyError:
            return error("Project not found.", 404)
        for c in chats:   # its chats go with it, as in Claude
            manager.forget(c["id"])
            store.delete(c["id"])
        return body({"ok": True, "deleted_chats": len(chats)})

    async def add_project_file(request: Request):
        pid = request.path_params["pid"]
        data = await request.json()
        try:
            if data.get("attachment"):
                p = projects.add_file(pid, str(data["attachment"]))
            else:
                p = projects.add_text(pid, data.get("name", ""), data.get("text", ""))
        except KeyError:
            return error("Project or file not found.", 404)
        except ValueError as e:
            return error(str(e))
        return body(project_view(p))

    async def remove_project_file(request: Request):
        try:
            return body(project_view(projects.remove_file(request.path_params["pid"], request.path_params["fid"])))
        except KeyError:
            return error("Project not found.", 404)

    async def project_file_text(request: Request):
        p = project_or_404(request.path_params["pid"])
        if not p:
            return error("Project not found.", 404)
        try:
            f, text = projects.file_text(p, request.path_params["fid"])
        except KeyError as e:
            return error(str(e.args[0]) if e.args else "File not found.", 404)
        return body({"name": f["name"], "text": text[:400_000]})

    async def add_project_note(request: Request):
        data = await request.json()
        try:
            return body(project_view(projects.add_note(request.path_params["pid"], data.get("text", ""), by="owner")))
        except KeyError:
            return error("Project not found.", 404)
        except ValueError as e:
            return error(str(e))

    async def remove_project_note(request: Request):
        try:
            return body(project_view(projects.remove_note(request.path_params["pid"], request.path_params["nid"])))
        except KeyError:
            return error("Project not found.", 404)

    async def new_project_chat(request: Request):
        p = project_or_404(request.path_params["pid"])
        if not p:
            return error("Project not found.", 404)
        data = await request.json() if await request.body() else {}
        try:
            ws = pick_workspace(p.get("workspace"))
        except ValueError as e:
            return error(str(e))
        bot = str(data.get("bot") or lead_id)
        try:
            bots.get(bot)
        except KeyError:
            return error("That bot doesn't exist any more.", 404)
        return body(public(store.create(ws, "project", bot=bot, project=p["id"])), 201)

    async def move_chat(request: Request):
        """Put a chat into a project, or take it out (project: null)."""
        cid = request.path_params["cid"]
        data = await request.json()
        pid = data.get("project") or None
        if pid and not project_or_404(pid):
            return error("Project not found.", 404)
        try:
            conv = store.get(cid)
        except KeyError:
            return error("Chat not found.", 404)
        if conv["mode"] == "self":
            return error("Chats that improve Corvis himself can't go in a project.")
        conv["project"] = pid
        store.save(conv)
        manager.forget(cid)
        return body(public(conv))

    # code sessions ------------------------------------------------------------
    def code_view(c: dict) -> dict:
        info = c.get("code") or {}
        c["running"] = bool(manager.active(c["id"]))
        run = manager.active(c["id"])
        c["waiting"] = bool(run and run._approvals)
        try:
            c["stat"] = code_sessions.stat(c["workspace"], info)
        except Exception:
            c["stat"] = {"files": 0, "added": 0, "removed": 0}
        return c

    async def list_code(request: Request):
        sessions = [c for c in store.list() if c.get("kind") == "code"][:40]
        out = await asyncio.to_thread(lambda: [code_view(c) for c in sessions])
        for c in out:
            try:
                conv = store.get(c["id"])
                last = next((m for m in reversed(conv["messages"]) if m.get("text")), None)
                c["last"] = " ".join((last or {}).get("text", "").split())[:180]
            except KeyError:
                c["last"] = ""
        return body({"sessions": out})

    async def new_code_session(request: Request):
        data = await request.json()
        try:
            ws = pick_workspace(data.get("folder"))
        except ValueError as e:
            return error(str(e))
        info = await asyncio.to_thread(code_sessions.start, ws, str(data.get("title") or data.get("prompt") or ""),
                                       bool(data.get("branch")))
        conv = store.create(ws, "project", bot=lead_id, project=data.get("project") or None, kind="code")
        conv["code"] = info
        store.save(conv)
        return body(public(conv), 201)

    def code_conv(cid: str):
        try:
            conv = store.get(cid)
        except KeyError:
            return None
        return conv if conv.get("kind") == "code" else None

    async def code_diff(request: Request):
        conv = code_conv(request.path_params["cid"])
        if not conv:
            return error("Code session not found.", 404)
        return body(await asyncio.to_thread(code_sessions.diff, conv["workspace"], conv.get("code") or {}))

    async def code_commit(request: Request):
        conv = code_conv(request.path_params["cid"])
        if not conv:
            return error("Code session not found.", 404)
        if manager.active(conv["id"]):
            return error("Corvis is still working. Wait for him to finish, then commit.", 409)
        data = await request.json()
        try:
            line = await asyncio.to_thread(code_sessions.commit, conv["workspace"], data.get("message", ""))
        except ValueError as e:
            return error(str(e))
        return body({"ok": True, "result": line})

    # artifacts ----------------------------------------------------------------
    async def list_artifacts(request: Request):
        q = request.query_params
        return body({"artifacts": artifacts.list(conversation_id=q.get("conversation") or None,
                                                 project=q.get("project") or None)})

    async def get_artifact(request: Request):
        try:
            a = artifacts.get(request.path_params["aid"])
        except KeyError:
            return error("Artifact not found.", 404)
        title = None
        if a.get("conversation_id"):
            try:
                title = store.get(a["conversation_id"])["title"]
            except KeyError:
                pass
        return body({**a, "conversation_title": title, "filename": artifacts.filename(a)})

    async def update_artifact(request: Request):
        data = await request.json()
        try:
            a = artifacts.rename(request.path_params["aid"], data.get("title", ""))
            if data.get("content") is not None:   # the owner edited it by hand
                a = artifacts.add_version(a["id"], str(data["content"]), "Edited by you")
        except KeyError:
            return error("Artifact not found.", 404)
        except ValueError as e:
            return error(str(e))
        return body(artifacts.summary(a))

    async def delete_artifact(request: Request):
        try:
            artifacts.delete(request.path_params["aid"])
        except KeyError:
            return error("Artifact not found.", 404)
        return body({"ok": True})

    def version_of(a: dict, raw: str | None) -> dict:
        try:
            n = int(raw or 0)
        except ValueError:
            n = 0
        return a["versions"][n - 1] if 1 <= n <= len(a["versions"]) else a["versions"][-1]

    async def view_artifact(request: Request):
        """The page itself, for the sandboxed frame. Never served as part of Corvis's own origin."""
        try:
            a = artifacts.get(request.path_params["aid"])
        except KeyError:
            return Response("Artifact not found.", status_code=404, media_type="text/plain")
        content = version_of(a, request.query_params.get("v"))["content"]
        if a["type"] == "html":
            media = "text/html; charset=utf-8"
        elif a["type"] == "svg":
            media = "text/html; charset=utf-8"   # wrapped, so it scales to the panel
            content = ("<!doctype html><meta charset=utf-8><style>html,body{margin:0;height:100%;background:#fff}"
                       "svg{display:block;width:100%;height:100%}</style>" + content)
        else:   # documents and code are drawn by the app itself; this is just a plain fallback
            media = "text/html; charset=utf-8"
            content = f"<!doctype html><meta charset=utf-8><pre style='white-space:pre-wrap'>{html.escape(content)}</pre>"
        origin = f"{request.url.scheme}://{request.url.netloc}"
        return Response(content, media_type=media, headers={
            "Content-Security-Policy": ARTIFACT_CSP.format(origin=origin),
            "X-Content-Type-Options": "nosniff", "X-Frame-Options": "SAMEORIGIN", "Cache-Control": "no-store"})

    async def download_artifact(request: Request):
        try:
            a = artifacts.get(request.path_params["aid"])
        except KeyError:
            return error("Artifact not found.", 404)
        content = version_of(a, request.query_params.get("v"))["content"]
        return Response(content.encode("utf-8"), media_type="application/octet-stream", headers={
            "Content-Disposition": f'attachment; filename="{artifacts.filename(a)}"', "X-Content-Type-Options": "nosniff"})

    # scheduled tasks ----------------------------------------------------------
    def run_outcome(run: dict) -> dict:
        """Fill in how a past run went, from the chat it ran in."""
        out = dict(run)
        cid = run.get("conversation_id")
        if not cid:
            return out
        try:
            conv = store.get(cid)
        except KeyError:
            out["status"] = "chat deleted"
            return out
        for i, m in enumerate(conv["messages"]):
            if m["role"] == "assistant" and m.get("ts", 0) >= run["ts"]:
                out["status"] = {"ok": "done"}.get(m.get("status"), m.get("status") or "done")
                out["summary"] = " ".join((m.get("text") or "").split())[:200]
                out["message"] = i
                return out
        out["status"] = "running" if manager.active(cid) else out.get("status", "no reply")
        return out

    async def list_scheduled(request: Request):
        items = routines.list()
        for r in items:
            r["runs"] = [run_outcome(x) for x in reversed(r.get("runs") or [])]
            try:
                r["bot_name"] = bots.get(r["bot"])["name"]
            except KeyError:
                r["bot_name"] = "?"
        return body({"tasks": items, "tz": owner_tz(), "now": time.time()})

    async def create_scheduled(request: Request):
        data = await request.json()
        try:
            bots.get(str(data.get("bot") or lead_id))
            r = routines.create(data.get("name", ""), str(data.get("bot") or lead_id), data.get("prompt", ""),
                                data.get("schedule") or {}, data.get("tz") or owner_tz(), fresh=bool(data.get("fresh")))
        except KeyError:
            return error("That bot doesn't exist.", 404)
        except ValueError as e:
            return error(str(e))
        return body(r, 201)

    async def update_scheduled(request: Request):
        data = {k: v for k, v in (await request.json()).items() if k in ("name", "prompt", "bot", "enabled", "tz",
                                                                         "schedule", "fresh")}
        try:
            return body(routines.update(request.path_params["rid"], data))
        except KeyError:
            return error("That task doesn't exist.", 404)
        except ValueError as e:
            return error(str(e))

    return [
        Route("/api/projects", list_projects),
        Route("/api/projects", create_project, methods=["POST"]),
        Route("/api/projects/{pid}", get_project),
        Route("/api/projects/{pid}", update_project, methods=["PATCH"]),
        Route("/api/projects/{pid}", delete_project, methods=["DELETE"]),
        Route("/api/projects/{pid}/files", add_project_file, methods=["POST"]),
        Route("/api/projects/{pid}/files/{fid}", project_file_text),
        Route("/api/projects/{pid}/files/{fid}", remove_project_file, methods=["DELETE"]),
        Route("/api/projects/{pid}/notes", add_project_note, methods=["POST"]),
        Route("/api/projects/{pid}/notes/{nid}", remove_project_note, methods=["DELETE"]),
        Route("/api/projects/{pid}/chats", new_project_chat, methods=["POST"]),
        Route("/api/conversations/{cid}/project", move_chat, methods=["POST"]),
        Route("/api/code/sessions", list_code),
        Route("/api/code/sessions", new_code_session, methods=["POST"]),
        Route("/api/code/sessions/{cid}/diff", code_diff),
        Route("/api/code/sessions/{cid}/commit", code_commit, methods=["POST"]),
        Route("/api/artifacts", list_artifacts),
        Route("/api/artifacts/{aid}", get_artifact),
        Route("/api/artifacts/{aid}", update_artifact, methods=["PATCH"]),
        Route("/api/artifacts/{aid}", delete_artifact, methods=["DELETE"]),
        Route("/api/artifacts/{aid}/download", download_artifact),
        Route("/artifact-view/{aid}", view_artifact),
        Route("/api/scheduled", list_scheduled),
        Route("/api/scheduled", create_scheduled, methods=["POST"]),
        Route("/api/scheduled/{rid}", update_scheduled, methods=["PATCH"]),
    ]
