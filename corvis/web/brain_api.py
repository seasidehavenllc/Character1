"""The second brain's API: dashboard, library, graph, reviews, reports, learning jobs, memory,
greetings and GitHub sync (see corvis/brain/). The GitHub token can be set but is never returned."""
from __future__ import annotations

import asyncio
from pathlib import Path

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from ..brain.kb import DEFAULT_CATEGORIES

READABLE = ("Knowledge/", "Reports/", "Memory/", "Conversations/", "Projects/", "Dashboard.md", "README.md")


def brain_routes(brain) -> list[Route]:
    if brain is None:
        async def off(request: Request):
            return JSONResponse({"error": "The second brain is turned off (brain.enabled in config.yaml)."}, status_code=404)
        return [Route("/api/brain", off), Route("/api/brain/{rest:path}", off, methods=["GET", "POST"])]
    kb, jobs, cont, repo = brain.kb, brain.jobs, brain.continuity, brain.repo

    def body(data, status: int = 200):
        return JSONResponse(data, status_code=status)

    def error(message: str, status: int = 400):
        return JSONResponse({"error": message}, status_code=status)

    async def payload(request: Request) -> dict:
        try:
            data = await request.json()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    def card(d: dict) -> dict:
        return {"id": d["id"], "title": d["title"], "category": d["category"], "summary": d.get("summary", ""),
                "confidence": d.get("confidence", 0), "health": d["health"], "last_verified": d.get("last_verified"),
                "created": d.get("created"), "sources": len(d.get("sources") or []), "related": d.get("related", []),
                "tags": d.get("tags") or []}

    async def overview(request: Request):
        def build():
            dash = kb.dashboard()
            active = jobs.active()
            return {"dashboard": dash, "jobs": jobs.list()[:8], "active": active["id"] if active else None,
                    "categories": sorted(set(DEFAULT_CATEGORIES) | set(dash["categories"])),
                    "sync": brain.settings(), "memory": cont is not None,
                    "maintenance": brain._last_maintained()}
        return body(await asyncio.to_thread(build))

    async def files(request: Request):
        q = request.query_params.get("q", "").strip()
        cat = request.query_params.get("category", "").strip()
        if q:
            docs = await asyncio.to_thread(kb.search, q, 40, False)
        else:
            docs = await asyncio.to_thread(kb.all)
            docs.sort(key=lambda d: (d["category"], d["title"].lower()))
        return body([card(d) for d in docs if not cat or d["category"] == cat])

    async def file(request: Request):
        doc_id = request.query_params.get("id", "")
        try:
            d = await asyncio.to_thread(kb.get, doc_id)
        except KeyError as e:
            return error(str(e).strip("'\""), 404)
        pending = next((p for p in kb.pending() if p["id"] == d["id"]), None)
        return body({**card(d), "body": d["body"], "path": d["path"], "sources_list": d.get("sources") or [],
                     "history": d.get("history") or [], "conflicts": d.get("conflicts") or [],
                     "related_titles": d.get("related_titles") or {}, "archive": kb.archive_versions(d["id"]),
                     "paths": [" → ".join(c) for c in kb.neighbours(d["id"], 2)[:12]], "pending": pending})

    async def graph(request: Request):
        return body(await asyncio.to_thread(kb.graph))

    async def pending(request: Request):
        return body(await asyncio.to_thread(kb.pending))

    async def approve(request: Request):
        data = await payload(request)
        try:
            d = await asyncio.to_thread(kb.approve, str(data.get("id", "")))
        except KeyError as e:
            return error(str(e).strip("'\""), 404)
        return body(card(d))

    async def reject(request: Request):
        data = await payload(request)
        try:
            await asyncio.to_thread(kb.reject, str(data.get("id", "")), str(data.get("why", ""))[:200])
        except KeyError as e:
            return error(str(e).strip("'\""), 404)
        return body({"ok": True})

    async def reports(request: Request):
        return body(await asyncio.to_thread(kb.reports))

    async def raw(request: Request):
        """Read one markdown file from the brain (reports, archived versions, summaries, projects)."""
        rel = request.query_params.get("path", "").replace("\\", "/").lstrip("/")
        root = brain.root.resolve()
        target = (root / rel).resolve()
        if (not rel.startswith(READABLE) or not rel.endswith(".md") or ".." in rel.split("/")
                or not target.is_relative_to(root) or not target.is_file()):
            return error("No such file in the brain.", 404)
        return body({"path": rel, "text": target.read_text(encoding="utf-8")[:200_000]})

    async def list_jobs(request: Request):
        return body(jobs.list())

    async def start_job(request: Request):
        data = await payload(request)
        try:
            job = brain.learn(str(data.get("topic", "")), str(data.get("mode", "learn")), by="owner")
        except ValueError as e:
            return error(str(e))
        return body(job)

    async def stop_job(request: Request):
        try:
            return body(jobs.stop(request.path_params["jid"]))
        except KeyError:
            return error("No such learning session.", 404)

    async def maintain(request: Request):
        return body(await asyncio.to_thread(brain.maintain))

    async def memory(request: Request):
        if cont is None:
            return body({"sessions": [], "projects": [], "conversations": []})

        def build():
            return {"sessions": cont.sessions(30), "projects": [cont.project(p["name"]) or p for p in cont.projects()],
                    "conversations": cont.search_conversations("", limit=40)}
        return body(await asyncio.to_thread(build))

    async def conversations(request: Request):
        if cont is None:
            return body([])
        try:
            since = max(0, int(request.query_params.get("since_days") or 0))
        except ValueError:
            since = 0
        return body(cont.search_conversations(request.query_params.get("q", ""), since_days=since, limit=20))

    async def save_project(request: Request):
        if cont is None:
            return error("Conversation memory is turned off.", 404)
        data = await payload(request)
        name = str(data.get("name", "")).strip()
        if not name:
            return error("Give the project a name.")
        p = await asyncio.to_thread(cont.update_project, name, data)
        await asyncio.to_thread(repo.commit, f"Project memory: {p['name']} (edited by the owner)")
        return body(p)

    async def greeting(request: Request):
        if cont is None:
            return body({"text": "", "context": {}})
        force = request.query_params.get("force") in ("1", "true")
        g = await asyncio.to_thread(cont.greeting, None, force)
        return body({"text": g["text"], "context": g.get("context", {}), "by_model": g.get("by_model", False)})

    async def sync_status(request: Request):
        return body(await asyncio.to_thread(brain.settings))

    async def sync_settings(request: Request):
        data = await payload(request)
        allowed = {k: data[k] for k in ("remote", "token", "auto_push", "auto_approve_confidence") if k in data}
        try:
            out = await asyncio.to_thread(brain.update_settings, allowed)
        except (ValueError, TypeError) as e:
            return error(str(e))
        return body(out)

    async def push(request: Request):
        msg = await asyncio.to_thread(repo.push)
        return body({"message": msg, **brain.settings()}, 200 if not repo.status.get("error") else 502)

    async def pull(request: Request):
        msg = await asyncio.to_thread(repo.pull)
        return body({"message": msg, **brain.settings()}, 200 if not repo.status.get("error") else 502)

    return [
        Route("/api/brain", overview),
        Route("/api/brain/files", files),
        Route("/api/brain/file", file),
        Route("/api/brain/graph", graph),
        Route("/api/brain/pending", pending),
        Route("/api/brain/pending/approve", approve, methods=["POST"]),
        Route("/api/brain/pending/reject", reject, methods=["POST"]),
        Route("/api/brain/reports", reports),
        Route("/api/brain/raw", raw),
        Route("/api/brain/jobs", list_jobs),
        Route("/api/brain/jobs", start_job, methods=["POST"]),
        Route("/api/brain/jobs/{jid}/stop", stop_job, methods=["POST"]),
        Route("/api/brain/maintain", maintain, methods=["POST"]),
        Route("/api/brain/memory", memory),
        Route("/api/brain/conversations", conversations),
        Route("/api/brain/projects", save_project, methods=["POST"]),
        Route("/api/brain/greeting", greeting),
        Route("/api/brain/sync", sync_status),
        Route("/api/brain/sync", sync_settings, methods=["POST"]),
        Route("/api/brain/sync/push", push, methods=["POST"]),
        Route("/api/brain/sync/pull", pull, methods=["POST"]),
    ]
