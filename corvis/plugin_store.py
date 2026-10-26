"""Plugins: installable bundles of skills, slash commands, connectors and tools.

The layout follows Claude Code plugins, so many of those install unchanged:

    my-plugin/
      .claude-plugin/plugin.json   (or .corvis-plugin/plugin.json, or plugin.json)
                                   {"name": "my-plugin", "version": "1.0.0", "description": "..."}
      skills/<skill>/SKILL.md      expert instructions, loaded when relevant (front matter: name, description)
      commands/<command>.md        a slash command: "/command words" runs this prompt ($ARGUMENTS = the words)
      .mcp.json                    connectors: {"mcpServers": {"name": {"command": ..., "args": [...]}}}
      tools/*.py                   Corvis tools: register(reg, ctx), like corvis/plugins/

Plugins install from a Git repository, a folder, or a .zip, or from a marketplace (a Git
repository with .claude-plugin/marketplace.json listing plugins). Plugins with tools/*.py run
code on this machine, so installing one needs the owner's explicit OK. Stored in data/plugins/.
"""
from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import threading
import time
import zipfile
from pathlib import Path

import yaml

MANIFESTS = (".claude-plugin/plugin.json", ".corvis-plugin/plugin.json", "plugin.json")
MARKETPLACE_FILES = (".claude-plugin/marketplace.json", ".corvis-plugin/marketplace.json", "marketplace.json")
NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")
MAX_BYTES = 50 * 1024 * 1024
MAX_FILES = 5000
GIT_URL = re.compile(r"^(https://[\w.-]+/[\w./~-]+?)(\.git)?/?$")


class PluginError(ValueError):
    pass


class NeedsCodeApproval(PluginError):
    """The plugin runs Python code on this machine; the owner has to say yes first."""


def front_matter(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        parts = text.split("---", 2)
        if len(parts) == 3:
            try:
                meta = yaml.safe_load(parts[1]) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), parts[2].lstrip("\n")
    return {}, text


def read_manifest(folder: Path) -> dict:
    for rel in MANIFESTS:
        p = folder / rel
        if p.is_file():
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as e:
                raise PluginError(f"{rel} isn't valid JSON: {e}") from e
            name = str(data.get("name") or "").strip().lower()
            if not NAME.match(name):
                raise PluginError(f"Plugin name '{name}' must be lowercase letters, digits and dashes.")
            return {**data, "name": name}
    raise PluginError("This isn't a plugin: no plugin.json (looked in .claude-plugin/ and the top folder).")


def _check_tree(folder: Path) -> None:
    total, count = 0, 0
    for p in folder.rglob("*"):
        if p.is_symlink():
            raise PluginError(f"Plugins can't contain links ({p.relative_to(folder)}).")
        if p.is_file():
            count += 1
            total += p.stat().st_size
    if count > MAX_FILES or total > MAX_BYTES:
        raise PluginError("That plugin is too big (over 50 MB or 5,000 files).")


def git_url(source: str) -> str | None:
    """A Git address, from a full URL or GitHub shorthand like owner/repo."""
    source = source.strip()
    if re.fullmatch(r"[\w.-]+/[\w.-]+", source):
        return f"https://github.com/{source}.git"
    m = GIT_URL.match(source)
    return m.group(1) + ".git" if m else None


def clone(url: str, dest: Path) -> None:
    if not shutil.which("git"):
        raise PluginError("Installing from Git needs Git (git-scm.com).")
    try:
        subprocess.run(["git", "clone", "--depth", "1", "--", url, str(dest)], capture_output=True, text=True,
                       timeout=180, check=True, env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    except subprocess.CalledProcessError as e:
        raise PluginError(f"Couldn't download {url}: {(e.stderr or e.stdout).strip()[-300:]}") from e
    except subprocess.TimeoutExpired as e:
        raise PluginError("Downloading the plugin took too long.") from e


def extract_zip(data: bytes, dest: Path) -> Path:
    try:
        zf = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as e:
        raise PluginError("That file isn't a valid .zip.") from e
    infos = zf.infolist()
    if len(infos) > MAX_FILES or sum(i.file_size for i in infos) > MAX_BYTES:
        raise PluginError("That plugin is too big (over 50 MB or 5,000 files).")
    root = dest.resolve()
    for info in infos:
        target = (dest / info.filename).resolve()
        if target != root and root not in target.parents:
            raise PluginError(f"Unsafe path in zip: {info.filename}")
        if (info.external_attr >> 16) & 0o170000 == 0o120000:
            raise PluginError("Plugins can't contain links.")
    zf.extractall(dest)
    tops = [p for p in dest.iterdir() if not p.name.startswith("__MACOSX")]
    if len(tops) == 1 and tops[0].is_dir() and not any((dest / m).is_file() for m in MANIFESTS):
        return tops[0]   # zipped as one top folder
    return dest


class PluginStore:
    def __init__(self, data_dir: str | Path):
        self.data_dir = Path(data_dir)
        self.root = self.data_dir / "plugins"
        self.markets_root = self.data_dir / "marketplaces"
        self.state_path = self.data_dir / "plugins.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    # --- state -------------------------------------------------------------------------
    def _state(self) -> dict:
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, data: dict) -> None:
        tmp = self.state_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1), encoding="utf-8")
        os.replace(tmp, self.state_path)

    def _plugins(self) -> dict:
        return self._state().get("plugins", {})

    # --- installing --------------------------------------------------------------------
    def install(self, source: str = "", zip_bytes: bytes | None = None, allow_code: bool = False,
                label: str = "") -> dict:
        """Install (or update) from a Git address, a folder on this machine, or zip bytes."""
        with tempfile.TemporaryDirectory(prefix="corvis-plugin-") as tmp:
            tmp_path = Path(tmp)
            if zip_bytes is not None:
                folder = extract_zip(zip_bytes, tmp_path / "x")
                label = label or "uploaded .zip"
            elif (url := git_url(source)) and not Path(source).expanduser().exists():
                clone(url, tmp_path / "repo")
                folder, label = tmp_path / "repo", label or url
            else:
                folder = Path(source).expanduser()
                if not folder.is_dir():
                    raise PluginError("Give a Git address (like github.com/owner/repo), a folder, or a .zip.")
                label = label or str(folder)
            return self._install_folder(folder, label, allow_code)

    def _install_folder(self, folder: Path, label: str, allow_code: bool) -> dict:
        manifest = read_manifest(folder)
        _check_tree(folder)
        name = manifest["name"]
        code = sorted(p.name for p in (folder / "tools").glob("*.py")) if (folder / "tools").is_dir() else []
        if code and not allow_code:
            raise NeedsCodeApproval(
                f"'{name}' includes Python code ({', '.join(code)}) that will run on this computer "
                "with Corvis's permissions. Install it only if you trust where it came from.")
        dest = self.root / name
        with self._lock:
            if dest.exists():
                shutil.rmtree(dest)
            shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(".git"))
            state = self._state()
            prev = state.get("plugins", {}).get(name, {})
            state.setdefault("plugins", {})[name] = {
                "enabled": prev.get("enabled", True), "source": label, "installed": time.time(),
                "version": str(manifest.get("version") or ""), "code_ok": bool(code)}
            self._save(state)
        return self.describe(name)

    def set_enabled(self, name: str, enabled: bool) -> dict:
        with self._lock:
            state = self._state()
            if name not in state.get("plugins", {}):
                raise KeyError(name)
            state["plugins"][name]["enabled"] = bool(enabled)
            self._save(state)
        return self.describe(name)

    def remove(self, name: str) -> None:
        with self._lock:
            state = self._state()
            if state.get("plugins", {}).pop(name, None) is None:
                raise KeyError(name)
            shutil.rmtree(self.root / name, ignore_errors=True)
            self._save(state)

    # --- reading -----------------------------------------------------------------------
    def enabled(self) -> list[str]:
        return [n for n, p in self._plugins().items() if p.get("enabled") and (self.root / n).is_dir()]

    def describe(self, name: str) -> dict:
        info = self._plugins()[name]
        folder = self.root / name
        try:
            manifest = read_manifest(folder)
        except PluginError:
            manifest = {"name": name}
        author = manifest.get("author")
        return {
            "name": name, "version": info.get("version") or manifest.get("version") or "",
            "description": str(manifest.get("description") or ""),
            "author": author.get("name") if isinstance(author, dict) else (author or ""),
            "enabled": bool(info.get("enabled")), "source": info.get("source", ""),
            "installed": info.get("installed"),
            "skills": [s["name"] for s in self._skills(name)],
            "commands": [c["name"] for c in self._commands(name)],
            "connectors": [c["name"] for c in self._connectors(name)],
            "tools": sorted(p.stem for p in (folder / "tools").glob("*.py")) if (folder / "tools").is_dir() else [],
        }

    def list(self) -> list[dict]:
        return [self.describe(n) for n in sorted(self._plugins()) if (self.root / n).is_dir()]

    def _skills(self, name: str) -> list[dict]:
        out = []
        for md in sorted((self.root / name / "skills").glob("*/SKILL.md")):
            meta, body = front_matter(md.read_text(encoding="utf-8", errors="replace"))
            out.append({"name": str(meta.get("name") or md.parent.name), "plugin": name,
                        "description": str(meta.get("description") or "")[:500], "body": body,
                        "folder": md.parent})
        return out

    def skills(self) -> list[dict]:
        return [s for n in self.enabled() for s in self._skills(n)]

    def _commands(self, name: str) -> list[dict]:
        out = []
        for md in sorted((self.root / name / "commands").glob("*.md")):
            meta, body = front_matter(md.read_text(encoding="utf-8", errors="replace"))
            out.append({"name": md.stem.lower(), "plugin": name, "body": body,
                        "description": str(meta.get("description") or "")[:300],
                        "hint": str(meta.get("argument-hint") or "")})
        return out

    def commands(self) -> list[dict]:
        seen, out = set(), []
        for n in self.enabled():
            for c in self._commands(n):
                if c["name"] not in seen:
                    seen.add(c["name"])
                    out.append(c)
        return out

    def expand_command(self, text: str) -> str | None:
        """'/name words' -> the command's prompt with $ARGUMENTS filled in (None if not a command)."""
        m = re.match(r"^/([a-z0-9][a-z0-9_-]*)(?:\s+(.*))?$", text.strip(), re.S)
        if not m:
            return None
        cmd = next((c for c in self.commands() if c["name"] == m.group(1).lower()), None)
        if cmd is None:
            return None
        args = (m.group(2) or "").strip()
        words = args.split()
        body = cmd["body"].replace("$ARGUMENTS", args)
        body = re.sub(r"\$(\d)", lambda k: words[int(k.group(1)) - 1] if 0 < int(k.group(1)) <= len(words) else "",
                      body)
        return f"(The owner ran /{cmd['name']} from the {cmd['plugin']} plugin.)\n\n{body.strip()}"

    def _connectors(self, name: str) -> list[dict]:
        from .connectors import validate

        path = self.root / name / ".mcp.json"
        if not path.is_file():
            return []
        try:
            servers = json.loads(path.read_text(encoding="utf-8")).get("mcpServers") or {}
        except (OSError, json.JSONDecodeError, AttributeError):
            return []
        root = str((self.root / name).resolve())
        out = []
        for sname, spec in servers.items():
            if not isinstance(spec, dict):
                continue
            spec = json.loads(json.dumps(spec).replace("${CLAUDE_PLUGIN_ROOT}", root.replace("\\", "\\\\"))
                              .replace("${CORVIS_PLUGIN_ROOT}", root.replace("\\", "\\\\")))
            kind = "http" if spec.get("url") else "stdio"
            if spec.get("type") == "sse":
                continue  # the old SSE transport isn't supported; Streamable HTTP is
            try:
                conn = validate({"name": f"{sname}", "slug": f"{name}_{sname}", "kind": kind,
                                 "url": spec.get("url"), "headers": spec.get("headers"),
                                 "command": spec.get("command"), "args": spec.get("args"),
                                 "env": spec.get("env"), "cwd": root}, source=f"plugin:{name}")
            except ValueError:
                continue
            conn["id"] = f"plg-{name}-{re.sub(r'[^a-z0-9-]', '-', sname.lower())}"[:60]
            out.append(conn)
        return out

    def connectors(self) -> list[dict]:
        return [c for n in self.enabled() for c in self._connectors(n)]

    def load_tools(self, reg, ctx) -> list[str]:
        """Run each enabled plugin's tools/*.py register(); a broken one is reported, not fatal."""
        errors = []
        state = self._plugins()
        for name in self.enabled():
            if not state[name].get("code_ok"):
                continue
            for py in sorted((self.root / name / "tools").glob("*.py")):
                mod_name = f"corvis_plugin_{name.replace('-', '_')}_{py.stem}"
                try:
                    spec = importlib.util.spec_from_file_location(mod_name, py)
                    mod = importlib.util.module_from_spec(spec)
                    spec.loader.exec_module(mod)
                    if hasattr(mod, "register"):
                        mod.register(reg, ctx)
                except Exception as e:
                    errors.append(f"Plugin '{name}' tool {py.name} failed to load: {type(e).__name__}: {e}")
        return errors

    # --- marketplaces ------------------------------------------------------------------
    def markets(self) -> dict:
        return self._state().get("marketplaces", {})

    def add_marketplace(self, source: str = "", folder: Path | None = None) -> dict:
        """Add a marketplace from a Git address (or, for testing, a local folder)."""
        tmp = Path(tempfile.mkdtemp(prefix="corvis-market-"))
        try:
            if folder is None and source and Path(source).expanduser().is_dir():
                folder = Path(source).expanduser()
            if folder is None:
                url = git_url(source)
                if not url:
                    raise PluginError("Give the marketplace's Git address, like github.com/owner/plugins.")
                clone(url, tmp / "repo")
                folder = tmp / "repo"
            market = self._read_market(folder)
            name = re.sub(r"[^a-z0-9-]", "-", str(market.get("name") or folder.name).lower())[:64].strip("-")
            dest = self.markets_root / name
            self.markets_root.mkdir(parents=True, exist_ok=True)
            with self._lock:
                if dest.exists():
                    shutil.rmtree(dest)
                shutil.copytree(folder, dest, ignore=shutil.ignore_patterns(".git"))
                state = self._state()
                state.setdefault("marketplaces", {})[name] = {"source": source or str(folder), "added": time.time()}
                self._save(state)
            return {"name": name, "plugins": self.market_plugins(name)}
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def remove_marketplace(self, name: str) -> None:
        with self._lock:
            state = self._state()
            if state.get("marketplaces", {}).pop(name, None) is None:
                raise KeyError(name)
            shutil.rmtree(self.markets_root / name, ignore_errors=True)
            self._save(state)

    @staticmethod
    def _read_market(folder: Path) -> dict:
        for rel in MARKETPLACE_FILES:
            p = folder / rel
            if p.is_file():
                try:
                    data = json.loads(p.read_text(encoding="utf-8"))
                except json.JSONDecodeError as e:
                    raise PluginError(f"{rel} isn't valid JSON: {e}") from e
                if not isinstance(data.get("plugins"), list):
                    raise PluginError(f"{rel} has no plugins list.")
                return data
        raise PluginError("No marketplace.json found (looked in .claude-plugin/ and the top folder).")

    def market_plugins(self, market: str) -> list[dict]:
        data = self._read_market(self.markets_root / market)
        installed = self._plugins()
        out = []
        for p in data["plugins"]:
            if not isinstance(p, dict) or not p.get("name"):
                continue
            out.append({"name": str(p["name"]), "description": str(p.get("description") or "")[:400],
                        "version": str(p.get("version") or ""), "market": market,
                        "installed": str(p["name"]).lower() in installed})
        return out

    def install_from_market(self, market: str, plugin: str, allow_code: bool = False) -> dict:
        folder = self.markets_root / market
        data = self._read_market(folder)
        entry = next((p for p in data["plugins"] if isinstance(p, dict) and p.get("name") == plugin), None)
        if entry is None:
            raise PluginError(f"'{plugin}' isn't in the {market} marketplace.")
        src = entry.get("source") or f"./{plugin}"
        label = f"{market} marketplace"
        if isinstance(src, str) and src.startswith("./"):
            target = (folder / src).resolve()
            if folder.resolve() not in target.parents and target != folder.resolve():
                raise PluginError("That marketplace entry points outside the marketplace.")
            return self._install_folder(target, label, allow_code)
        if isinstance(src, dict):
            src = src.get("url") or (src.get("repo") and f"https://github.com/{src['repo']}.git") or ""
        return self.install(str(src), allow_code=allow_code, label=label)
