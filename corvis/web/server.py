"""A small local web app for Corvis (no extra dependencies).

Runs on http://127.0.0.1:8800 and only listens on your own machine.
"""

from __future__ import annotations

import base64
import json
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ..account import Account, HubError
from ..brain import Attachment, Corvis
from ..conversations import ConversationStore, title_from
from ..identity import Identity
from ..memory import MemoryStore
from ..models import ModelCatalog, supports_vision
from ..runtime import EFFORTS, describe_api_error, make_body
from ..workshop import Workshop

INDEX = Path(__file__).resolve().parent / "index.html"
MAX_BODY = 40 * 1024 * 1024
MAX_THUMB_CHARS = 60_000   # small image previews are stored with the chat history


class App:
    def __init__(self, identity: Identity, catalog: ModelCatalog, account: Account, workspace: Path,
                 model_id: str | None, effort: str, conversations: ConversationStore | None = None,
                 memory: MemoryStore | None = None, corvis: Corvis | None = None):
        self.identity = identity
        self.allow_commands = False
        self.lock = threading.Lock()
        self.conversations = conversations or ConversationStore()
        self.current: str | None = None   # open conversation id; None = new chat
        self.corvis = corvis or Corvis(identity, memory or MemoryStore(), make_body("avatar", identity),
                                       Workshop(workspace, approve=lambda cmd: self.allow_commands),
                                       catalog, model_id, effort, account=account)
        self.corvis.sync(force=True)

    def state(self) -> dict[str, Any]:
        c = self.corvis
        acct = c.account
        return {
            "name": self.identity.name,
            "models": [{"id": m.id, "label": m.label, "group": m.group, "description": m.description,
                        "vision": supports_vision(m)} for m in c.catalog.list()],
            "device": {**c.catalog.device.to_dict(), "summary": c.catalog.device.summary()},
            "model": c.model.id,
            "effort": c.effort,
            "efforts": EFFORTS,
            "body": c.body.name,
            "allow_commands": self.allow_commands,
            "workspace": str(c.workshop.root),
            "active_model": c.active.label if c.active else None,
            "conversations": self.conversations.list(),
            "current": self.current,
            "account": {
                "signed_in": bool(acct and acct.signed_in), "username": acct.username if acct else "",
                "hub_url": acct.hub_url if acct else "", "hub_online": bool(acct and acct.hub_online),
                "last_sync": acct.last_sync if acct else None,
            },
        }

    # --- settings and account --------------------------------------------------------

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
            if data.get("sync"):
                self.corvis.sync(force=True)
        return self.state()

    def auth(self, data: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            acct = self.corvis.account
            try:
                if data.get("action") == "logout":
                    acct.sign_out()
                else:
                    acct.sign_in(data["hub_url"], data["username"], data["password"],
                                 register=data.get("action") == "register")
                    self.corvis.sync(force=True)
            except HubError as e:
                return {**self.state(), "error": str(e)}
            self.corvis.catalog.refresh()
            if self.corvis.model.provider != "auto" and self.corvis.model not in self.corvis.catalog.list():
                self.corvis.switch_model(self.corvis.catalog.default)
        return self.state()

    # --- conversations ---------------------------------------------------------------

    def open_conversation(self, cid: str | None) -> dict[str, Any]:
        with self.lock:
            if cid and not self.conversations.exists(cid):
                raise KeyError("That conversation no longer exists.")
            msgs = self.conversations.messages(cid) if cid else []
            self.current = cid
            self.corvis.load_transcript([{"role": m["role"], "text": m["model_text"]} for m in msgs])
        return {**self.state(), "messages": [{k: m[k] for k in ("role", "text", "attachments", "model")}
                                             for m in msgs]}

    def update_conversation(self, cid: str, data: dict[str, Any]) -> dict[str, Any]:
        with self.lock:
            if data.get("delete"):
                self.conversations.delete(cid)
                if self.current == cid:
                    self.current = None
                    self.corvis.load_transcript([])
            if "title" in data:
                self.conversations.rename(cid, str(data["title"]))
            if "pinned" in data:
                self.conversations.set_pinned(cid, bool(data["pinned"]))
        return self.state()

    # --- chatting --------------------------------------------------------------------

    def chat(self, message: str, conversation: str | None, files: list[dict[str, Any]]) -> dict[str, Any]:
        events: list[str] = []
        attachments = [Attachment(f["name"], f.get("type") or "application/octet-stream",
                                  base64.b64decode(f["data"])) for f in files]
        shown = [{"name": a.name, "type": a.media_type, "size": len(a.data),
                  **({"thumb": f["thumb"]} if len(f.get("thumb") or "") <= MAX_THUMB_CHARS and f.get("thumb") else {})}
                 for a, f in zip(attachments, files)]
        with self.lock:
            if conversation != self.current:          # the app switched chats since the last message
                msgs = self.conversations.messages(conversation) if conversation else []
                self.corvis.load_transcript([{"role": m["role"], "text": m["model_text"]} for m in msgs])
                self.current = conversation
            try:
                reply = self.corvis.chat(message, on_event=events.append, attachments=attachments)
            except Exception as e:
                msg = describe_api_error(e)
                if msg is None:
                    traceback.print_exc()
                    msg = f"{type(e).__name__}: {e}"
                return {"error": msg, "events": events, "current": self.current}
            if self.current is None:
                self.current = self.conversations.create(title_from(message or files[0]["name"]))
            model = self.corvis.active.label if self.corvis.active else None
            model_text = self.corvis.transcript[-2]["text"] if len(self.corvis.transcript) >= 2 else message
            self.conversations.add_message(self.current, "user", message, model_text, shown)
            self.conversations.add_message(self.current, "assistant", reply, model=model)
            return {"reply": reply, "events": events, "model": model, "current": self.current,
                    "conversations": self.conversations.list()}

    def stop(self) -> dict[str, Any]:
        self.corvis.cancel.set()   # no lock: the running chat holds it
        return {"ok": True}


def make_server(app: App, host: str = "127.0.0.1", port: int = 8800) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, code: int, body: bytes, ctype: str = "application/json") -> None:
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
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
            if length > MAX_BODY:
                return self._json({"error": "Upload too large (40 MB max per message)."}, 413)
            try:
                data = json.loads(self.rfile.read(length) or b"{}")
                path = self.path
                if path == "/api/chat":
                    self._json(app.chat(str(data.get("message", "")), data.get("conversation"),
                                        list(data.get("files", []))))
                elif path == "/api/stop":
                    self._json(app.stop())
                elif path == "/api/settings":
                    self._json(app.settings(data))
                elif path == "/api/auth":
                    self._json(app.auth(data))
                elif path == "/api/open":
                    self._json(app.open_conversation(data.get("id")))
                elif path == "/api/conversation":
                    self._json(app.update_conversation(str(data["id"]), data))
                else:
                    self._json({"error": "not found"}, 404)
            except (KeyError, ValueError) as e:
                self._json({"error": str(e).strip("'\"")}, 400)

        def log_message(self, *args: Any) -> None:
            pass

    return ThreadingHTTPServer((host, port), Handler)


def serve(identity: Identity, catalog: ModelCatalog, account: Account, workspace: Path, port: int = 8800,
          model_id: str | None = None, effort: str = "high") -> None:
    app = App(identity, catalog, account, workspace, model_id, effort)
    server = make_server(app, "127.0.0.1", port)
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
