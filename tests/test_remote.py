"""Remote access (phone) tests: owner password, sessions, rate limiting, the PC's one-time
sign-in, the address allow-list, and the installable-app files."""
from __future__ import annotations

import http.cookiejar
import json
import threading
import time
import urllib.error
import urllib.request

import uvicorn

from corvis.llm import Reply
from corvis.web import auth as auth_mod
from corvis.web.auth import Auth
from corvis.web.server import create_app, run_web

from tests.test_web import _free_port, manager_with

PASSWORD = "ravens fly at midnight"


# --- the password & sessions ----------------------------------------------------------
def test_password_sessions_and_lockout(tmp_path):
    auth = Auth(tmp_path)
    assert not auth.has_password()
    try:
        auth.set_password("short")
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    auth.set_password(PASSWORD)
    stored = json.loads((tmp_path / "auth.json").read_text())
    assert PASSWORD not in json.dumps(stored)            # only a hash is stored

    token = auth.login(PASSWORD, "iPhone")
    assert token and auth.valid(token) and not auth.valid("made-up")
    assert token not in json.dumps(json.loads((tmp_path / "auth.json").read_text()))  # tokens hashed too
    auth.logout(token)
    assert not auth.valid(token)

    a, b = auth.login(PASSWORD), auth.login(PASSWORD)
    auth.set_password(PASSWORD + "!")                    # new password signs everyone out
    assert not auth.valid(a) and not auth.valid(b)

    old_sleep = auth_mod.time.sleep
    auth_mod.time.sleep = lambda s: None                 # skip the anti-guessing delay in tests
    try:
        for _ in range(auth_mod.MAX_FAILURES):
            assert auth.login("wrong guess") is None
        assert auth.locked_for() > 0
        assert auth.login(PASSWORD + "!") is None         # even the right password waits
    finally:
        auth_mod.time.sleep = old_sleep


def test_launch_token_is_single_use(tmp_path):
    auth = Auth(tmp_path)
    t = auth.launch_token()
    assert auth.use_launch_token(t) and not auth.use_launch_token(t)
    stale = auth.launch_token()
    auth._launch[stale] = time.time() - 1      # pretend two minutes have passed
    assert not auth.use_launch_token(stale)


# --- the server with remote access on --------------------------------------------------
class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):
        return None


class RemoteServer:
    def __init__(self, tmp_path, allowed_hosts=None, password=True):
        mgr = manager_with(tmp_path, [Reply("hi from Corvis")])
        (tmp_path / "proj").mkdir(exist_ok=True)
        cfg = {**mgr.cfg, "web": {"default_workspace": str(tmp_path / "proj")},
               "remote": {"enabled": True, "allowed_hosts": allowed_hosts or []}}
        mgr.cfg = cfg
        self.app = create_app(cfg, manager=mgr)
        if password:
            self.app.state.auth.set_password(PASSWORD)
        self.port = _free_port()
        self.server = uvicorn.Server(uvicorn.Config(self.app, host="127.0.0.1", port=self.port, log_level="error"))
        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar), NoRedirect)

    def __enter__(self):
        self.thread.start()
        while not self.server.started:
            time.sleep(0.02)
        return self

    def __exit__(self, *exc):
        self.server.should_exit = True
        self.thread.join(5)

    def req(self, method, path, data=None, headers=None):
        hdrs = {"X-Corvis": "1", "Content-Type": "application/json", **(headers or {})}
        r = urllib.request.Request(f"http://127.0.0.1:{self.port}{path}", method=method,
                                   data=json.dumps(data).encode() if data is not None else None,
                                   headers={k: v for k, v in hdrs.items() if v is not None})
        try:
            with self.opener.open(r, timeout=10) as resp:
                return resp.status, dict(resp.headers), resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read().decode()


def test_remote_requires_sign_in(tmp_path):
    with RemoteServer(tmp_path) as s:
        status, headers, _ = s.req("GET", "/")
        assert status == 303 and headers["location"] == "/login"
        status, _, text = s.req("GET", "/api/info")
        assert status == 401 and json.loads(text)["login"] is True
        assert s.req("GET", "/api/conversations")[0] == 401
        assert s.req("POST", "/api/uploads?name=x.txt", None)[0] == 401
        assert s.req("GET", "/files/0123456789abcdef/x.png")[0] in (303, 401)

        # what must stay reachable before signing in
        assert s.req("GET", "/login")[0] == 200
        assert s.req("GET", "/static/app.css")[0] == 200
        status, headers, text = s.req("GET", "/manifest.webmanifest")
        assert status == 200 and headers["content-type"].startswith("application/manifest+json")
        assert json.loads(text)["display"] == "standalone"
        status, headers, _ = s.req("GET", "/sw.js")
        assert status == 200 and headers["service-worker-allowed"] == "/"
        assert s.req("GET", "/offline.html")[0] == 200

        # wrong, then right password
        status, _, text = s.req("POST", "/api/login", {"password": "nope"})
        assert status == 401 and "Wrong password" in text
        status, headers, _ = s.req("POST", "/api/login", {"password": PASSWORD})
        cookie = headers["set-cookie"]
        assert status == 200 and "HttpOnly" in cookie and "samesite=lax" in cookie.lower()
        status, headers, text = s.req("GET", "/api/info")
        assert status == 200 and json.loads(text)["remote"] is True
        assert headers["x-frame-options"] == "DENY"

        # the chat works once signed in
        status, _, text = s.req("POST", "/api/conversations", {})
        assert status == 201

        # sign out
        assert s.req("POST", "/api/logout")[0] == 200
        assert s.req("GET", "/api/info")[0] == 401


def test_pc_signs_in_with_launch_token(tmp_path):
    with RemoteServer(tmp_path) as s:
        token = s.app.state.auth.launch_token()
        status, headers, _ = s.req("GET", f"/?launch={token}")
        assert status == 303 and headers["location"] == "/" and "corvis_session=" in headers["set-cookie"]
        assert s.req("GET", "/api/info")[0] == 200
        s.jar.clear()
        status, headers, _ = s.req("GET", f"/?launch={token}")   # can't be used twice
        assert status == 303 and headers["location"] == "/login"


def test_allowed_hosts_and_header_rule(tmp_path):
    with RemoteServer(tmp_path, allowed_hosts=["corvis.example.com"]) as s:
        s.req("POST", "/api/login", {"password": PASSWORD})
        assert s.req("GET", "/api/info", headers={"Host": "corvis.example.com"})[0] == 200
        assert s.req("GET", "/api/info", headers={"Host": "evil.example.net"})[0] == 403
        assert s.req("GET", "/api/info", headers={"X-Corvis": None})[0] == 403  # other sites can't call the API


def test_remote_without_password_refuses_to_start(tmp_path):
    cfg = {"data_dir": str(tmp_path), "remote": {"enabled": True},
           "web": {"port": _free_port(), "open_browser": False}}
    assert run_web(cfg, open_browser=False) == 1


def test_pc_only_mode_still_needs_no_password(tmp_path):
    from tests.test_web import Server
    with Server(tmp_path, []) as s:
        status, info = s.call("GET", "/api/info")
        assert status == 200 and info["remote"] is False
