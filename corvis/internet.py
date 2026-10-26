"""Web access: search the internet and read pages as clean text.

Search providers (set internet.search_provider in config.yaml):
- duckduckgo: no account or key needed (default)
- brave:      Brave Search API, needs internet.brave_api_key (free tier available)
- searxng:    your own SearXNG instance, needs internet.searxng_url (fully private)

Safety: pages can only be fetched from the public internet. Addresses on this PC or
your home network (127.0.0.1, 192.168.x.x, ...) are refused, so a web page can't trick
Corvis into poking at your router or at Corvis's own server.
"""
from __future__ import annotations

import ipaddress
import re
import socket
from html import unescape
from html.parser import HTMLParser
from urllib.parse import parse_qs, urljoin, urlparse

import requests

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/128.0 Safari/537.36")
MAX_PAGE_BYTES = 4_000_000
MAX_REDIRECTS = 5
TIMEOUT = 20


class WebError(RuntimeError):
    pass


def internet_cfg(cfg: dict) -> dict:
    i = cfg.get("internet", {}) or {}
    return {
        "enabled": i.get("enabled", True),
        "provider": str(i.get("search_provider", "duckduckgo")).lower(),
        "brave_api_key": i.get("brave_api_key") or "",
        "brave_endpoint": i.get("brave_endpoint", "https://api.search.brave.com/res/v1/web/search"),
        "searxng_url": (i.get("searxng_url") or "").rstrip("/"),
        "allow_private": bool(i.get("allow_private_addresses", False)),
        "ddg_endpoints": i.get("ddg_endpoints", ["https://html.duckduckgo.com/html/",
                                                 "https://lite.duckduckgo.com/lite/"]),
    }


# --- search ---------------------------------------------------------------------
def _clean(s: str) -> str:
    return " ".join(unescape(re.sub(r"<[^>]+>", " ", s)).split())


def _ddg_target(href: str) -> str:
    """DuckDuckGo wraps result links (//duckduckgo.com/l/?uddg=REAL_URL). Unwrap them."""
    if href.startswith("//"):
        href = "https:" + href
    parsed = urlparse(href)
    if "duckduckgo.com" in parsed.netloc and parsed.path.startswith("/l/"):
        target = parse_qs(parsed.query).get("uddg", [""])[0]
        return target or href
    return href


class _DDGParser(HTMLParser):
    """Reads both the html.duckduckgo.com and lite.duckduckgo.com result pages."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results: list[dict] = []
        self._mode = None  # "title" | "snippet"
        self._buf: list[str] = []
        self._ad_depth = 0
        self._depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            return
        a = dict(attrs)
        cls = a.get("class", "") or ""
        self._depth += 1
        if tag == "div" and "result--ad" in cls:
            self._ad_depth = self._depth
        if self._ad_depth:
            return
        if tag == "a" and ("result__a" in cls or "result-link" in cls):
            href = _ddg_target(a.get("href", ""))
            if "duckduckgo.com/y.js" in href:  # sponsored
                return
            self.results.append({"title": "", "url": href, "snippet": ""})
            self._mode, self._buf = "title", []
        elif ("result__snippet" in cls or "result-snippet" in cls) and self.results:
            self._mode, self._buf = "snippet", []

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if self._ad_depth and self._depth <= self._ad_depth:
            self._ad_depth = 0
        self._depth -= 1
        if self._mode == "title" and tag == "a":
            self.results[-1]["title"] = " ".join("".join(self._buf).split())
            self._mode = None
        elif self._mode == "snippet" and tag in ("a", "td", "div"):
            self.results[-1]["snippet"] = " ".join("".join(self._buf).split())
            self._mode = None

    def handle_data(self, data):
        if self._mode:
            self._buf.append(data)


def parse_duckduckgo(html: str) -> list[dict]:
    p = _DDGParser()
    p.feed(html)
    seen, out = set(), []
    for r in p.results:
        if r["url"].startswith("http") and r["title"] and r["url"] not in seen:
            seen.add(r["url"])
            out.append(r)
    return out


def _search_duckduckgo(query: str, limit: int, c: dict) -> list[dict]:
    last_error = "no results"
    for endpoint in c["ddg_endpoints"]:
        try:
            r = requests.post(endpoint, data={"q": query, "kl": "us-en"},
                              headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
        except requests.RequestException as e:
            last_error = str(e)
            continue
        if r.status_code != 200:
            last_error = f"HTTP {r.status_code}"
            continue
        if "anomaly" in r.text[:5000].lower() and "result" not in r.text[:20000]:
            last_error = "DuckDuckGo asked for a bot check"
            continue
        results = parse_duckduckgo(r.text)
        if results:
            return results[:limit]
    raise WebError(f"DuckDuckGo search failed ({last_error}). If this keeps happening, set "
                   "internet.search_provider to 'brave' (free API key) or 'searxng' in config.yaml.")


def _search_brave(query: str, limit: int, c: dict) -> list[dict]:
    if not c["brave_api_key"]:
        raise WebError("Brave search needs internet.brave_api_key in config.yaml.")
    try:
        r = requests.get(c["brave_endpoint"], params={"q": query, "count": min(limit, 20)},
                         headers={"X-Subscription-Token": c["brave_api_key"], "Accept": "application/json"},
                         timeout=TIMEOUT)
    except requests.RequestException as e:
        raise WebError(f"Brave search failed: {e}") from e
    if r.status_code != 200:
        raise WebError(f"Brave search returned HTTP {r.status_code}: {r.text[:200]}")
    items = r.json().get("web", {}).get("results", [])
    return [{"title": _clean(i.get("title", "")), "url": i.get("url", ""),
             "snippet": _clean(i.get("description", ""))} for i in items][:limit]


def _search_searxng(query: str, limit: int, c: dict) -> list[dict]:
    if not c["searxng_url"]:
        raise WebError("SearXNG search needs internet.searxng_url in config.yaml (e.g. http://localhost:8888).")
    try:
        r = requests.get(f"{c['searxng_url']}/search", params={"q": query, "format": "json"},
                         headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT)
    except requests.RequestException as e:
        raise WebError(f"SearXNG search failed: {e}") from e
    if r.status_code != 200:
        raise WebError(f"SearXNG returned HTTP {r.status_code}. Make sure 'json' is enabled under "
                       "search.formats in its settings.yml.")
    items = r.json().get("results", [])
    return [{"title": _clean(i.get("title", "")), "url": i.get("url", ""),
             "snippet": _clean(i.get("content", ""))} for i in items][:limit]


PROVIDERS = {"duckduckgo": _search_duckduckgo, "brave": _search_brave, "searxng": _search_searxng}


def search(query: str, cfg: dict, limit: int = 6) -> list[dict]:
    c = internet_cfg(cfg)
    fn = PROVIDERS.get(c["provider"])
    if fn is None:
        raise WebError(f"Unknown search provider '{c['provider']}'. Use duckduckgo, brave or searxng.")
    return fn(query.strip(), max(1, min(limit, 15)), c)


# --- fetching pages -------------------------------------------------------------
def check_url(url: str, allow_private: bool = False) -> str:
    parsed = urlparse(url.strip())
    if parsed.scheme not in ("http", "https") or not parsed.hostname:
        raise WebError("Only http:// and https:// web addresses can be read.")
    if allow_private:
        return url.strip()
    try:
        infos = socket.getaddrinfo(parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as e:
        raise WebError(f"Couldn't find the site {parsed.hostname}: {e}") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0].split("%")[0])
        # Only truly public addresses: this also blocks Tailscale/CGNAT (100.64.0.0/10),
        # which is_private misses, so web pages can't reach devices on your tailnet.
        if not ip.is_global or ip.is_multicast:
            raise WebError(f"{parsed.hostname} points to a private or local address ({ip}). "
                           "Corvis only reads pages on the public internet.")
    return url.strip()


SKIP_TAGS = {"script", "style", "noscript", "svg", "nav", "footer", "header", "aside", "form",
             "iframe", "template", "button", "select", "canvas", "dialog"}
BLOCK_TAGS = {"p", "div", "section", "article", "main", "br", "tr", "table", "ul", "ol",
              "blockquote", "pre", "figure", "figcaption", "dl", "dt", "dd", "hr", "li",
              "h1", "h2", "h3", "h4", "h5", "h6"}
PRE_MARK = "\x00"
VOID_TAGS = {"br", "hr", "img", "input", "meta", "link", "source", "wbr", "area", "base", "col", "embed"}


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = ""
        self.parts: list[str] = []
        self.main_parts: list[str] = []
        self._skip = 0
        self._in_title = False
        self._main = 0
        self._pre = 0

    def _emit(self, s: str) -> None:
        self.parts.append(s)
        if self._main:
            self.main_parts.append(s)

    def handle_starttag(self, tag, attrs):
        if tag in VOID_TAGS:
            if tag in ("br", "hr"):
                self._emit("\n")
            return
        if tag in SKIP_TAGS or self._skip:
            self._skip += 1
            return
        if tag == "title":
            self._in_title = True
        if tag in ("main", "article"):
            self._main += 1
        if tag in BLOCK_TAGS:
            self._emit("\n")
        if tag == "pre":
            self._pre += 1
            self._emit(PRE_MARK)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._emit("#" * int(tag[1]) + " ")
        elif tag == "li":
            self._emit("- ")

    def handle_endtag(self, tag):
        if tag in VOID_TAGS:
            return
        if self._skip:
            self._skip -= 1
            return
        if tag == "title":
            self._in_title = False
        if tag in ("main", "article") and self._main:
            self._main -= 1
        if tag == "pre" and self._pre:
            self._pre -= 1
        if tag in BLOCK_TAGS:
            self._emit("\n")

    def handle_data(self, data):
        if self._in_title:
            self.title += data
            return
        if self._skip:
            return
        # Code blocks keep their indentation: each of their lines is marked so the
        # clean-up step below doesn't strip it.
        self._emit(data.replace("\n", "\n" + PRE_MARK) if self._pre else re.sub(r"\s+", " ", data))


def html_to_text(html: str) -> tuple[str, str]:
    p = _TextExtractor()
    try:
        p.feed(html)
        p.close()
    except Exception:  # malformed HTML: keep what we have
        pass
    main = "".join(p.main_parts)
    body = main if len(main.strip()) > 400 else "".join(p.parts)
    lines = [ln[len(PRE_MARK):].rstrip() if ln.startswith(PRE_MARK) else ln.strip()
             for ln in body.split("\n")]
    text, blank = [], 0
    for ln in lines:
        if ln in ("", "-", "#"):
            blank += 1
            if blank == 1 and text:
                text.append("")
            continue
        blank = 0
        text.append(ln)
    return " ".join(p.title.split()), "\n".join(text).strip()


def fetch(url: str, cfg: dict, start: int = 0, max_chars: int = 8000) -> str:
    c = internet_cfg(cfg)
    current = check_url(url, c["allow_private"])
    session = requests.Session()
    for _ in range(MAX_REDIRECTS + 1):
        try:
            r = session.get(current, headers={"User-Agent": USER_AGENT, "Accept": "text/html,text/plain,*/*"},
                            timeout=TIMEOUT, allow_redirects=False, stream=True)
        except requests.RequestException as e:
            raise WebError(f"Couldn't load {current}: {e}") from e
        if r.is_redirect or r.status_code in (301, 302, 303, 307, 308):
            nxt = r.headers.get("Location")
            r.close()
            if not nxt:
                break
            current = check_url(urljoin(current, nxt), c["allow_private"])  # re-check every hop
            continue
        break
    else:
        raise WebError("Too many redirects.")

    if r.status_code >= 400:
        r.close()
        raise WebError(f"{current} returned HTTP {r.status_code}.")
    ctype = r.headers.get("Content-Type", "").lower()
    if "pdf" in ctype or current.lower().endswith(".pdf"):
        r.close()
        raise WebError("That's a PDF. Corvis can't read PDFs from the web yet; try another source.")
    raw = b""
    for chunk in r.iter_content(65536):
        raw += chunk
        if len(raw) > MAX_PAGE_BYTES:
            break
    r.close()
    encoding = r.encoding or "utf-8"
    if "charset" not in ctype:
        m = re.search(rb'<meta[^>]+charset=["\']?([\w-]+)', raw[:4000], re.I)
        encoding = m.group(1).decode() if m else "utf-8"
    try:
        content = raw.decode(encoding, errors="replace")
    except LookupError:
        content = raw.decode("utf-8", errors="replace")

    if "html" in ctype or "<html" in content[:2000].lower():
        title, text = html_to_text(content)
    else:
        title, text = "", content.strip()
    if not text:
        raise WebError("The page loaded but had no readable text (it may need JavaScript).")
    start = max(0, int(start))
    piece = text[start:start + max_chars]
    more = (f"\n\n[Page continues: {len(text) - start - len(piece)} more characters. "
            f"Call fetch_page with start={start + len(piece)} to keep reading.]"
            if start + len(piece) < len(text) else "")
    head = f"{title or current}\n{current}\n\n"
    return head + piece + more
