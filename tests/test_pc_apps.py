"""PC-wide files, apps, installs, phone setup and voice endpoints.
Windows-only pieces (launching, Steam, winget, closing windows) use stand-ins."""
from __future__ import annotations

import json
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from corvis import apps, installs, pc, phone_setup
from corvis.config import CORVIS_HOME, build_agent


def make_agent(tmp_path, approvals=None, **extra):
    """Agent whose PC access is limited to tmp_path; approvals is a list of True/False answers."""
    project = tmp_path / "project"
    project.mkdir(exist_ok=True)
    asked = []

    def approver(prompt):
        asked.append(prompt)
        return approvals.pop(0) if approvals else False

    cfg = {"data_dir": str(tmp_path / "data"), "internet": {"enabled": False},
           "pc_access": {"roots": [str(tmp_path)]}, **extra}
    agent = build_agent(project, cfg, approver=approver, on_event=lambda *_: None)
    return agent, asked


# --- guardrails ------------------------------------------------------------------------
def test_policy_roots_private_and_read_only(tmp_path):
    corvis_home, data = tmp_path / "corvis", tmp_path / "corvis" / "data"
    data.mkdir(parents=True)
    (data / "auth.json").write_text("{}")
    pol = pc.PCPolicy({"pc_access": {"roots": [str(tmp_path / "games"), str(corvis_home)],
                                     "private": [str(tmp_path / "games" / "taxes")]}}, corvis_home, data)
    (tmp_path / "games" / "taxes").mkdir(parents=True)
    assert pol.check(tmp_path / "games" / "a.txt", "write")
    for path, action, why in [
        (tmp_path / "elsewhere.txt", "read", "outside"),
        (data / "auth.json", "read", "private"),
        (tmp_path / "games" / "taxes" / "2025.pdf", "read", "private"),
        (tmp_path / "games", "delete", "private"),              # would delete a private folder inside
        (corvis_home / "corvis" / "agent.py", "write", "protected"),
        (corvis_home, "delete", "private"),
    ]:
        try:
            pol.check(path, action)
            raise AssertionError(f"{path} {action} should be refused")
        except PermissionError as e:
            assert why in str(e), (path, str(e))
    assert pol.check(corvis_home / "README.md", "read")        # reading Corvis's own files is fine
    listing = pc.list_dir(pol, str(tmp_path / "games"))
    assert [e["name"] for e in listing["entries"]] == []       # the private folder isn't even listed
    assert [c["name"] for c in listing["crumbs"]] == [str(tmp_path / "games")]


def test_pc_tools_flow(tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "notes.txt").write_text("buy milk\nfinish boss fight")
    (docs / "old").mkdir()
    (docs / "old" / "level1.map").write_text("x")
    agent, asked = make_agent(tmp_path, approvals=[True, False, True, True])
    run = agent.registry.run

    assert str(tmp_path) in run("pc_list", {})
    assert "notes.txt" in run("pc_list", {"path": str(docs)})
    assert "finish boss fight" in run("pc_read", {"path": str(docs / "notes.txt")})
    assert "level1.map" in run("pc_find", {"name": "*.map", "folder": str(tmp_path)})

    # creating a new plain file outside the project: no question needed
    assert run("pc_write", {"path": str(docs / "todo.md"), "content": "- ship it"}).startswith("Created")
    assert not asked
    # a script outside the project asks (approved), overwriting outside asks (declined)
    assert run("pc_write", {"path": str(docs / "go.bat"), "content": "echo hi"}).startswith("Created")
    assert "declined" in run("pc_write", {"path": str(docs / "notes.txt"), "content": "x", "overwrite": True})
    assert (docs / "notes.txt").read_text().startswith("buy milk")
    # inside the project, scripts don't need a question
    n = len(asked)
    run("pc_write", {"path": str(tmp_path / "project" / "build.bat"), "content": "make"})
    assert len(asked) == n

    assert run("pc_make_folder", {"path": str(docs / "new")}).startswith("Created folder")
    assert run("pc_move", {"source": str(docs / "todo.md"), "destination": str(docs / "new")}).startswith("Moved")
    assert (docs / "new" / "todo.md").exists()
    out = run("pc_delete", {"path": str(docs / "old")})
    assert out.startswith("Deleted") and not (docs / "old").exists()
    assert "Recycle Bin" in asked[-1] and "1 files" in asked[-1]
    trashed = list((tmp_path / "data" / "trash").iterdir())       # recoverable (Recycle Bin on Windows)
    assert trashed and (trashed[0] / "level1.map").exists()
    assert "outside the folders" in run("pc_read", {"path": "/etc/hostname"})
    assert "won't delete a whole drive" in run("pc_delete", {"path": str(tmp_path)}) or \
           "private" in run("pc_delete", {"path": str(tmp_path)})


def test_pc_access_can_be_turned_off(tmp_path):
    agent, _ = make_agent(tmp_path, pc_access={"enabled": False})
    assert "pc_list" not in agent.registry.tools


# --- apps ------------------------------------------------------------------------------
def fake_pc(tmp_path):
    menu = tmp_path / "StartMenu" / "Programs"
    (menu / "Visual Studio Code").mkdir(parents=True)
    (menu / "Visual Studio Code" / "Visual Studio Code.lnk").write_bytes(b"lnk")
    (menu / "Spotify.lnk").write_bytes(b"lnk")
    (menu / "Uninstall Spotify.lnk").write_bytes(b"lnk")
    (menu / "Deep Rock Galactic.url").write_text("[InternetShortcut]\nURL=steam://rungameid/548430\n")
    steam = tmp_path / "Steam"
    lib2 = tmp_path / "SteamLibrary2"
    (steam / "steamapps").mkdir(parents=True)
    (lib2 / "steamapps").mkdir(parents=True)
    (steam / "steamapps" / "libraryfolders.vdf").write_text(
        '"libraryfolders"\n{\n\t"0"\n\t{\n\t\t"path"\t\t"%s"\n\t}\n}\n' % str(lib2).replace("\\", "\\\\"))
    (lib2 / "steamapps" / "appmanifest_553850.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"553850"\n\t"name"\t\t"HELLDIVERS™ 2"\n}\n')
    (steam / "steamapps" / "appmanifest_228980.acf").write_text(
        '"AppState"\n{\n\t"appid"\t\t"228980"\n\t"name"\t\t"Steamworks Common Redistributables"\n}\n')
    return apps.AppIndex(dirs=[menu], steam=steam)


def test_app_index_finds_shortcuts_and_steam_games(tmp_path):
    idx = fake_pc(tmp_path)
    names = {a.name for a in idx.apps()}
    assert "Uninstall Spotify" not in names and "Steamworks Common Redistributables" not in names
    best = idx.find("helldivers 2")[0][1]
    assert (best.kind, best.target) == ("steam", "553850")
    assert idx.find("vs code")[0][1].name == "Visual Studio Code"
    assert idx.find("deep rock")[0][1].target == "548430"
    assert idx.find("zzzz nothing") == []


def test_open_and_close_apps_with_stand_ins(tmp_path):
    calls = []
    old_launcher, old_runner = dict(apps.launcher), dict(apps.runner)
    apps.launcher.update(startfile=lambda t, a="": calls.append(("start", t, a)),
                         popen=lambda cmd: calls.append(("popen", cmd)))
    windows = [{"name": "Spotify", "pid": 4242, "title": "Spotify Premium"},
               {"name": "Code", "pid": 77, "title": "player.py - MyGame - Visual Studio Code"}]
    scripts = []

    def ps(script, timeout=30):
        scripts.append(script)
        return json.dumps(windows) if script.startswith("Get-Process | Where") else ""
    apps.runner["powershell"] = ps
    try:
        agent, asked = make_agent(tmp_path, approvals=[False, True], )
        agent.registry.ctx.state["app_index"] = fake_pc(tmp_path)
        # rebuild the app tools so they use the fake index
        from corvis.tools import app_tools
        app_tools.register(agent.registry, agent.registry.ctx)
        run = agent.registry.run
        assert run("open_app", {"name": "helldivers 2"}) == "Asked Steam to start HELLDIVERS™ 2."
        assert calls[-1] == ("start", "steam://rungameid/553850", "")
        proj = tmp_path / "project"
        assert run("open_app", {"name": "vs code", "file_or_folder": str(proj)}).startswith("Opened Visual Studio Code")
        assert calls[-1][2] == f'"{proj}"'
        assert "Spotify" in run("list_open_apps", {})
        assert "declined" in run("close_app", {"name": "spotify"})
        assert run("close_app", {"name": "spotify"}).startswith("Asked Spotify to close")
        assert "-Id 4242" in scripts[-1] and "CloseMainWindow" in scripts[-1]
        assert apps.match_windows("visual studio code", windows)[0]["pid"] == 77
        assert "only http" in run("open_url", {"url": "file:///C:/Windows"})
    finally:
        apps.launcher.update(old_launcher)
        apps.runner.update(old_runner)


# --- installs --------------------------------------------------------------------------
WINGET_OUT = """\r   - \r   \\ \r
Name               Id                           Version  Match         Source
---------------------------------------------------------------------------------
Visual Studio Code Microsoft.VisualStudioCode   1.105.1  Moniker: code winget
VSCodium           VSCodium.VSCodium            1.105.0                winget
"""


def test_winget_search_and_install(tmp_path):
    rows = installs.parse_winget_table(WINGET_OUT)
    assert rows[0] == {"name": "Visual Studio Code", "id": "Microsoft.VisualStudioCode",
                       "version": "1.105.1", "source": "winget"}
    assert rows[1]["id"] == "VSCodium.VSCodium"
    ran = []
    old = dict(installs.runner)
    installs.runner.update(which=lambda n: "C:/winget.exe",
                           run=lambda cmd, timeout: (ran.append(cmd), (0, WINGET_OUT if cmd[1] == "search"
                                                                       else "Successfully installed"))[1])
    try:
        agent, asked = make_agent(tmp_path, approvals=[False, True])
        run = agent.registry.run
        assert "Microsoft.VisualStudioCode" in run("search_installable", {"query": "vs code"})
        assert "declined" in run("install_app", {"package_id": "Microsoft.VisualStudioCode"})
        assert run("install_app", {"package_id": "Microsoft.VisualStudioCode"}).startswith("Installed")
        assert ran[-1][:4] == ["winget", "install", "--id", "Microsoft.VisualStudioCode"]
        assert "--silent" in ran[-1]
        assert "doesn't look like" in run("install_app", {"package_id": "x; rm -rf /"}) or \
               "declined" in run("install_app", {"package_id": "x; rm -rf /"})
    finally:
        installs.runner.update(old)


def test_download_file(tmp_path):
    class H(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/get":
                self.send_response(302); self.send_header("Location", "/files/setup.exe"); self.end_headers(); return
            data = b"MZ fake installer" if self.path.endswith(".exe") else b"<html>page</html>"
            self.send_response(200)
            self.send_header("Content-Type", "application/octet-stream" if self.path.endswith(".exe") else "text/html")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, *a):
            pass

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        dl = tmp_path / "Downloads"
        info = installs.download(base + "/get", dl, {"internet": {"allow_private_addresses": True}})
        assert Path(info["path"]).name == "setup.exe" and info["size"] == 17 and len(info["sha256"]) == 64
        again = installs.download(base + "/get", dl, {"internet": {"allow_private_addresses": True}})
        assert Path(again["path"]).name == "setup (1).exe"
        try:
            installs.download(base + "/page", dl, {"internet": {"allow_private_addresses": True}})
            raise AssertionError("a web page isn't a download")
        except Exception as e:
            assert "web page" in str(e)
        try:
            installs.download(base + "/get", dl, {})  # default: local addresses refused
            raise AssertionError("expected refusal")
        except Exception as e:
            assert "private or local" in str(e)
    finally:
        srv.shutdown()


# --- phone setup -------------------------------------------------------------------------
def test_update_remote_config_keeps_comments():
    text = ("name: Corvis\n\nremote:\n  # comment stays\n  enabled: false\n  allowed_hosts: []\n\n"
            "pc_access:\n  enabled: true\n")
    out = phone_setup.update_remote_config(text, "my-pc.tail1.ts.net")
    assert "  enabled: true\n  allowed_hosts: [my-pc.tail1.ts.net]" in out
    assert "# comment stays" in out and "pc_access:\n  enabled: true" in out
    again = phone_setup.update_remote_config(out, "my-pc.tail1.ts.net")
    assert again.count("my-pc.tail1.ts.net") == 1
    assert "remote:\n  enabled: true" in phone_setup.update_remote_config("name: x\n", "h.ts.net")


def test_phone_setup_run(tmp_path):
    cfgfile = tmp_path / "config.yaml"
    cfgfile.write_text("remote:\n  enabled: false\n  allowed_hosts: []\n")
    from corvis.web.auth import Auth
    Auth(tmp_path / "data").set_password("ravens fly at midnight")
    cmds = []
    old_run, old_find = dict(phone_setup.runner), phone_setup.find_tailscale

    def fake_run(cmd, timeout=60):
        cmds.append(cmd)
        if cmd[1] == "status":
            return 0, json.dumps({"BackendState": "Running", "Self": {"DNSName": "kody-pc.tail9.ts.net."}})
        return 0, "Available within your tailnet: https://kody-pc.tail9.ts.net/"
    phone_setup.runner["run"] = fake_run
    phone_setup.runner["stream"] = lambda cmd, timeout=600: fake_run(cmd)
    phone_setup.find_tailscale = lambda: "tailscale"
    try:
        code = phone_setup.run({"data_dir": str(tmp_path / "data")}, cfgfile, lambda: None)
    finally:
        phone_setup.runner.update(old_run)
        phone_setup.find_tailscale = old_find
    assert code == 0
    assert ["tailscale", "serve", "--bg", "8765"] in cmds
    assert "allowed_hosts: [kody-pc.tail9.ts.net]" in cfgfile.read_text()
    assert (tmp_path / "config.yaml.bak").exists()


# --- server: files browser and voice --------------------------------------------------------
def test_files_browser_and_voice_endpoints(tmp_path):
    (tmp_path / "Pictures").mkdir()
    png = __import__("base64").b64decode(
        "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg==")
    (tmp_path / "Pictures" / "shot.png").write_bytes(png)
    (tmp_path / "Pictures" / "page.html").write_text("<script>alert(1)</script>")
    # A server whose PC access is limited to tmp_path:
    import time
    import urllib.error
    import urllib.request

    import uvicorn

    from corvis.web.server import create_app
    from tests.test_web import _free_port, manager_with
    mgr = manager_with(tmp_path, [])
    cfg = {**mgr.cfg, "pc_access": {"roots": [str(tmp_path)]}}
    mgr.cfg = cfg
    app = create_app(cfg, manager=mgr)
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="error"))
    t = threading.Thread(target=server.run, daemon=True)
    t.start()
    while not server.started:
        time.sleep(0.02)
    base = f"http://127.0.0.1:{port}"

    def get(path, headers=None):
        req = urllib.request.Request(base + path, headers={"X-Corvis": "1", **(headers or {})})
        try:
            with urllib.request.urlopen(req, timeout=10) as r:
                return r.status, {k.lower(): v for k, v in r.headers.items()}, r.read()
        except urllib.error.HTTPError as e:
            return e.code, {k.lower(): v for k, v in e.headers.items()}, e.read()

    try:
        status, _, data = get("/api/pc/list?path=" + str(tmp_path / "Pictures"))
        listing = json.loads(data)
        assert status == 200 and [e["name"] for e in listing["entries"]] == ["page.html", "shot.png"]
        status, _, data = get("/api/pc/preview?path=" + str(tmp_path / "Pictures" / "page.html"))
        assert json.loads(data)["kind"] == "text"
        status, headers, data = get("/pcfile?path=" + str(tmp_path / "Pictures" / "shot.png"))
        assert headers["content-type"] == "image/png" and data == png
        status, headers, _ = get("/pcfile?path=" + str(tmp_path / "Pictures" / "page.html"))
        assert headers["content-disposition"].startswith("attachment")   # never runs in the page
        assert get("/api/pc/list?path=/etc")[0] == 403
        info = json.loads(get("/api/info")[2])
        assert info["pc_access"] is True and info["voice"]["speech_to_text"] in ("local", "browser")
        req = urllib.request.Request(base + "/api/transcribe", data=b"x" * 500, method="POST",
                                     headers={"X-Corvis": "1", "Content-Type": "audio/webm"})
        try:
            urllib.request.urlopen(req, timeout=10)
        except urllib.error.HTTPError as e:
            assert e.code == 500 and "Install_Voice.bat" in e.read().decode()
    finally:
        server.should_exit = True
        t.join(5)
