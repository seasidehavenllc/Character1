"""Finding blueprints online: "Corvis, pull up the Eiffel Tower."

Looks for real, downloadable 3D models in places that allow it:
- Wikimedia Commons (community-made STL models with clear licences; no key needed)
- NASA 3D Resources (official NASA models of spacecraft, rovers and more)
- a general web search for direct model links (.stl, .obj, .glb, .3mf, .ply, .zip)

Corvis is honest about what he finds. Every result says where it came from and whether it's
official or community-made. Real engineering drawings of military or secret designs are
classified, and car makers and other companies don't publish their factory CAD; when that
applies he says so instead of pretending a hobby model is the real thing. If nothing can be
downloaded, he says that too. He won't fetch printable weapon parts.
"""
from __future__ import annotations

import json
import re
import time
from html import unescape
from pathlib import Path
from urllib.parse import quote, urljoin, urlparse

import requests

from .internet import WebError, check_url, internet_cfg, search as web_search
from .meshes import FORMATS as MODEL_FORMATS, MAX_BYTES

USER_AGENT = "Corvis/2.0 (personal assistant; fetches openly licensed 3D models for its owner) python-requests"
TIMEOUT = 25
NASA_TREE = "https://api.github.com/repos/nasa/NASA-3D-Resources/git/trees/master?recursive=1"
NASA_RAW = "https://raw.githubusercontent.com/nasa/NASA-3D-Resources/master/"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"
MODEL_EXT = tuple(f".{f}" for f in MODEL_FORMATS if f != "gltf") + (".zip",)

WEAPONS = re.compile(r"\b(fire ?arms?|hand ?guns?|pistols?|rifles?|shot ?guns?|revolvers?|lower receivers?|receivers?|"
                     r"ar-?15|ak-?47|glock|ghost guns?|suppressors?|silencers?|bump stocks?|auto ?sears?|bombs?|"
                     r"explosives?|grenades?|detonators?|warheads?|ied)\b", re.I)
HARMLESS_GUNS = re.compile(r"\b(nerf|glue|heat|staple|nail|caulk|spray|water|toy|ray|laser|paint|grease|massage|"
                           r"bubble|foam|cosplay|prop)\b", re.I)
GUN = re.compile(r"\bguns?\b", re.I)
CLASSIFIED = re.compile(r"\b(f-?35|f-?22|b-?2|b-?21|sr-?71|sr-?72|stealth|nuclear|icbm|hypersonic|ballistic missile|"
                        r"cruise missile|submarine reactor|aircraft carrier|area 51|nsa|military satellite|spy satellite|"
                        r"railgun|drone strike|predator drone|reaper drone|tank armou?r|abrams|patriot missile)\b", re.I)
BRANDS = re.compile(r"\b(lamborghini|ferrari|porsche|bugatti|mclaren|tesla|bmw|mercedes|audi|ford|chevrolet|toyota|honda|"
                    r"apple|iphone|ipad|samsung|playstation|xbox|boeing|airbus|spacex|blue origin|rolex|dyson|lego)\b", re.I)


def assess(query: str) -> dict:
    """What Corvis must say up front about a request, before searching."""
    q = " ".join(query.split())
    gun = GUN.search(q) and not HARMLESS_GUNS.search(q)
    if (WEAPONS.search(q) and not HARMLESS_GUNS.search(q)) or gun:
        return {"blocked": "I won't look for or pull in printable weapons or weapon parts. That's a hard line for me. "
                           "I'm happy to help with a prop that clearly can't work, or anything else."}
    notes = []
    m = CLASSIFIED.search(q)
    if m:
        notes.append(f"Classified: the real engineering blueprints for {m.group(0)} designs are classified or "
                     "export-controlled, so they aren't available to anyone outside the programme. Anything I find "
                     "is a public, outside-shape model made by hobbyists, and I'll label it that way.")
    m = BRANDS.search(q)
    if m:
        notes.append(f"{m.group(0).title()} doesn't publish its factory CAD, so the real engineering drawings aren't "
                     "available. What exists publicly are community-made models of the outside shape; I'll say so "
                     "on anything I pull up.")
    return {"blocked": None, "notes": notes}


def _strip_html(s: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s or "")).split())


def _get(url: str, **kw) -> requests.Response:
    r = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, **kw)
    if r.status_code == 429:
        raise WebError(f"{urlparse(url).hostname} is rate-limiting right now. Try again in a minute.")
    r.raise_for_status()
    return r


def search_commons(query: str, limit: int = 8) -> list[dict]:
    params = {"action": "query", "format": "json", "generator": "search", "gsrnamespace": 6, "gsrlimit": limit,
              "gsrsearch": f"filemime:application/sla {query}", "prop": "imageinfo",
              "iiprop": "url|size|mime|extmetadata", "iiextmetadatafilter": "LicenseShortName|Artist|ObjectName"}
    try:
        data = _get(COMMONS_API, params=params).json()
    except (requests.RequestException, ValueError) as e:
        raise WebError(f"Wikimedia Commons didn't answer: {e}") from e
    out = []
    pages = sorted((data.get("query") or {}).get("pages", {}).values(), key=lambda p: p.get("index", 99))
    for p in pages:
        info = (p.get("imageinfo") or [{}])[0]
        meta = info.get("extmetadata") or {}
        if not info.get("url"):
            continue
        out.append({"title": p["title"].removeprefix("File:").rsplit(".", 1)[0], "url": info["url"],
                    "page": info.get("descriptionurl", ""), "site": "Wikimedia Commons", "format": "stl",
                    "size": info.get("size", 0), "kind": "community",
                    "license": _strip_html((meta.get("LicenseShortName") or {}).get("value", "")),
                    "author": _strip_html((meta.get("Artist") or {}).get("value", ""))[:120]})
    return out


def _nasa_index(cache_dir: Path) -> list[str]:
    cache = cache_dir / "nasa_models.json"
    try:
        if time.time() - cache.stat().st_mtime < 7 * 86400:
            return json.loads(cache.read_text(encoding="utf-8"))
    except OSError:
        pass
    try:
        tree = _get(NASA_TREE).json().get("tree", [])
    except (requests.RequestException, ValueError) as e:
        raise WebError(f"NASA's model library didn't answer: {e}") from e
    paths = [t["path"] for t in tree if t.get("type") == "blob" and t["path"].lower().endswith(MODEL_EXT)
             and t["path"].startswith("3D Models/")]
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache.write_text(json.dumps(paths), encoding="utf-8")
    return paths


def search_nasa(query: str, cache_dir: Path, limit: int = 6) -> list[dict]:
    words = [w for w in re.findall(r"[a-z0-9]+", query.lower()) if len(w) > 2 and w not in {"the", "nasa", "model", "blueprint"}]
    if not words:
        return []
    best: dict[str, tuple[int, str]] = {}
    pref = {".glb": 5, ".stl": 4, ".obj": 3, ".3mf": 3, ".zip": 1, ".ply": 2}
    for path in _nasa_index(cache_dir):
        folder = path.split("/")[1] if path.count("/") >= 2 else path
        hay = path.lower()
        score = sum(1 for w in words if w in hay)
        if score < max(1, len(words) - 1):
            continue
        ext = "." + path.rsplit(".", 1)[-1].lower()
        rank = score * 10 + pref.get(ext, 0)
        if folder not in best or rank > best[folder][0]:
            best[folder] = (rank, path)
    out = []
    for folder, (_, path) in sorted(best.items(), key=lambda kv: kv[1][0], reverse=True)[:limit]:
        out.append({"title": folder, "url": NASA_RAW + quote(path), "page": "https://github.com/nasa/NASA-3D-Resources",
                    "site": "NASA 3D Resources", "format": path.rsplit(".", 1)[-1].lower(), "size": 0,
                    "kind": "official", "license": "NASA media usage guidelines (free to use)", "author": "NASA"})
    return out


def find(query: str, cfg: dict, data_dir: str | Path) -> dict:
    """Search every source. Never raises: problems become notes, so Corvis can report them honestly."""
    query = " ".join(str(query or "").split())[:120]
    q = re.sub(r"\b(blue ?prints?|3d|models?|schematics?|plans?|files?|stl|cad|for me|please|pull up|find|the)\b", " ",
               query, flags=re.I)
    q = " ".join(q.split()) or query
    verdict = assess(query)
    result = {"query": query, "search": q, "notes": list(verdict.get("notes") or []), "results": [], "pages": [],
              "problems": [], "blocked": verdict.get("blocked")}
    if verdict.get("blocked"):
        return result
    if not internet_cfg(cfg)["enabled"]:
        result["problems"].append("Internet access is turned off in config.yaml, so I can't search online.")
        return result
    for name, fn in (("Wikimedia Commons", lambda: search_commons(q)),
                     ("NASA 3D Resources", lambda: search_nasa(q, Path(data_dir) / "cache"))):
        try:
            result["results"].extend(fn())
        except WebError as e:
            result["problems"].append(str(e))
    try:
        for hit in web_search(f"{q} free 3D model STL download", cfg, limit=6):
            url = hit.get("url", "")
            entry = {"title": hit.get("title", "")[:120], "url": url, "site": urlparse(url).hostname or "",
                     "snippet": hit.get("snippet", "")[:200]}
            if url.lower().split("?")[0].endswith(MODEL_EXT):
                result["results"].append({**entry, "page": url, "format": url.lower().split("?")[0].rsplit(".", 1)[-1],
                                          "size": 0, "kind": "community", "license": "unknown (check the site)",
                                          "author": ""})
            else:
                result["pages"].append(entry)
    except Exception as e:   # web search is a bonus; the model libraries matter most
        result["problems"].append(f"Web search didn't work: {e}")
    result["results"].sort(key=lambda r: r["kind"] != "official")
    if not result["results"]:
        result["notes"].append(
            f"I couldn't find a downloadable 3D model of “{q}” that I'm allowed to pull in."
            + (" The web pages I found may have one behind a sign-in or a download button; open one and give me the "
               "direct link, or download it and drop the file in." if result["pages"] else "")
            + " I can also build an approximation from shapes, clearly labelled as mine.")
    return result


def download(url: str, cfg: dict) -> tuple[str, bytes]:
    """Fetch a model file from the public internet (never private or local addresses)."""
    allow = internet_cfg(cfg)["allow_private"]
    current = check_url(url, allow)
    session = requests.Session()
    for _ in range(6):
        try:
            r = session.get(current, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT, allow_redirects=False, stream=True)
        except requests.RequestException as e:
            raise WebError(f"Couldn't download {current}: {e}") from e
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            nxt = r.headers.get("Location")
            r.close()
            if not nxt:
                break
            current = check_url(urljoin(current, nxt), allow)   # every hop is checked
            continue
        break
    else:
        raise WebError("Too many redirects.")
    if r.status_code == 429:
        raise WebError(f"{urlparse(current).hostname} is rate-limiting right now. Try again in a minute.")
    if r.status_code >= 400:
        r.close()
        raise WebError(f"{current} returned HTTP {r.status_code}.")
    ctype = r.headers.get("Content-Type", "").lower()
    if "text/html" in ctype:
        r.close()
        raise WebError("That link is a web page, not a model file. Open it and find the direct download link "
                       "(some sites need you to sign in first), or download it and drop the file in.")
    raw = bytearray()
    for chunk in r.iter_content(1 << 16):
        raw += chunk
        if len(raw) > MAX_BYTES:
            r.close()
            raise WebError(f"That model is over {MAX_BYTES // (1024 * 1024)} MB.")
    r.close()
    name = Path(urlparse(current).path).name or "model"
    return requests.utils.unquote(name), bytes(raw)
