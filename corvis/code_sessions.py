"""Code sessions, like Claude Code: a chat tied to one repo folder, with its changes tracked.

Starting a session notes where the repo was (the base commit) and, if the owner asks,
moves the work onto a fresh branch so it stays separate. While Corvis works, the app can show
every file he changed as a diff against that base, and the owner can commit the result.

Git is run directly (no shell) and only on the session's own folder.
"""
from __future__ import annotations

import re
import subprocess
import uuid
from pathlib import Path

EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"   # git's id for "no files at all"
MAX_PATCH = 80_000        # characters of diff shown per file
MAX_TOTAL = 600_000
MAX_NEW_FILE = 200_000    # bytes of an untracked file turned into a diff


def git(folder: str | Path, *args: str, timeout: int = 30) -> tuple[int, str]:
    try:
        p = subprocess.run(["git", "-c", "core.quotepath=off", "--no-pager", *args], cwd=str(folder),
                           capture_output=True, text=True, timeout=timeout, encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return 127, "Git isn't installed on this computer."
    except subprocess.TimeoutExpired:
        return 124, "Git took too long."
    return p.returncode, (p.stdout if p.returncode == 0 else (p.stderr or p.stdout)).strip("\n")


def is_repo(folder: str | Path) -> bool:
    code, out = git(folder, "rev-parse", "--show-toplevel")
    return code == 0 and Path(out).resolve() == Path(folder).resolve()


def current_branch(folder: str | Path) -> str | None:
    code, out = git(folder, "branch", "--show-current")
    return out or None if code == 0 else None


def head(folder: str | Path) -> str | None:
    code, out = git(folder, "rev-parse", "HEAD")
    return out if code == 0 else None


def slug(text: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:32].strip("-")
    return s or "session"


def start(folder: str | Path, title: str = "", new_branch: bool = False) -> dict:
    """What the session remembers about its repo. Never fails: a non-Git folder just isn't tracked."""
    folder = Path(folder)
    info = {"repo": folder.name, "git": is_repo(folder), "base": None, "branch": None, "made_branch": False,
            "note": ""}
    if not info["git"]:
        info["note"] = "This folder isn't a Git repository, so changes can't be shown as diffs."
        return info
    info["base"] = head(folder)
    info["branch"] = current_branch(folder)
    if new_branch:
        name = f"corvis/{slug(title)}-{uuid.uuid4().hex[:4]}"
        code, out = git(folder, "switch", "-c", name)
        if code == 0:
            info["branch"], info["made_branch"] = name, True
        else:
            info["note"] = f"Couldn't make a new branch, so Corvis is working on {info['branch']}: {out}"
    return info


def _is_binary(path: Path) -> bool:
    try:
        return b"\0" in path.read_bytes()[:8000]
    except OSError:
        return True


def diff(folder: str | Path, info: dict) -> dict:
    """Every change since the session started: committed or not, plus new files."""
    folder = Path(folder)
    if not info.get("git") or not is_repo(folder):
        return {"git": False, "files": [], "added": 0, "removed": 0, "note": info.get("note") or "Not a Git repository."}
    base = info.get("base") or EMPTY_TREE
    files: dict[str, dict] = {}
    code, out = git(folder, "diff", "--numstat", "-M", base)
    if code != 0:
        return {"git": True, "files": [], "added": 0, "removed": 0, "note": out}
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        a, r, path = parts[0], parts[1], parts[-1]
        files[path] = {"path": path, "added": int(a) if a.isdigit() else 0, "removed": int(r) if r.isdigit() else 0,
                       "binary": a == "-", "status": "modified", "patch": ""}
    code, out = git(folder, "diff", "--name-status", "-M", base)
    for line in out.splitlines() if code == 0 else []:
        parts = line.split("\t")
        if len(parts) >= 2 and parts[-1] in files:
            files[parts[-1]]["status"] = {"A": "added", "D": "deleted", "R": "renamed"}.get(parts[0][:1], "modified")
    total = 0
    for path, f in files.items():
        if f["binary"] or total > MAX_TOTAL:
            continue
        code, patch = git(folder, "diff", "--no-color", "-M", base, "--", path)
        if code == 0:
            f["patch"] = patch[:MAX_PATCH] + ("\n… (diff cut short)" if len(patch) > MAX_PATCH else "")
            total += len(f["patch"])
    code, out = git(folder, "ls-files", "--others", "--exclude-standard")
    for path in (out.splitlines() if code == 0 else [])[:200]:
        p = folder / path
        if not p.is_file():
            continue
        f = {"path": path, "status": "added", "binary": _is_binary(p), "removed": 0, "patch": "", "added": 0}
        if not f["binary"] and p.stat().st_size <= MAX_NEW_FILE:
            lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
            f["added"] = len(lines)
            if total <= MAX_TOTAL:
                body = "\n".join("+" + ln for ln in lines)
                f["patch"] = (f"new file\n@@ -0,0 +1,{len(lines)} @@\n" + body)[:MAX_PATCH]
                total += len(f["patch"])
        files[path] = f
    items = sorted(files.values(), key=lambda f: f["path"])
    return {"git": True, "files": items, "added": sum(f["added"] for f in items),
            "removed": sum(f["removed"] for f in items), "branch": current_branch(folder), "base": info.get("base"),
            "note": info.get("note", "")}


def stat(folder: str | Path, info: dict) -> dict:
    """Just the totals, for the session list."""
    if not info.get("git"):
        return {"files": 0, "added": 0, "removed": 0}
    code, out = git(folder, "diff", "--numstat", info.get("base") or EMPTY_TREE, timeout=10)
    added = removed = n = 0
    for line in out.splitlines() if code == 0 else []:
        a, r, *_ = line.split("\t") + ["", ""]
        added += int(a) if a.isdigit() else 0
        removed += int(r) if r.isdigit() else 0
        n += 1
    code, out = git(folder, "ls-files", "--others", "--exclude-standard", timeout=10)
    for path in (out.splitlines() if code == 0 and out else [])[:200]:
        p = Path(folder) / path
        n += 1
        if p.is_file() and p.stat().st_size <= MAX_NEW_FILE and not _is_binary(p):
            added += len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    return {"files": n, "added": added, "removed": removed}


def commit(folder: str | Path, message: str) -> str:
    message = str(message or "").strip()
    if not message:
        raise ValueError("Write a commit message first.")
    code, out = git(folder, "add", "-A")
    if code != 0:
        raise ValueError(f"git add failed: {out}")
    code, out = git(folder, "commit", "-m", message[:2000])
    if code != 0:
        raise ValueError(out or "Nothing to commit.")
    return out.splitlines()[0] if out else "Committed."
