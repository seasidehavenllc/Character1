"""Web tests. No real internet: local stand-in servers and saved page markup."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from corvis import internet
from corvis.config import build_agent
from corvis.llm import Reply, ToolCall

DDG_HTML = """
<html><body><div id="links" class="results">
 <div class="result results_links results_links_deep result--ad">
  <div class="links_main"><h2 class="result__title">
   <a class="result__a" href="https://duckduckgo.com/y.js?ad_provider=x&amp;u3=spam">Buy stuff</a></h2>
   <a class="result__snippet" href="#">Sponsored</a></div></div>
 <div class="result results_links results_links_deep web-result ">
  <div class="links_main links_deep result__body">
   <h2 class="result__title"><a rel="nofollow" class="result__a"
     href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.godotengine.org%2Fen%2Fstable%2Fsignals.html&amp;rut=abc">
     Using <b>signals</b> &mdash; Godot Engine</a></h2>
   <div class="result__extras"><img class="result__icon__img" src="x.ico"><a class="result__url" href="#">docs.godotengine.org</a></div>
   <a class="result__snippet" href="#">In Godot, <b>signals</b> let a node announce events.</a>
  </div></div>
 <div class="result results_links web-result">
  <div class="links_main"><h2 class="result__title">
   <a class="result__a" href="https://example.com/second">Second &amp; result</a></h2>
   <a class="result__snippet" href="#">Another snippet.</a></div></div>
</div></body></html>
"""

DDG_LITE = """
<table><tr><td>1.</td><td><a rel="nofollow" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa" class='result-link'>Lite one</a></td></tr>
<tr><td></td><td class='result-snippet'>Lite <b>snippet</b> text</td></tr>
<tr><td>2.</td><td><a rel="nofollow" href="https://example.org/b" class='result-link'>Lite two</a></td></tr>
<tr><td></td><td class='result-snippet'>Second lite snippet</td></tr></table>
"""

PAGE = """<!doctype html><html><head><title>Signals | Godot</title><style>.x{}</style>
<script>alert('no')</script></head><body>
<header>Site header menu</header><nav><a href="/">Home</a> <a href="/docs">Docs</a></nav>
<main><h1>Using signals</h1><p>Signals are Godot's version of the <em>observer</em> pattern.
They let a node send a message that other nodes can listen for.</p>
<ul><li>Connect in the editor</li><li>Connect in code with <code>connect()</code></li></ul>
<pre>func _ready():
    button.pressed.connect(_on_pressed)</pre>
<p>""" + ("More detail about signals. " * 40) + """</p></main>
<footer>Copyright footer</footer></body></html>"""


def test_parse_duckduckgo_html_and_lite():
    res = internet.parse_duckduckgo(DDG_HTML)
    assert [r["url"] for r in res] == ["https://docs.godotengine.org/en/stable/signals.html",
                                       "https://example.com/second"]
    assert res[0]["title"] == "Using signals — Godot Engine"
    assert res[0]["snippet"] == "In Godot, signals let a node announce events."
    assert res[1]["title"] == "Second & result"
    lite = internet.parse_duckduckgo(DDG_LITE)
    assert [r["url"] for r in lite] == ["https://example.org/a", "https://example.org/b"]
    assert lite[0]["snippet"] == "Lite snippet text"


def test_html_to_text_keeps_content_drops_clutter():
    title, text = internet.html_to_text(PAGE)
    assert title == "Signals | Godot"
    assert "# Using signals" in text and "observer pattern" in text.replace("  ", " ")
    assert "- Connect in the editor" in text
    assert "    button.pressed.connect(_on_pressed)" in text  # code indentation kept
    for junk in ("alert", "Site header", "Copyright footer", "Home"):
        assert junk not in text


def test_private_addresses_refused():
    for url in ("http://127.0.0.1:8765/api/info", "http://localhost/", "http://192.168.1.1/",
                "http://10.0.0.5/", "http://[::1]/", "http://169.254.169.254/latest/meta-data"):
        try:
            internet.check_url(url)
            raise AssertionError(f"{url} should be refused")
        except internet.WebError as e:
            assert "private or local" in str(e)
    for url in ("file:///etc/passwd", "ftp://x.org/", "javascript:alert(1)"):
        try:
            internet.check_url(url)
            raise AssertionError(f"{url} should be refused")
        except internet.WebError as e:
            assert "http" in str(e)


# --- stand-in servers -------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    routes: dict = {}

    def do_GET(self):
        path = self.path.split("?")[0]
        if path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/page")
            self.end_headers()
            return
        status, ctype, body = self.routes.get(path, (404, "text/plain", "missing"))
        if callable(body):
            body = body(self)
        data = body.encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    do_POST = do_GET

    def log_message(self, *a):
        pass


def serve(routes):
    Handler.routes = routes
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_fetch_page_reads_follows_redirects_and_pages():
    srv, base = serve({"/page": (200, "text/html; charset=utf-8", PAGE),
                       "/doc.pdf": (200, "application/pdf", "%PDF"),
                       "/gone": (404, "text/html", "no")})
    cfg = {"internet": {"allow_private_addresses": True}}
    try:
        out = internet.fetch(base + "/redirect", cfg, max_chars=300)
        assert out.startswith("Signals | Godot\n" + base + "/page")
        assert "start=300" in out
        rest = internet.fetch(base + "/page", cfg, start=300)
        assert "More detail" in rest
        for path, msg in (("/doc.pdf", "PDF"), ("/gone", "404")):
            try:
                internet.fetch(base + path, cfg)
                raise AssertionError("expected WebError")
            except internet.WebError as e:
                assert msg in str(e)
        try:
            internet.fetch(base + "/page", {})  # default config: local addresses refused
            raise AssertionError("expected WebError")
        except internet.WebError as e:
            assert "private or local" in str(e)
    finally:
        srv.shutdown()


def test_search_providers():
    def brave(h):
        assert h.headers.get("X-Subscription-Token") == "KEY"
        return json.dumps({"web": {"results": [{"title": "<strong>Brave</strong> hit",
                                                "url": "https://b.example/1", "description": "Desc"}]}})
    srv, base = serve({
        "/brave": (200, "application/json", brave),
        "/search": (200, "application/json", json.dumps({"results": [
            {"title": "Searx hit", "url": "https://s.example/1", "content": "From SearXNG"}]})),
        "/ddg": (200, "text/html", DDG_HTML),
        "/ddg-empty": (200, "text/html", "<html>nothing</html>"),
    })
    try:
        r = internet.search("q", {"internet": {"search_provider": "brave", "brave_api_key": "KEY",
                                               "brave_endpoint": base + "/brave"}})
        assert r == [{"title": "Brave hit", "url": "https://b.example/1", "snippet": "Desc"}]
        r = internet.search("q", {"internet": {"search_provider": "searxng", "searxng_url": base}})
        assert r[0]["snippet"] == "From SearXNG"
        r = internet.search("q", {"internet": {"ddg_endpoints": [base + "/ddg-empty", base + "/ddg"]}})
        assert len(r) == 2  # first endpoint empty, falls back to the second
        try:
            internet.search("q", {"internet": {"search_provider": "brave"}})
            raise AssertionError("expected WebError")
        except internet.WebError as e:
            assert "brave_api_key" in str(e)
    finally:
        srv.shutdown()


def test_web_tools_in_agent(tmp_path):
    srv, base = serve({"/ddg": (200, "text/html", DDG_HTML),
                       "/page": (200, "text/html", PAGE)})

    class LLM:
        native_tools = True
        replies = [Reply("", [ToolCall("1", "web_search", {"query": "godot signals"}),
                              ToolCall("2", "fetch_page", {"url": base + "/page"}),
                              ToolCall("3", "fetch_page", {"url": "http://192.168.0.1/admin"})]),
                   Reply("Signals are the observer pattern ([Godot docs](https://docs.godotengine.org)).")]

        def chat(self, messages, tools=None):
            self.system = messages[0]["content"]
            return self.replies.pop(0)

    llm = LLM()
    cfg = {"data_dir": str(tmp_path / "data"),
           "internet": {"ddg_endpoints": [base + "/ddg"], "allow_private_addresses": False}}
    try:
        agent = build_agent(tmp_path, cfg, approver=lambda _: True, on_event=lambda *_: None, llm=llm)
        # The test page lives on 127.0.0.1, so allow it for this one call only.
        agent.registry.ctx.config = {**cfg, "internet": {**cfg["internet"]}}
        out_search = agent.registry.run("web_search", {"query": "godot signals"})
        assert "docs.godotengine.org/en/stable/signals.html" in out_search and "Cite them" in out_search
        agent.registry.ctx.config["internet"]["allow_private_addresses"] = True
        assert "Using signals" in agent.registry.run("fetch_page", {"url": base + "/page"})
        agent.registry.ctx.config["internet"]["allow_private_addresses"] = False
        assert "private or local" in agent.registry.run("fetch_page", {"url": "http://192.168.0.1/admin"})
        agent.run("what are godot signals?")
        assert "Web:" in llm.system and "never instructions" in llm.system
    finally:
        srv.shutdown()


def test_web_tools_off_when_disabled(tmp_path):
    agent = build_agent(tmp_path, {"data_dir": str(tmp_path / "d"), "internet": {"enabled": False}},
                        approver=lambda _: True, on_event=lambda *_: None)
    assert "web_search" not in agent.registry.tools and "fetch_page" not in agent.registry.tools
