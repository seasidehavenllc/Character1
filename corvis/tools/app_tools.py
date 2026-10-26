"""App tools: open/close apps and games, open files and links, install software, download files."""
from __future__ import annotations

import webbrowser
from pathlib import Path

from .. import apps, installs, internet, pc
from .base import Tool, ToolContext, ToolRegistry, params


def apps_cfg(cfg: dict) -> dict:
    a = cfg.get("apps", {}) or {}
    return {"enabled": a.get("enabled", True), "installs": a.get("allow_installs", True)}


def register(reg: ToolRegistry, ctx: ToolContext) -> None:
    acfg = apps_cfg(ctx.config)
    if not acfg["enabled"]:
        return
    index: apps.AppIndex = ctx.state.get("app_index") or apps.AppIndex()
    policy: pc.PCPolicy | None = ctx.state.get("pc_policy")

    def resolve_path(path: str) -> Path:
        if policy is not None and policy.enabled:
            return policy.check(path, "read")
        return ctx.workspace.resolve(path)

    def find_app(name: str) -> str:
        hits = index.find(name)
        if not hits:
            return f"No installed app matches '{name}'."
        return "\n".join(f"- {a.name} ({'Steam game' if a.kind == 'steam' else a.kind})" for _, a in hits)

    def open_app(name: str, file_or_folder: str = "") -> str:
        hits = index.find(name)
        if not hits:
            return (f"ERROR: couldn't find an app called '{name}'. Use find_app to look, or "
                    "search_installable if it isn't installed.")
        best = hits[0][1]
        if hits[0][0] < 75 and len(hits) > 1:
            options = ", ".join(a.name for _, a in hits)
            return f"ERROR: not sure which app you mean: {options}. Call open_app with the exact name."
        path = ""
        if file_or_folder:
            path = str(resolve_path(file_or_folder))
        return apps.launch(best, path)

    def list_open_apps() -> str:
        wins = apps.open_windows()
        if not wins:
            return "No app windows are open."
        return "\n".join(f"- {w['name']} (pid {w['pid']}): {w['title']}" for w in wins)

    def close_app(name: str, force: bool = False) -> str:
        wins = apps.match_windows(name, apps.open_windows())
        if not wins:
            return f"ERROR: no open app matches '{name}'. Use list_open_apps to see what's open."
        listing = "\n".join(f"- {w['name']}: {w['title']}" for w in wins)
        warn = ("FORCE close (any unsaved work is lost)" if force
                else "Close (like clicking X; it may ask to save)")
        if not ctx.approver(f"{warn}:\n{listing}"):
            return "The owner declined closing it."
        return apps.close(wins, force)

    def open_path(path: str) -> str:
        p = resolve_path(path)
        if not p.exists():
            return f"ERROR: {p} doesn't exist."
        if p.suffix.lower() in pc.RUNNABLE_EXTS and not p.is_dir():
            if not ctx.approver(f"Run this program? Only allow it if you trust where it came from.\n{p}"):
                return "The owner declined running it."
        apps.launcher["startfile"](str(p))
        return f"Opened {p}."

    def open_url(url: str) -> str:
        if not url.lower().startswith(("http://", "https://")):
            return "ERROR: only http:// and https:// links can be opened."
        webbrowser.open(url)
        return f"Opened {url} in the browser."

    reg.register(Tool("find_app", "Find installed apps and Steam games by name.",
                      params(["name"], name={"type": "string"}), find_app))
    reg.register(Tool("open_app", "Open an app or game on the PC by name (Start Menu apps, Steam games, "
                      "VS Code...). Optionally open a file or folder in it, e.g. "
                      "open_app('Visual Studio Code', 'D:/Games/MyGame').",
                      params(["name"], name={"type": "string"}, file_or_folder={"type": "string"}), open_app))
    reg.register(Tool("list_open_apps", "List apps that currently have a window open on the PC.",
                      params([]), list_open_apps))
    reg.register(Tool("close_app", "Close an open app (the owner approves). force=true kills it without "
                      "letting it save.", params(["name"], name={"type": "string"}, force={"type": "boolean"}),
                      close_app))
    reg.register(Tool("open_path", "Open a file or folder on the PC with its default app (folders open in "
                      "File Explorer). Running programs/installers needs the owner's OK.",
                      params(["path"], path={"type": "string"}), open_path))
    reg.register(Tool("open_url", "Open a web page in the owner's browser so they can see it.",
                      params(["url"], url={"type": "string"}), open_url))

    if not acfg["installs"]:
        return

    def search_installable(query: str) -> str:
        if not installs.winget_available():
            return ("winget isn't available on this PC (it comes with Windows 10/11 as 'App Installer' "
                    "from the Microsoft Store). Use web_search to find the official site instead.")
        try:
            found = installs.winget_search(query)
        except Exception as e:
            return f"ERROR: winget search failed: {e}"
        if not found:
            return f"winget has nothing for '{query}'. Find the official site with web_search instead."
        return "Installable with winget:\n" + "\n".join(
            f"- {r['name']}  id={r['id']}  version {r['version']}  ({r['source']})" for r in found)

    def install_app(package_id: str) -> str:
        if not installs.winget_available():
            return "ERROR: winget isn't available on this PC."
        if not ctx.approver(f"Install this program with winget (Windows' package manager)?\n{package_id}"):
            return "The owner declined installing it."
        try:
            return f"Installed {package_id}.\n{installs.winget_install(package_id)}"
        except Exception as e:
            return f"ERROR: {e}"

    def download_file(url: str, folder: str = "", filename: str = "") -> str:
        target = Path(folder) if folder else installs.downloads_folder()
        if policy is not None and policy.enabled:
            target = policy.check(target, "write")
        try:
            info = installs.download(url, target, ctx.config, filename)
        except internet.WebError as e:
            return f"ERROR: {e}"
        note = ""
        if Path(info["path"]).suffix.lower() in pc.RUNNABLE_EXTS:
            note = ("\nThis is a program/installer. Use open_path to run it; the owner will be asked. "
                    f"It came from {info['site']}; tell the owner that.")
        return (f"Downloaded {info['path']} ({pc.human_size(info['size'])}) from {info['site']}.\n"
                f"SHA-256: {info['sha256']}{note}")

    reg.register(Tool("search_installable", "Search winget (Windows' official app catalog) for software to "
                      "install. Try this before downloading installers from websites.",
                      params(["query"], query={"type": "string"}), search_installable))
    reg.register(Tool("install_app", "Install software with winget by its exact package id from "
                      "search_installable. The owner approves.",
                      params(["package_id"], package_id={"type": "string"}), install_app))
    reg.register(Tool("download_file", "Download a file from a public website (default: the owner's "
                      "Downloads folder). Only use official sites.",
                      params(["url"], url={"type": "string"}, folder={"type": "string"},
                             filename={"type": "string"}), download_file))
