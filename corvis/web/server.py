"""A small local web app for Corvis (no extra dependencies).

Runs on http://127.0.0.1:8800 and only listens on your own machine.
"""

from __future__ import annotations

import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..brain import Corvis
from ..identity import Identity
from ..memory import MemoryStore
from ..models import ModelCatalog
from ..runtime import EFFORTS, describe_api_error, make_body
from ..workshop import Workshop

INDEX = Path(__file__).resolve().parent / "index.html"


class App:
    def __init__(self, identity: Identity, catalog: ModelCatalog, workspace: Path,
                 model_id: str | None, effort: str):
        self.identity = identity
        self.allow_commands = False
        self.lock = threading.Lock()
        self.corvis = Corvis(identity, MemoryStore(), make_body("avatar", identity),
                             Workshop(workspace, approve=lambda cmd: self.allow_commands),
                             catalog, model_id, effort)

    def state(self) -> dict[str, Any]:
        c = self.corvis
        return {
            "name": self.identity.name,
            "self_image": self.identity.self_image,
            "models": [{"id": m.id, "label": m.label, "group": m.group, "description": m.description}
                       for m in c.catalog.list()],
            "device": {**c.catalog.device.to_dict(), "summary": c.catalog.device.summary()},
            "model": c.model.id,
            "effort": c.effort,
            "efforts": EFFORTS,
            "body": c.body.name,
            "allow_commands": self.allow_commands,
            "workspace": str(c.workshop.root),
            "transcript": c.transcript,
        }

    def settings(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if data.get("refresh_models"):
                self.corvis.catalog.refresh()
            if "model" in data:
                self.corvis.switch_model(data["model"])
            if "effort" in data and data["effort"] in EFFORTS:
                self.corvis.set_effort(data["effort"])
            if "body" in data and data["body"] != self.corvis.body.name:
                self.corvis.transfer_to(make_body(data["body"], self.identity))
            if "allow_commands" in data:
                self.allow_commands = bool(data["allow_commands"])
        return self.state()

    def chat(self, message: str) -> dict[str, Any]:
        events: list[str] = []
        with self.lock:
            try:
                reply = self.corvis.chat(message, on_event=events.append)
                return {"reply": reply, "events": events, "model": self.corvis.model.label}
            except Exception as e:
                msg = describe_api_error(e)
                if msg is None:
                    traceback.print_exc()
                    msg = f"{type(e).__name__}: {e}"
                return {"error": msg, "events": events}


def serve(identity: Identity, catalog: ModelCatalog, workspace: Path, port: int = 8800,
          model_id: str | None = None, effort: str = "high") -> None:
    app = App(identity, catalog, workspace, model_id, effort)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _json(self, data: Any, code: int = 200) -> None:
            self._send(code, json.dumps(data).encode())

        def do_GET(self) -> None:
            if self.path in ("/", "/index.html"):
                self._send(200, INDEX.read_bytes(), "text/html; charset=utf-8")
            elif self.path == "/api/state":
                self._json(app.state())
            else:
                self._json({"error": "not found"}, 404)

        def do_POST(self) -> None:
            length = int(self.headers.get("Content-Length", 0))
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                if self.path == "/api/chat":
                    self._json(app.chat(str(data.get("message", ""))))
                elif self.path == "/api/settings":
                    self._json(app.settings(data))
                else:
                    self._json({"error": "not found"}, 404)
            except (KeyError, ValueError) as e:
                self._json({"error": str(e)}, 400)

        def log_message(self, *args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}"
    print(f"Corvis web app running at {url}  (Ctrl+C to stop)")
    threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        app.corvis.body.shutdown()
        print("\nCorvis offline.")
