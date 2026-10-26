"""Files anywhere on the PC, not just the current project, with guardrails.

What's off limits completely (can't even be read):
  passwords, keys and browser data: .ssh, credential stores, browser profiles,
  password managers, and Corvis's own password file.
What can be read but never changed:
  Windows itself, Program Files, ProgramData, Startup folders (so nothing can be set to
  run when you log in), and Corvis's own code (use "Corvis himself" for that).
Everything else inside the allowed roots (all your drives, by default) is fair game. The
tools ask you first before deleting, moving, overwriting outside the project, or writing
scripts/programs outside the project. Deleting sends things to the Recycle Bin.
"""
from __future__ import annotations

import fnmatch
import os
import shutil
import string
import subprocess
import time
from pathlib import Path

from .safety import IGNORED_DIRS

IS_WINDOWS = os.name == "nt"

# Writing these outside a project needs the owner's OK: they can run code.
RUNNABLE_EXTS = {".exe", ".bat", ".cmd", ".ps1", ".psm1", ".vbs", ".vbe", ".js", ".jse", ".wsf",
                 ".wsh", ".msi", ".msp", ".scr", ".com", ".pif", ".lnk", ".url", ".reg", ".dll",
                 ".sys", ".hta", ".cpl", ".jar", ".sh", ".py", ".pyw", ".appref-ms"}

PRIVATE_IN_HOME = [
    ".ssh", ".gnupg", ".aws", ".azure", ".kube", ".docker", ".git-credentials", ".netrc",
    "AppData/Roaming/Microsoft/Credentials", "AppData/Local/Microsoft/Credentials",
    "AppData/Roaming/Microsoft/Protect", "AppData/Roaming/Microsoft/Crypto",
    "AppData/Local/Microsoft/Vault", "AppData/Roaming/Microsoft/SystemCertificates",
    "AppData/Local/Google/Chrome/User Data", "AppData/Local/Microsoft/Edge/User Data",
    "AppData/Local/BraveSoftware", "AppData/Roaming/Mozilla/Firefox/Profiles",
    "AppData/Roaming/Opera Software", "AppData/Local/Vivaldi/User Data",
    "AppData/Roaming/Bitwarden", "AppData/Local/1Password", "AppData/Roaming/KeePass",
    "AppData/Roaming/discord/Local Storage", "AppData/Roaming/Telegram Desktop/tdata",
    ".config/google-chrome", ".config/chromium", ".mozilla", ".config/BraveSoftware",
    ".local/share/keyrings", ".password-store",
]
READ_ONLY_IN_HOME = [
    "AppData/Roaming/Microsoft/Windows/Start Menu/Programs/Startup",
    ".config/autostart", ".bashrc", ".profile", ".zshrc",
]


def pc_cfg(cfg: dict) -> dict:
    p = cfg.get("pc_access", {}) or {}
    return {"enabled": p.get("enabled", True),
            "roots": [str(r) for r in (p.get("roots") or [])],
            "private": [str(r) for r in (p.get("private") or [])]}


def _under(path: Path, folder: Path) -> bool:
    try:
        return path == folder or path.is_relative_to(folder)
    except ValueError:
        return False


def _norm(p: str | Path) -> Path:
    return Path(os.path.expandvars(str(p).strip().strip('"'))).expanduser().resolve(strict=False)


def default_roots() -> list[Path]:
    if IS_WINDOWS:
        return [Path(f"{d}:\\") for d in string.ascii_uppercase if os.path.exists(f"{d}:\\")]
    return [Path.home()]


class PCPolicy:
    def __init__(self, cfg: dict, corvis_home: Path, data_dir: Path):
        c = pc_cfg(cfg)
        self.enabled = c["enabled"]
        self.roots = [_norm(r) for r in c["roots"]] or default_roots()
        home = Path.home()
        self.private = [_norm(home / p) for p in PRIVATE_IN_HOME] + [_norm(p) for p in c["private"]]
        self.private.append(_norm(Path(data_dir) / "auth.json"))
        self.read_only = [_norm(home / p) for p in READ_ONLY_IN_HOME]
        self.read_only += [_norm(corvis_home), _norm(data_dir)]
        if IS_WINDOWS:
            sysdrive = os.environ.get("SystemDrive", "C:") + "\\"
            for env, fallback in (("SystemRoot", sysdrive + "Windows"),
                                  ("ProgramFiles", sysdrive + "Program Files"),
                                  ("ProgramFiles(x86)", sysdrive + "Program Files (x86)"),
                                  ("ProgramData", sysdrive + "ProgramData")):
                self.read_only.append(_norm(os.environ.get(env, fallback)))
            for name in ("$Recycle.Bin", "System Volume Information", "Recovery", "Boot",
                         "pagefile.sys", "hiberfil.sys", "swapfile.sys"):
                self.private.append(_norm(sysdrive + name))
        else:
            self.read_only += [Path("/etc"), Path("/usr"), Path("/bin"), Path("/sbin"),
                               Path("/boot"), Path("/lib")]

    def resolve(self, path: str | Path) -> Path:
        if not str(path).strip():
            raise PermissionError("Give a full path, like D:/Games/MyGame.")
        return _norm(path)

    def check(self, path: str | Path, action: str = "read") -> Path:
        if not self.enabled:
            raise PermissionError("PC-wide file access is turned off (pc_access.enabled in config.yaml).")
        p = self.resolve(path)
        if not any(_under(p, r) for r in self.roots):
            roots = ", ".join(str(r) for r in self.roots)
            raise PermissionError(f"{p} is outside the folders Corvis may use ({roots}).")
        for blocked in self.private:
            if _under(p, blocked) or (p != blocked and _under(blocked, p) and action != "read"):
                raise PermissionError(f"{p} holds private data (passwords, keys or browser data). "
                                      "Corvis doesn't touch it.")
        if action != "read":
            for ro in self.read_only:
                if _under(p, ro) or (action == "delete" and _under(ro, p)):
                    raise PermissionError(f"{p} is protected (system, startup, or Corvis's own files). "
                                          "Corvis can read it but not change it.")
        return p

    def is_private(self, p: Path) -> bool:
        return any(_under(p, b) for b in self.private)


# --- operations used by the tools and the Files browser ----------------------------
def human_size(n: float) -> str:
    for unit in ("bytes", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{int(n)} bytes" if unit == "bytes" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def list_dir(policy: PCPolicy, path: str = "", show_hidden: bool = False, limit: int = 2000) -> dict:
    """{'path', 'parent', 'entries': [...]}; an empty path lists the roots (drives)."""
    if not str(path).strip():
        return {"path": "", "parent": None, "crumbs": [], "entries": [
            {"name": str(r), "path": str(r), "is_dir": True, "size": None, "modified": None}
            for r in policy.roots]}
    folder = policy.check(path, "read")
    if not folder.is_dir():
        raise NotADirectoryError(f"{folder} isn't a folder.")
    entries = []
    try:
        items = list(os.scandir(folder))
    except PermissionError as e:
        raise PermissionError(f"Windows won't let Corvis open {folder}: {e.strerror}") from e
    for e in items:
        if not show_hidden and (e.name.startswith(".") or e.name.startswith("$")
                                or e.name.lower() in {"desktop.ini", "thumbs.db"}):
            continue
        full = Path(e.path)
        if policy.is_private(_norm(full)):
            continue
        try:
            st = e.stat(follow_symlinks=False)
            is_dir = e.is_dir()
        except OSError:
            continue
        entries.append({"name": e.name, "path": str(full), "is_dir": is_dir,
                        "size": None if is_dir else st.st_size, "modified": st.st_mtime})
        if len(entries) >= limit:
            break
    entries.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))
    parent = None
    if not any(folder == r for r in policy.roots):
        parent = str(folder.parent)
    # Breadcrumbs from the root this folder lives in, e.g. D:\ > Games > MyGame
    root = max((r for r in policy.roots if _under(folder, r)), key=lambda r: len(str(r)))
    crumbs = [{"name": str(root), "path": str(root)}]
    cur = root
    for part in folder.relative_to(root).parts:
        cur = cur / part
        crumbs.append({"name": part, "path": str(cur)})
    return {"path": str(folder), "parent": parent, "entries": entries, "crumbs": crumbs}


def read_text(p: Path, start: int = 0, max_chars: int = 12_000) -> str:
    from .attachments import _docx_text, _pdf_text, _zip_listing, detect_kind

    if p.is_dir():
        raise IsADirectoryError(f"{p} is a folder. Use pc_list to see what's in it.")
    with open(p, "rb") as fh:
        head = fh.read(8192)
    kind, _ = detect_kind(p.name, head)
    if kind == "pdf":
        text = _pdf_text(p)
    elif kind == "docx":
        text = _docx_text(p)
    elif kind == "archive":
        text = _zip_listing(p)
    elif kind == "text":
        if p.stat().st_size > 20_000_000:
            raise ValueError(f"{p.name} is too big to read as text ({human_size(p.stat().st_size)}).")
        raw = p.read_bytes()
        enc = "utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8-sig"
        text = raw.decode(enc, errors="replace")
    else:
        return f"{p.name} is a {kind} file ({human_size(p.stat().st_size)}); it has no text to read."
    start = max(0, int(start))
    piece = text[start:start + max_chars]
    more = (f"\n\n[{len(text) - start - len(piece)} more characters. Read again with start="
            f"{start + len(piece)}.]" if start + len(piece) < len(text) else "")
    return f"{p} (characters {start}-{start + len(piece)} of {len(text)})\n\n{piece}{more}"


def find(policy: PCPolicy, pattern: str, folder: str, limit: int = 200, seconds: float = 15.0) -> list[str]:
    base = policy.check(folder, "read")
    pat = pattern if any(ch in pattern for ch in "*?[") else f"*{pattern}*"
    hits, deadline = [], time.monotonic() + seconds
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in IGNORED_DIRS and not d.startswith(("$", "."))
                       and not policy.is_private(_norm(Path(dirpath) / d))]
        for name in dirnames + filenames:
            if fnmatch.fnmatch(name.lower(), pat.lower()):
                hits.append(str(Path(dirpath) / name) + ("\\" if IS_WINDOWS and name in dirnames else
                                                         "/" if name in dirnames else ""))
                if len(hits) >= limit:
                    return hits
        if time.monotonic() > deadline:
            hits.append(f"... (stopped after {int(seconds)}s; search a smaller folder)")
            break
    return hits


def folder_summary(p: Path, cap: int = 5000) -> str:
    files, total = 0, 0
    for dirpath, _, filenames in os.walk(p):
        for f in filenames:
            files += 1
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
            if files >= cap:
                return f"{cap}+ files, over {human_size(total)}"
    return f"{files} files, {human_size(total)}"


def recycle(p: Path, trash_dir: Path) -> str:
    """Delete to the Recycle Bin (Windows) or Corvis's trash folder (elsewhere)."""
    if IS_WINDOWS:
        script = ("Add-Type -AssemblyName Microsoft.VisualBasic; $p = $env:CORVIS_TARGET; "
                  "if (Test-Path -LiteralPath $p -PathType Container) { "
                  "[Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p, 'OnlyErrorDialogs', 'SendToRecycleBin') } "
                  "else { [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, 'OnlyErrorDialogs', 'SendToRecycleBin') }")
        env = {**os.environ, "CORVIS_TARGET": str(p)}  # passed as data, never pasted into the command
        proc = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
                              env=env, capture_output=True, text=True, timeout=120)
        if proc.returncode != 0 or p.exists():
            raise OSError(f"Couldn't move {p} to the Recycle Bin: {(proc.stderr or proc.stdout).strip()[:300]}")
        return "Recycle Bin"
    trash_dir.mkdir(parents=True, exist_ok=True)
    dest = trash_dir / f"{time.strftime('%Y%m%d-%H%M%S')}-{p.name}"
    shutil.move(str(p), str(dest))
    return str(trash_dir)
