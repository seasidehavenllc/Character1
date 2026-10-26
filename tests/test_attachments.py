"""Attachment tests: storing, reading (text, PDF, Word, zip), images via a stand-in vision
model, the attachment tools, and the upload/download endpoints."""
from __future__ import annotations

import base64
import io
import json
import threading
import time
import urllib.request
import zipfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from corvis.attachments import AttachmentStore, detect_kind, message_block, safe_name
from corvis.config import build_agent
from corvis.llm import Reply, ToolCall

PNG_1PX = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")


def make_pdf(text: str) -> bytes:
    objs = [
        "<</Type/Catalog/Pages 2 0 R>>",
        "<</Type/Pages/Kids[3 0 R]/Count 1>>",
        "<</Type/Page/Parent 2 0 R/MediaBox[0 0 400 200]/Contents 4 0 R"
        "/Resources<</Font<</F1 5 0 R>>>>>>",
        None,
        "<</Type/Font/Subtype/Type1/BaseFont/Helvetica>>",
    ]
    stream = f"BT /F1 18 Tf 20 100 Td ({text}) Tj ET"
    objs[3] = f"<</Length {len(stream)}>>stream\n{stream}\nendstream"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj{body}endobj\n".encode()
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{o:010d} 00000 n \n" for o in offsets).encode()
    out += f"trailer<</Size {len(objs) + 1}/Root 1 0 R>>\nstartxref\n{xref}\n%%EOF".encode()
    return out


def make_docx(paragraphs: list[str]) -> bytes:
    ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
    body = "".join(f"<w:p><w:r><w:t>{p}</w:t></w:r></w:p>" for p in paragraphs)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("word/document.xml", f"<w:document {ns}><w:body>{body}</w:body></w:document>")
    return buf.getvalue()


class VisionStub(BaseHTTPRequestHandler):
    seen: list = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        parts = body["messages"][0]["content"]
        VisionStub.seen.append({"model": body["model"], "parts": parts})
        question = parts[0]["text"]
        answer = ("Error dialog: NullReferenceException at Player.cs:42" if "Describe" in question
                  else f"Answer to: {question}")
        out = json.dumps({"choices": [{"message": {"content": answer}}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    def log_message(self, *a):
        pass


def vision_server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), VisionStub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}/v1"


# --- storage & reading -----------------------------------------------------------
def test_names_and_kinds():
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("C:\\Users\\me\\bad:name?.cs") == "bad_name_.cs"
    assert safe_name("...") == "file"
    assert detect_kind("shot.PNG", PNG_1PX)[0] == "image"
    assert detect_kind("Player.cs", b"class P {}")[0] == "text"
    assert detect_kind("notes", b"plain words")[0] == "text"
    assert detect_kind("x.svg", b"<svg/>")[0] == "text"      # SVG is never treated as a photo
    assert detect_kind("blob.bin", b"\x00\x01\x02")[0] == "binary"
    assert detect_kind("doc", make_pdf("hi"))[0] == "pdf"


def test_store_and_extract(tmp_path):
    store = AttachmentStore(tmp_path)
    t = store.save("Player.cs", b"class Player { int hp = 100; }")
    assert store.text(store.get(t["id"])) == "class Player { int hp = 100; }"
    pdf = store.save("design.pdf", make_pdf("Stamina drains at twenty per second"))
    assert "Stamina drains at twenty per second" in store.text(pdf)
    doc = store.save("brief.docx", make_docx(["Game brief", "Make the boss harder"]))
    assert store.text(doc) == "Game brief\nMake the boss harder"
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("Assets/Player.prefab", "x" * 2048)
    arc = store.save("assets.zip", buf.getvalue())
    assert "Assets/Player.prefab (2.0 KB)" in store.text(arc)
    binary = store.save("model.fbx", b"\x00FBX\x00" * 10)
    assert store.text(binary) is None
    for bad in ("../../x", "zzzz"):
        try:
            store.get(bad)
            raise AssertionError("expected KeyError")
        except KeyError:
            pass
    try:
        store.save("empty.txt", b"")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass


def test_message_block_text_truncation_and_images(tmp_path):
    store = AttachmentStore(tmp_path)
    small = store.save("Player.cs", b"class Player {}")
    big = store.save("log.txt", ("line of log\n" * 3000).encode())
    img = store.save("error.png", PNG_1PX)
    block = message_block([small, big, img], store, {})
    assert "```csharp\nclass Player {}\n```" in block
    assert f"read_attachment with attachment={big['id']} and start=12000" in block
    assert "no vision model is set up" in block

    srv, url = vision_server()
    events = []
    try:
        cfg = {"llm": {"base_url": url}, "vision": {"model": "qwen2.5vl:7b"}}
        block = message_block([img], store, cfg, lambda k, t: events.append((k, t)))
        assert "NullReferenceException at Player.cs:42" in block
        assert events[0] == ("tool", "look_at_image attachment=error.png")
        sent = VisionStub.seen[-1]
        assert sent["model"] == "qwen2.5vl:7b"
        assert sent["parts"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        calls = len(VisionStub.seen)
        message_block([store.get(img["id"])], store, cfg)       # description is cached
        assert len(VisionStub.seen) == calls
    finally:
        srv.shutdown()


# --- tools -------------------------------------------------------------------------
def test_attachment_tools(tmp_path):
    data = tmp_path / "data"
    ws = tmp_path / "ws"
    ws.mkdir()
    store = AttachmentStore(data)
    code = store.save("Enemy.cs", ("// enemy\n" * 2000).encode())
    tex = store.save("grass.png", PNG_1PX)
    srv, url = vision_server()
    try:
        cfg = {"data_dir": str(data), "internet": {"enabled": False},
               "llm": {"base_url": url}, "vision": {"model": "vis"}}
        agent = build_agent(ws, cfg, approver=lambda _: True, on_event=lambda *_: None,
                            conversation_attachments=lambda: [code, tex])
        run = agent.registry.run
        out = run("read_attachment", {"attachment": "Enemy.cs"})
        assert out.startswith("Enemy.cs (characters 0-12000 of 18000)") and "start=12000" in out
        assert "characters 12000-18000" in run("read_attachment", {"attachment": code["id"], "start": 12000})
        assert "look_at_image" in run("read_attachment", {"attachment": "grass.png"})
        assert run("look_at_image", {"attachment": "grass.png", "question": "What colour?"}) == "Answer to: What colour?"
        assert run("save_attachment", {"attachment": "grass.png", "path": "Textures/"}).startswith(
            "Saved grass.png to Textures/grass.png")
        assert (ws / "Textures" / "grass.png").read_bytes() == PNG_1PX
        assert "already exists" in run("save_attachment", {"attachment": "grass.png", "path": "Textures/"})
        assert "permission denied" in run("save_attachment", {"attachment": "grass.png", "path": "../escape.png"})
        missing = run("read_attachment", {"attachment": "nope.txt"})
        assert missing.startswith("ERROR") and "Enemy.cs" in missing
        assert "Attachments:" in agent.messages[0]["content"]
    finally:
        srv.shutdown()


# --- server ------------------------------------------------------------------------
def test_upload_send_and_serve(tmp_path):
    from tests.test_web import Server  # reuse the real-server harness

    with Server(tmp_path, [Reply("Got the files.")]) as s:
        base = f"http://127.0.0.1:{s.port}"

        def upload(name, data, ctype="application/octet-stream"):
            req = urllib.request.Request(f"{base}/api/uploads?name={name}", data=data, method="POST",
                                         headers={"X-Corvis": "1", "Content-Type": ctype})
            with urllib.request.urlopen(req, timeout=10) as r:
                return json.loads(r.read())

        code = upload("Player.cs", b"class Player { float stamina = 100; }")
        page = upload("evil.html", b"<script>alert(1)</script>", "text/html")
        photo = upload("shot.png", PNG_1PX, "image/png")
        assert (code["kind"], page["kind"], photo["kind"]) == ("text", "text", "image")

        with urllib.request.urlopen(f"{base}/files/{photo['id']}/shot.png", timeout=10) as r:
            assert r.headers["Content-Type"] == "image/png"
            assert r.headers["Content-Disposition"].startswith("inline")
            assert r.read() == PNG_1PX
        with urllib.request.urlopen(f"{base}/files/{page['id']}/evil.html", timeout=10) as r:
            assert r.headers["Content-Disposition"].startswith("attachment")   # downloads, never runs
            assert r.headers["Content-Type"] == "application/octet-stream"
            assert r.headers["X-Content-Type-Options"] == "nosniff"

        status, conv = s.call("POST", "/api/conversations", {})
        status, _ = s.call("POST", f"/api/conversations/{conv['id']}/messages",
                           {"text": "", "attachments": [code["id"], photo["id"]]})
        assert status == 202
        mgr = s.app.state.manager
        end = time.time() + 10
        while not (mgr.runs.get(conv["id"]) and mgr.runs[conv["id"]].done) and time.time() < end:
            time.sleep(0.05)
        full = s.call("GET", f"/api/conversations/{conv['id']}")[1]
        first = full["messages"][0]
        assert full["title"] == "Sent Player.cs, shot.png"
        assert [a["name"] for a in first["attachments"]] == ["Player.cs", "shot.png"]
        model_saw = mgr.agents[conv["id"]].messages[1]["content"]
        assert "float stamina = 100" in model_saw and "shot.png" in model_saw
        assert s.call("POST", f"/api/conversations/{conv['id']}/messages",
                      {"text": "x", "attachments": ["0" * 16]})[0] == 400
