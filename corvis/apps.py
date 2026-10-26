"""Opening and closing apps on the PC (Windows first; basic support elsewhere).

Finds apps the way you would: Start Menu and desktop shortcuts, your Steam library,
and a few built-ins (VS Code, File Explorer, Notepad, Terminal, Settings...).
"""
from __future__ import annotations

import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path

IS_WINDOWS = os.name == "nt"
SKIP_SHORTCUT_WORDS = ("uninstall", "readme", "read me", "help", "website", "release notes",
                       "documentation", "manual", "license", "support", "changelog")
NOT_GAMES = ("steamworks common", "proton", "steam linux runtime", "redistributable", "directx",
             "steamvr")


@dataclass
class App:
    name: str
    kind: str     # "shortcut" | "steam" | "command" | "uri"
    target: str   # shortcut path, steam app id, command/exe, or URI
    source: str = ""


def normalize(name: str) -> str:
    name = re.sub(r"[™®©]", "", name.lower())
    return " ".join(re.sub(r"[^a-z0-9]+", " ", name).split())


ALIASES = {
    "vs code": "visual studio code", "vscode": "visual studio code", "code": "visual studio code",
    "explorer": "file explorer", "files": "file explorer", "terminal": "windows terminal",
    "cmd": "command prompt", "calc": "calculator", "task manager": "task manager",
    "chrome": "google chrome", "edge": "microsoft edge", "firefox": "mozilla firefox",
    "word": "microsoft word", "excel": "microsoft excel", "ue5": "unreal engine",
    "unreal": "unreal engine", "unity": "unity hub", "settings": "windows settings",
}


def builtin_apps() -> list[App]:
    apps = []
    if IS_WINDOWS:
        local = os.environ.get("LOCALAPPDATA", "")
        for exe in (Path(local) / "Programs/Microsoft VS Code/Code.exe",
                    Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Microsoft VS Code/Code.exe"):
            if exe.is_file():
                apps.append(App("Visual Studio Code", "command", str(exe), "built-in"))
                break
        else:
            if shutil.which("code"):
                apps.append(App("Visual Studio Code", "command", "code", "built-in"))
        apps += [App("File Explorer", "command", "explorer.exe", "built-in"),
                 App("Notepad", "command", "notepad.exe", "built-in"),
                 App("Command Prompt", "command", "cmd.exe", "built-in"),
                 App("Calculator", "uri", "calculator:", "built-in"),
                 App("Task Manager", "command", "taskmgr.exe", "built-in"),
                 App("Windows Settings", "uri", "ms-settings:", "built-in")]
        if shutil.which("wt"):
            apps.append(App("Windows Terminal", "command", "wt.exe", "built-in"))
    elif shutil.which("code"):
        apps.append(App("Visual Studio Code", "command", "code", "built-in"))
    return apps


def start_menu_dirs() -> list[Path]:
    if not IS_WINDOWS:
        return [Path.home() / ".local/share/applications", Path("/usr/share/applications")]
    dirs = []
    for env in ("ProgramData", "APPDATA"):
        if os.environ.get(env):
            dirs.append(Path(os.environ[env]) / "Microsoft/Windows/Start Menu/Programs")
    for desk in (Path.home() / "Desktop", Path(os.environ.get("PUBLIC", "C:/Users/Public")) / "Desktop"):
        dirs.append(desk)
    return dirs


def shortcut_apps(dirs: list[Path]) -> list[App]:
    apps = []
    for d in dirs:
        if not d.is_dir():
            continue
        for p in d.rglob("*"):
            if p.suffix.lower() not in (".lnk", ".url", ".desktop") or not p.is_file():
                continue
            name = p.stem
            if any(w in name.lower() for w in SKIP_SHORTCUT_WORDS):
                continue
            kind, target = "shortcut", str(p)
            if p.suffix.lower() == ".url":  # Steam/Epic desktop shortcuts are .url files
                try:
                    m = re.search(r"^URL=(.+)$", p.read_text(errors="ignore"), re.M)
                except OSError:
                    m = None
                if m and m.group(1).strip().startswith("steam://rungameid/"):
                    kind, target = "steam", m.group(1).strip().rsplit("/", 1)[-1]
            apps.append(App(name, kind, target, str(d)))
    return apps


def steam_root() -> Path | None:
    if IS_WINDOWS:
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam") as k:
                return Path(winreg.QueryValueEx(k, "SteamPath")[0])
        except OSError:
            pass
        for guess in ("C:/Program Files (x86)/Steam", "C:/Program Files/Steam"):
            if Path(guess).is_dir():
                return Path(guess)
        return None
    for guess in (Path.home() / ".steam/steam", Path.home() / ".local/share/Steam"):
        if guess.is_dir():
            return guess
    return None


def _vdf_values(text: str, key: str) -> list[str]:
    return [m.group(1).replace("\\\\", "\\") for m in re.finditer(rf'"{key}"\s+"([^"]*)"', text)]


def steam_games(root: Path | None) -> list[App]:
    if root is None:
        return []
    libraries = [root]
    vdf = root / "steamapps/libraryfolders.vdf"
    if vdf.is_file():
        libraries += [Path(p) for p in _vdf_values(vdf.read_text(errors="ignore"), "path")]
    games, seen = [], set()
    for lib in libraries:
        for acf in (lib / "steamapps").glob("appmanifest_*.acf"):
            text = acf.read_text(errors="ignore")
            ids, names = _vdf_values(text, "appid"), _vdf_values(text, "name")
            if not ids or not names or ids[0] in seen:
                continue
            if any(w in names[0].lower() for w in NOT_GAMES):
                continue
            seen.add(ids[0])
            games.append(App(names[0], "steam", ids[0], f"Steam library {lib}"))
    return games


class AppIndex:
    """All launchable apps. Rescanned at most once a minute."""

    def __init__(self, dirs: list[Path] | None = None, steam: Path | None | bool = True):
        self.dirs = dirs
        self.steam = steam
        self._apps: list[App] = []
        self._at = 0.0

    def apps(self) -> list[App]:
        if not self._apps or time.monotonic() - self._at > 60:
            root = steam_root() if self.steam is True else (self.steam or None)
            found = builtin_apps() + steam_games(root) + shortcut_apps(self.dirs or start_menu_dirs())
            unique: dict[str, App] = {}
            for a in found:  # prefer built-ins and Steam entries over duplicate shortcuts
                unique.setdefault(normalize(a.name), a)
            self._apps, self._at = list(unique.values()), time.monotonic()
        return self._apps

    def find(self, query: str, limit: int = 5) -> list[tuple[int, App]]:
        q = normalize(query)
        q = ALIASES.get(q, q)
        if not q:
            return []
        qt = set(q.split())
        scored = []
        for a in self.apps():
            n = normalize(a.name)
            nt = set(n.split())
            if n == q:
                s = 100
            elif n.startswith(q) or (len(q) >= 3 and n.replace(" ", "") == q.replace(" ", "")):
                s = 90
            elif q in n:
                s = 80
            elif qt and qt <= nt:
                s = 75
            else:
                s = int(difflib.SequenceMatcher(None, q, n).ratio() * 70)
            if s >= 50:
                scored.append((s, a))
        scored.sort(key=lambda x: (-x[0], len(x[1].name)))
        return scored[:limit]


_shared: AppIndex | None = None


def shared_index() -> AppIndex:
    """One index for the whole program, so scanning happens at most once a minute."""
    global _shared
    if _shared is None:
        _shared = AppIndex()
    return _shared


# --- launching & closing ----------------------------------------------------------
def _startfile(target: str, arguments: str = "") -> None:
    if IS_WINDOWS:
        if arguments:
            os.startfile(target, "open", arguments)  # type: ignore[attr-defined]
        else:
            os.startfile(target)  # type: ignore[attr-defined]
    else:
        opener = "open" if sys.platform == "darwin" else "xdg-open"
        subprocess.Popen([opener, target], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _popen(cmd: list[str]) -> None:
    flags = 0
    if IS_WINDOWS:
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        if Path(cmd[0]).suffix.lower() in (".cmd", ".bat") or cmd[0] == "code":
            cmd = ["cmd", "/c", *cmd]
    subprocess.Popen(cmd, creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     stdin=subprocess.DEVNULL, close_fds=True)


# Tests replace these two to avoid launching real programs.
launcher = {"startfile": _startfile, "popen": _popen}


def launch(app: App, path: str = "") -> str:
    if app.kind == "steam":
        launcher["startfile"](f"steam://rungameid/{app.target}")
        return f"Asked Steam to start {app.name}."
    if app.kind == "uri":
        launcher["startfile"](app.target)
        return f"Opened {app.name}."
    if app.kind == "command":
        launcher["popen"]([app.target, path] if path else [app.target])
        return f"Opened {app.name}" + (f" with {path}." if path else ".")
    launcher["startfile"](app.target, f'"{path}"' if path else "")
    return f"Opened {app.name}" + (f" with {path}." if path else ".")


def _powershell(script: str, timeout: int = 30) -> str:
    proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                          capture_output=True, text=True, timeout=timeout)
    if proc.returncode != 0:
        raise OSError((proc.stderr or proc.stdout).strip()[:300])
    return proc.stdout


runner = {"powershell": _powershell}


def open_windows() -> list[dict]:
    """Running programs that have a window: [{'name', 'pid', 'title'}]."""
    if not IS_WINDOWS and runner["powershell"] is _powershell:
        raise OSError("Listing open apps is only supported on Windows for now.")
    out = runner["powershell"](
        "Get-Process | Where-Object { $_.MainWindowTitle } | "
        "Select-Object @{n='name';e={$_.ProcessName}}, @{n='pid';e={$_.Id}}, "
        "@{n='title';e={$_.MainWindowTitle}} | ConvertTo-Json -Compress")
    out = out.strip()
    if not out:
        return []
    data = json.loads(out)
    items = data if isinstance(data, list) else [data]
    me = os.getpid()
    return [i for i in items if int(i.get("pid", 0)) != me]


def match_windows(query: str, windows: list[dict]) -> list[dict]:
    q = normalize(ALIASES.get(normalize(query), query))
    q_short = q.replace(" ", "")
    hits = []
    for w in windows:
        n, t = normalize(w["name"]), normalize(w["title"])
        if q in (n, n.replace(" ", "")) or q_short == n.replace(" ", "") or q in t or q_short in n.replace(" ", ""):
            hits.append(w)
        elif {"visual studio code"} & {q} and n == "code":
            hits.append(w)
    return hits


def close(windows: list[dict], force: bool = False) -> str:
    ids = ",".join(str(int(w["pid"])) for w in windows)
    if force:
        runner["powershell"](f"Stop-Process -Id {ids} -Force")
        return "Force-closed " + ", ".join(w["name"] for w in windows) + "."
    runner["powershell"](f"Get-Process -Id {ids} | ForEach-Object {{ [void]$_.CloseMainWindow() }}")
    return ("Asked " + ", ".join(w["name"] for w in windows) + " to close (like clicking X). "
            "If it has unsaved work it may ask you first.")
