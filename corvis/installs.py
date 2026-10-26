"""Installing software and downloading files.

1. winget first: Windows' own package manager installs from a vetted catalog, without
   clicking through download sites. (Comes with Windows 10/11 as "App Installer".)
2. Otherwise download from the software's official site into Downloads. Running an
   installer is always the owner's call.
"""
from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse

import requests

from . import internet

MAX_DOWNLOAD_BYTES = 8 * 1024**3


def _run(cmd: list[str], timeout: int) -> tuple[int, str]:
    proc = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                          timeout=timeout)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


runner = {"run": _run, "which": shutil.which}  # tests swap these out


def winget_available() -> bool:
    return bool(runner["which"]("winget"))


def parse_winget_table(text: str) -> list[dict]:
    """Read winget's table output (Name / Id / Version / [Match] / Source)."""
    lines = [ln.split("\r")[-1].rstrip() for ln in text.splitlines()]  # drop progress spinners
    for i, line in enumerate(lines):
        if re.match(r"^Name\s+Id\s+Version", line) and i + 1 < len(lines) and set(lines[i + 1].strip()) == {"-"}:
            header, rows = line, lines[i + 2:]
            break
    else:
        return []
    cols = [(m.group(0).strip().lower(), m.start()) for m in re.finditer(r"\S+\s*", header)]
    out = []
    for row in rows:
        if not row.strip():
            continue
        item = {}
        for j, (name, start) in enumerate(cols):
            end = cols[j + 1][1] if j + 1 < len(cols) else None
            item[name] = row[start:end].strip() if end else row[start:].strip()
        if item.get("id"):
            out.append({"name": item.get("name", ""), "id": item["id"],
                        "version": item.get("version", ""), "source": item.get("source", "")})
    return out


def winget_search(query: str, limit: int = 8) -> list[dict]:
    code, out = runner["run"](["winget", "search", "--query", query, "--accept-source-agreements",
                               "--disable-interactivity"], 120)
    results = parse_winget_table(out)
    if not results and code != 0 and "No package found" not in out:
        raise RuntimeError(out.strip()[-400:] or f"winget exited with {code}")
    return results[:limit]


def winget_install(package_id: str) -> str:
    if not re.fullmatch(r"[\w.+-]+", package_id):
        raise ValueError(f"'{package_id}' doesn't look like a winget package id.")
    code, out = runner["run"](["winget", "install", "--id", package_id, "--exact", "--silent",
                               "--accept-package-agreements", "--accept-source-agreements",
                               "--disable-interactivity"], 1800)
    tail = "\n".join(ln.split("\r")[-1] for ln in out.strip().splitlines()[-12:])
    if code != 0:
        raise RuntimeError(f"winget couldn't install {package_id} (exit {code}):\n{tail}")
    return tail


def downloads_folder() -> Path:
    return Path.home() / "Downloads"


def _filename(resp: requests.Response, url: str) -> str:
    cd = resp.headers.get("Content-Disposition", "")
    m = re.search(r"filename\*=UTF-8''([^;]+)", cd) or re.search(r'filename="?([^";]+)"?', cd)
    name = unquote(m.group(1)) if m else unquote(Path(urlparse(url).path).name)
    from .attachments import safe_name
    return safe_name(name or "download")


def download(url: str, folder: Path, cfg: dict, filename: str = "") -> dict:
    """Download a file from the public internet. Returns path, size, sha256, final url."""
    c = internet.internet_cfg(cfg)
    if not c["enabled"]:
        raise internet.WebError("Internet access is turned off in config.yaml.")
    current = internet.check_url(url, c["allow_private"])
    session = requests.Session()
    for _ in range(internet.MAX_REDIRECTS + 1):
        resp = session.get(current, headers={"User-Agent": internet.USER_AGENT}, timeout=60,
                           allow_redirects=False, stream=True)
        if resp.is_redirect or resp.status_code in (301, 302, 303, 307, 308):
            nxt = resp.headers.get("Location")
            resp.close()
            current = internet.check_url(urljoin(current, nxt), c["allow_private"])
            continue
        break
    else:
        raise internet.WebError("Too many redirects.")
    if resp.status_code >= 400:
        resp.close()
        raise internet.WebError(f"{current} returned HTTP {resp.status_code}.")
    if "text/html" in resp.headers.get("Content-Type", "") and not filename.lower().endswith((".html", ".htm")):
        resp.close()
        raise internet.WebError("That link is a web page, not a file. Find the direct download link "
                                "(read the page with fetch_page first).")
    name = filename or _filename(resp, current)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / name
    n = 1
    while dest.exists():
        dest = folder / f"{Path(name).stem} ({n}){Path(name).suffix}"
        n += 1
    sha, size = hashlib.sha256(), 0
    part = dest.with_name(dest.name + ".part")
    try:
        with open(part, "wb") as fh:
            for chunk in resp.iter_content(1 << 20):
                size += len(chunk)
                if size > MAX_DOWNLOAD_BYTES:
                    raise internet.WebError("Download is over 8 GB; stopped.")
                sha.update(chunk)
                fh.write(chunk)
        part.replace(dest)
    finally:
        resp.close()
        if part.exists():
            part.unlink()
    return {"path": str(dest), "size": size, "sha256": sha.hexdigest(), "url": current,
            "site": urlparse(current).hostname or ""}
