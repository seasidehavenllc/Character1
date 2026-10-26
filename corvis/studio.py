"""Corvis Creative Studio and Mission Control task registry.

This module intentionally separates workflow planning from execution. It never claims a
render or generation happened unless a configured adapter reports a completed artifact.
"""
from __future__ import annotations
import json, shutil, threading, time, uuid
from pathlib import Path
from typing import Any
from .graphify_integration import GraphifyIntegration

APP_CATALOG = [
 {"id":"gimp","name":"GIMP","category":"image","url":"https://www.gimp.org/","commands":["gimp"],"formats":["xcf","png","jpg","tif"]},
 {"id":"krita","name":"Krita","category":"image","url":"https://krita.org/","commands":["krita"],"formats":["kra","ora","png"]},
 {"id":"inkscape","name":"Inkscape","category":"design","url":"https://inkscape.org/","commands":["inkscape"],"formats":["svg","pdf","png"]},
 {"id":"darktable","name":"darktable","category":"photo","url":"https://www.darktable.org/","commands":["darktable"],"formats":["xmp","jpg","tif"]},
 {"id":"rawtherapee","name":"RawTherapee","category":"photo","url":"https://rawtherapee.com/","commands":["rawtherapee"],"formats":["jpg","tif"]},
 {"id":"blender","name":"Blender","category":"3d","url":"https://www.blender.org/","commands":["blender"],"formats":["blend","obj","stl","fbx","glb"]},
 {"id":"kdenlive","name":"Kdenlive","category":"video","url":"https://kdenlive.org/","commands":["kdenlive"],"formats":["kdenlive","mp4","mov"]},
 {"id":"ffmpeg","name":"FFmpeg","category":"video","url":"https://ffmpeg.org/","commands":["ffmpeg"],"formats":["mp4","mov","wav","mp3"]},
 {"id":"davinci-resolve","name":"DaVinci Resolve","category":"video","url":"https://www.blackmagicdesign.com/products/davinciresolve","commands":["resolve","DaVinciResolve"],"formats":["drp","mp4","mov"]},
 {"id":"scribus","name":"Scribus","category":"publishing","url":"https://www.scribus.net/","commands":["scribus"],"formats":["sla","pdf"]},
]
MODEL_CATALOG = [
 {"id":"wan","name":"Wan video models","kind":"video","url":"https://github.com/Wan-Video/Wan2.2","mode":"local-or-adapter"},
 {"id":"ltx","name":"LTX video models","kind":"video","url":"https://github.com/Lightricks/LTX-Video","mode":"local-or-adapter"},
 {"id":"hunyuan","name":"HunyuanVideo","kind":"video","url":"https://github.com/Tencent-Hunyuan/HunyuanVideo","mode":"local-or-adapter"},
 {"id":"cogvideo","name":"CogVideoX","kind":"video","url":"https://github.com/THUDM/CogVideo","mode":"local-or-adapter"},
 {"id":"image-api","name":"Configured image API","kind":"image","mode":"requires-config"},
]

class CreativeStudio:
    def __init__(self, data_dir: str | Path, workspace: str | Path, config: dict | None = None):
        self.root = Path(data_dir) / "studio"
        self.root.mkdir(parents=True, exist_ok=True)
        self.workspace = Path(workspace).expanduser()
        self.workspace.mkdir(parents=True, exist_ok=True)
        self.config = config or {}
        self.file = self.root / "jobs.json"
        self.lock = threading.RLock()
        self.jobs: dict[str, dict] = {}
        try:
            raw = json.loads(self.file.read_text(encoding="utf-8"))
            self.jobs = {x["id"]: x for x in raw if isinstance(x, dict) and x.get("id")}
        except (OSError, ValueError, TypeError): pass

    def _save(self):
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(list(self.jobs.values()), indent=2), encoding="utf-8")
        tmp.replace(self.file)

    def applications(self):
        result=[]
        for item in APP_CATALOG:
            executable = next((shutil.which(x) for x in item["commands"] if shutil.which(x)), None)
            result.append({**item, "installed": bool(executable), "executable": executable})
        return result

    def models(self):
        configured = self.config.get("creative", {}).get("models", {}) or {}
        return [{**m, "configured": bool(configured.get(m["id"]))} for m in MODEL_CATALOG]

    def snapshot(self):
        with self.lock:
            jobs = sorted(self.jobs.values(), key=lambda j: j.get("updated_at", 0), reverse=True)
            graphify = GraphifyIntegration(self.workspace).status()
            return {"applications": self.applications(), "models": self.models(), "jobs": jobs[:100],
                    "integrations": [graphify], "graphify": graphify,
                    "workspace": str(self.workspace), "capabilities": {"job_tracking": True,
                    "desktop_automation": bool(self.config.get("computer", {}).get("enabled", True)),
                    "video_generation": any(m["configured"] for m in self.models() if m["kind"] == "video"),
                    "knowledge_graph": graphify["ready"],
                    "note": "Model generation needs a configured adapter or local model runtime; availability is not inferred from repository links."}}

    def create_job(self, payload: dict):
        title = str(payload.get("title") or "Creative project").strip()[:160]
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt: raise ValueError("Describe what you want Corvis to create.")
        kind = str(payload.get("kind") or "image")
        if kind not in {"image", "video", "design", "photo", "3d", "publishing", "creative-mix"}:
            raise ValueError("Unsupported creative project type.")
        jid = uuid.uuid4().hex[:12]
        now = time.time()
        outdir = (self.workspace / "CorvisStudio" / jid).resolve()
        # Output is constrained to the configured workspace, not arbitrary user paths.
        base = (self.workspace / "CorvisStudio").resolve()
        if base not in outdir.parents: raise ValueError("Invalid output path.")
        plan = self._plan(kind, prompt)
        job = {"id":jid,"title":title,"prompt":prompt,"kind":kind,"status":"planned","progress":0,
               "created_at":now,"updated_at":now,"output_dir":str(outdir),"plan":plan,"events":[
               {"ts":now,"status":"planned","message":"Project brief saved; execution has not started."}],
               "artifacts":[],"approval_required":True,"execution_note":"Planned only. Start requires an explicit approval step and a configured execution adapter."}
        with self.lock:
            self.jobs[jid]=job; self._save()
        return job

    def _plan(self, kind: str, prompt: str):
        plans = {
          "image":[("brief","Clarify image dimensions, style, and target format"),("generate","Generate a draft with a configured image model"),("edit","Use GIMP or Krita for layers, masks, and retouching"),("verify","Inspect image dimensions and export a final asset")],
          "video":[("brief","Define aspect ratio, duration, shot list, and audio needs"),("shots","Generate or import individual shots using a configured video model"),("edit","Assemble clips in Kdenlive or DaVinci Resolve; use FFmpeg for verified conversions"),("verify","Check codec, duration, audio, and final playback")],
          "design":[("brief","Define audience, layout, brand, and deliverable formats"),("create","Create editable vector artwork in Inkscape"),("refine","Review typography, alignment, contrast, and variants"),("export","Export SVG/PDF and raster previews")],
          "photo":[("ingest","Inspect source files and preserve originals"),("develop","Apply RAW/color adjustments in darktable or RawTherapee"),("retouch","Use GIMP/Krita for local edits and compositing"),("verify","Check color, resolution, and export settings")],
          "3d":[("brief","Specify geometry, units, dimensions, tolerances, and output format"),("model","Create an editable Blender scene or scripted model"),("inspect","Check scale, normals, parts, and scene structure"),("export","Export requested interchange or 3D-print format")],
          "publishing":[("brief","Define page size, bleed, typography, and output intent"),("layout","Build editable layout in Scribus"),("preflight","Check fonts, linked assets, margins, and bleed"),("export","Export and inspect print-ready PDF")],
          "creative-mix":[("brief","Convert the brief into image, video, audio, design, and 3D deliverables"),("assets","Generate or import source assets using configured tools"),("production","Edit assets in the appropriate desktop applications"),("review","Review consistency, accessibility, and technical specs"),("deliver","Package editable project files and final exports")],
        }
        return [{"id":f"step-{i+1}","key":key,"title":label,"status":"queued"} for i,(key,label) in enumerate(plans[kind])]

    def get(self, jid):
        with self.lock:
            if jid not in self.jobs: return None
            return self.jobs[jid]

    def update_status(self, jid, status, message, progress=None):
        allowed={"planned","waiting_approval","running","paused","cancelled","completed","failed"}
        if status not in allowed: raise ValueError("Invalid job status.")
        with self.lock:
            job=self.jobs.get(jid)
            if not job: return None
            now=time.time(); job.update(status=status,updated_at=now)
            if status == "waiting_approval":
                job["execution_note"] = "Approval recorded; execution is blocked until a compatible model/application adapter is configured."
            elif status == "cancelled":
                job["execution_note"] = "Cancelled by user. No external process is assumed to have stopped unless its adapter confirms cancellation."
            if progress is not None: job["progress"]=max(0,min(100,int(progress)))
            job.setdefault("events",[]).append({"ts":now,"status":status,"message":str(message)[:500]})
            job["events"]=job["events"][-200:]
            self._save(); return job

    def cancel(self, jid):
        job=self.get(jid)
        if not job: return None
        if job["status"] in {"completed","failed","cancelled"}: return job
        return self.update_status(jid,"cancelled","Cancelled by the user. No external job is assumed to have stopped unless its adapter confirms cancellation.")
