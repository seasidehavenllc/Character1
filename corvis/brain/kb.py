"""The knowledge base: Corvis's long-term, human-readable knowledge, kept as markdown files.

    Knowledge/
    ├── Current/<Category>/<Topic>.md        what Corvis knows now
    ├── PendingReview/<Category>/<Topic>.md  proposed updates waiting for approval
    │                 <Topic>.review.json    why the update was proposed
    └── Archive/<Category>/<Topic>/<when>.md every version that was replaced, and why
    Reports/{Daily,Weekly,Monthly}/          what each learning session did
    Dashboard.md                             the live state of the knowledge base

Every knowledge file starts with YAML front matter (title, topic, summary, sources, created,
last_verified, confidence, knowledge_health, related, ...) followed by readable markdown that
Corvis wrote in his own words. Files link to related files, which forms the knowledge graph.

Updates never overwrite knowledge straight away: they go to PendingReview, and only replace
the current file (archiving the old one) once approved, or automatically when Corvis's
confidence is above the configured threshold.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import shutil
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

import yaml

DEFAULT_CATEGORIES = ["Robotics", "ArtificialIntelligence", "Programming", "Engineering", "Electronics", "Business",
                      "Projects", "Research", "Personal"]
REVIEW_AFTER_DAYS = 90
STALE_PENALTY = 15
HEALTH_LABELS = [(95, "Excellent"), (80, "Healthy"), (60, "Needs Verification"), (40, "Aging Information"),
                 (0, "Potentially Outdated")]

# How much Corvis trusts a kind of source (0-1). Official docs and standards bodies first.
OFFICIAL = ("docs.ros.org", "ros.org", "arduino.cc", "raspberrypi.com", "python.org", "docs.python.org",
            "developer.mozilla.org", "learn.microsoft.com", "developer.nvidia.com", "docs.nvidia.com", "kernel.org",
            "w3.org", "ietf.org", "iso.org", "ieee.org", "nist.gov", "nasa.gov", "rust-lang.org", "go.dev",
            "nodejs.org", "react.dev", "pytorch.org", "tensorflow.org", "opencv.org", "docs.opencv.org",
            "unrealengine.com", "docs.unity3d.com", "espressif.com", "st.com", "ti.com", "analog.com", "microchip.com")
SCHOLARLY = ("arxiv.org", "nature.com", "science.org", "acm.org", "springer.com", "sciencedirect.com",
             "mit.edu", "stanford.edu", "cmu.edu", "berkeley.edu")
WEAK = ("pinterest.", "quora.com", "reddit.com", "facebook.com", "tiktok.com", "x.com", "twitter.com", "instagram.com")


def source_reliability(url: str) -> float:
    host = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if not host:
        return 0.5
    if any(host == d or host.endswith("." + d) for d in OFFICIAL) or host.startswith(("docs.", "developer.")) \
            or "readthedocs" in host:
        return 0.95
    if host.endswith((".gov", ".mil")) or any(host == d or host.endswith("." + d) for d in SCHOLARLY):
        return 0.92
    if host.endswith(".edu") or host.endswith(".ac.uk"):
        return 0.88
    if host.endswith("wikipedia.org"):
        return 0.8
    if host in ("github.com", "gitlab.com"):
        return 0.75
    if host.endswith(("stackoverflow.com", "stackexchange.com")):
        return 0.65
    if any(w in host for w in WEAK):
        return 0.35
    if any(w in host for w in ("medium.com", "dev.to", "blogspot", "wordpress", "substack")):
        return 0.5
    return 0.6


def health_label(score: float) -> str:
    return next(label for floor, label in HEALTH_LABELS if score >= floor)


def slugify(title: str) -> str:
    """'Servo motors' -> 'ServoMotors' (the user's naming style)."""
    words = re.findall(r"[A-Za-z0-9]+", title)
    slug = "".join(w if w.isupper() and len(w) > 1 else w[:1].upper() + w[1:] for w in words)
    if slug:
        return slug[:80]
    digest = hashlib.sha1(str(title).encode("utf-8")).hexdigest()[:8]   # e.g. a title in another script
    return f"Topic{digest}"


def category_name(name: str) -> str:
    known = {c.lower(): c for c in DEFAULT_CATEGORIES}
    key = re.sub(r"[^a-z0-9]", "", str(name or "").lower())
    for k, v in known.items():
        if key == k or key == re.sub(r"[^a-z0-9]", "", v.lower()):
            return v
    if key in ("ai", "machinelearning", "ml"):
        return "ArtificialIntelligence"
    return slugify(name or "Research")


def today() -> str:
    return dt.date.today().isoformat()


def _days_since(date_str: str, now: dt.date | None = None) -> int:
    try:
        return ((now or dt.date.today()) - dt.date.fromisoformat(str(date_str)[:10])).days
    except ValueError:
        return 9999


def compute_health(meta: dict, now: dt.date | None = None, review_after: int = REVIEW_AFTER_DAYS) -> dict:
    """Knowledge Health Score (0-100) and the reasons behind it."""
    sources = meta.get("sources") or []
    rel = [float(s.get("reliability", source_reliability(s.get("url", "")))) for s in sources if isinstance(s, dict)]
    domains = {urlparse(s.get("url", "")).hostname for s in sources if isinstance(s, dict) and s.get("url")}
    reliability = sum(rel) / len(rel) if rel else 0.3
    validation = min(1.0, len(domains) / 4)
    age = _days_since(meta.get("last_verified") or meta.get("created") or "", now)
    if age <= 30:
        freshness = 1.0
    elif age <= review_after:
        freshness = 1.0 - 0.4 * (age - 30) / max(review_after - 30, 1)
    else:
        freshness = max(0.0, 0.6 - 0.6 * (age - review_after) / 275)
    consistency = 1.0 - min(1.0, 0.25 * len(meta.get("conflicts") or []))
    confidence = max(0.0, min(1.0, float(meta.get("confidence") or 0) / 100))
    updates = 0.5 + 0.5 * min(1.0, int(meta.get("update_count") or 0) / 3)
    score = 100 * (0.25 * reliability + 0.20 * validation + 0.20 * freshness + 0.15 * consistency
                   + 0.15 * confidence + 0.05 * updates)
    overdue = age > review_after
    if overdue:
        score -= STALE_PENALTY
    score = round(max(0.0, min(100.0, score)))
    return {"score": score, "label": health_label(score), "overdue": overdue, "age_days": age,
            "factors": {"source_reliability": round(reliability, 2), "validating_sources": len(domains),
                        "days_since_verified": age, "conflicts": len(meta.get("conflicts") or []),
                        "confidence": round(confidence * 100), "updates": int(meta.get("update_count") or 0)}}


def compute_confidence(sources: list[dict], supported_ratio: float, conflicts: int) -> int:
    """How sure Corvis is, from how good and how many sources agree."""
    rel = [float(s.get("reliability", 0.5)) for s in sources] or [0.3]
    domains = {urlparse(s.get("url", "")).hostname for s in sources if s.get("url")}
    c = 100 * (0.5 * sum(rel) / len(rel) + 0.3 * min(1.0, len(domains) / 4) + 0.2 * supported_ratio) - 8 * conflicts
    return int(max(5, min(99, round(c))))


# --- reading and writing files -------------------------------------------------------------

def parse(text: str) -> tuple[dict, str]:
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end > 0:
            try:
                meta = yaml.safe_load(text[3:end]) or {}
            except yaml.YAMLError:
                meta = {}
            return (meta if isinstance(meta, dict) else {}), text[end + 4:].lstrip("\n")
    return {}, text


def dump(meta: dict, body: str) -> str:
    front = yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=110).strip()
    return f"---\n{front}\n---\n\n{body.strip()}\n"


FIELD_ORDER = ["title", "topic", "category", "summary", "sources", "created", "last_verified", "confidence",
               "knowledge_health", "health_label", "related", "tags", "conflicts", "update_count", "version"]


def render(doc: dict, kb_root: Path | None = None) -> str:
    """A knowledge file: front matter + readable markdown."""
    meta = {k: doc[k] for k in FIELD_ORDER if k in doc}
    lines = [f"# {doc['title']}", "", f"> {doc.get('summary', '').strip()}", ""]
    meta_line = (f"**Confidence:** {doc.get('confidence', 0)}% · **Knowledge health:** {doc.get('knowledge_health', 0)}% "
                 f"({doc.get('health_label', '')}) · **Last verified:** {doc.get('last_verified', '')}")
    lines += [meta_line, ""]
    if doc.get("key_points"):
        lines += ["## Key points", ""] + [f"- {p}" for p in doc["key_points"]] + [""]
    if doc.get("details"):
        lines += ["## Details", "", doc["details"].strip(), ""]
    if doc.get("conflicts"):
        lines += ["## Conflicting information", ""] + [f"- {c}" for c in doc["conflicts"]] + [""]
    if doc.get("related"):
        lines += ["## Related topics", ""]
        here = doc.get("category", "Research")
        for rid in doc["related"]:
            cat, _, slug = rid.partition("/")
            rel_path = f"{slug}.md" if cat == here else f"../{cat}/{slug}.md"
            lines.append(f"- [{doc.get('related_titles', {}).get(rid, slug)}]({rel_path})")
        lines.append("")
    if doc.get("sources"):
        lines += ["## Sources", ""]
        for i, s in enumerate(doc["sources"], 1):
            lines.append(f"{i}. [{s.get('title') or s.get('url')}]({s.get('url')}) — reliability "
                         f"{round(100 * float(s.get('reliability', 0.5)))}%, read {s.get('accessed', '')}")
        lines.append("")
    if doc.get("history"):
        lines += ["## History", ""] + [f"- {h}" for h in doc["history"][-30:]] + [""]
    return dump(meta, "\n".join(lines))


def body_sections(body: str) -> dict:
    """Pull key points, details, history back out of a rendered file."""
    out: dict = {"key_points": [], "details": "", "history": []}
    current = None
    buf: list[str] = []

    def flush():
        if current == "Key points":
            out["key_points"] = [l[2:].strip() for l in buf if l.startswith("- ")]
        elif current == "Details":
            out["details"] = "\n".join(buf).strip()
        elif current == "History":
            out["history"] = [l[2:].strip() for l in buf if l.startswith("- ")]
    for line in body.splitlines():
        if line.startswith("## "):
            flush()
            current, buf = line[3:].strip(), []
        else:
            buf.append(line)
    flush()
    return out


class KnowledgeBase:
    def __init__(self, root: str | Path, review_after_days: int = REVIEW_AFTER_DAYS, on_change=None):
        self.root = Path(root)
        self.review_after = review_after_days
        self.on_change = on_change or (lambda message: None)   # e.g. commit to Git
        self._lock = threading.RLock()
        for sub in ("Knowledge/Current", "Knowledge/PendingReview", "Knowledge/Archive", "Reports/Daily",
                    "Reports/Weekly", "Reports/Monthly"):
            (self.root / sub).mkdir(parents=True, exist_ok=True)
        for cat in DEFAULT_CATEGORIES:
            (self.root / "Knowledge/Current" / cat).mkdir(exist_ok=True)
            keep = self.root / "Knowledge/Current" / cat / ".gitkeep"
            if not keep.exists():
                keep.write_text("", encoding="utf-8")
        self._cache: dict[str, tuple[float, dict]] = {}

    # --- paths ---------------------------------------------------------------------------
    def _path(self, doc_id: str, area: str = "Current") -> Path:
        cat, _, slug = str(doc_id).partition("/")
        if not cat or not slug or not re.fullmatch(r"[A-Za-z0-9]+", cat) or not re.fullmatch(r"[A-Za-z0-9]+", slug):
            raise KeyError(f"Bad knowledge id '{doc_id}' (use Category/Topic, e.g. Robotics/ServoMotors).")
        return self.root / "Knowledge" / area / cat / f"{slug}.md"

    def rel(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix()

    # --- reading -------------------------------------------------------------------------
    def _load(self, path: Path) -> dict:
        stamp = path.stat().st_mtime
        hit = self._cache.get(str(path))
        if hit and hit[0] == stamp:
            return hit[1]
        meta, body = parse(path.read_text(encoding="utf-8"))
        doc = {**meta, **body_sections(body), "body": body,
               "id": f"{path.parent.name}/{path.stem}", "path": self.rel(path)}
        doc.setdefault("title", path.stem)
        doc.setdefault("category", path.parent.name)
        doc["related"] = [r for r in (doc.get("related") or []) if isinstance(r, str)]
        self._cache[str(path)] = (stamp, doc)
        return doc

    def get(self, doc_id: str, area: str = "Current") -> dict:
        path = self._path(doc_id, area)
        if not path.is_file():
            raise KeyError(f"No knowledge file '{doc_id}'.")
        doc = dict(self._load(path))
        h = compute_health(doc, review_after=self.review_after)
        doc["health"] = h
        return doc

    def all(self) -> list[dict]:
        out = []
        for path in sorted((self.root / "Knowledge/Current").glob("*/*.md")):
            try:
                d = dict(self._load(path))
            except (OSError, ValueError):
                continue
            d["health"] = compute_health(d, review_after=self.review_after)
            out.append(d)
        return out

    def find(self, title: str) -> dict | None:
        """A file by id, or by title / slug (case-insensitive)."""
        t = str(title or "").strip()
        if "/" in t:
            try:
                return self.get(t)
            except KeyError:
                pass
        slug = slugify(t).lower()
        for d in self.all():
            if d["title"].lower() == t.lower() or d["id"].split("/")[1].lower() == slug:
                return d
        return None

    # --- search and the graph ------------------------------------------------------------
    @staticmethod
    def _terms(text: str) -> list[str]:
        return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if len(w) > 2 and w not in STOP]

    def search(self, query: str, limit: int = 6, expand: bool = True) -> list[dict]:
        terms = self._terms(query)
        if not terms:
            return []
        docs = self.all()
        scored = []
        for d in docs:
            title = d["title"].lower()
            hay_title = set(self._terms(d["title"] + " " + d["id"]))
            hay_summary = d.get("summary", "").lower()
            hay_tags = " ".join(d.get("tags") or []).lower() + " " + d.get("topic", "").lower()
            body = d.get("body", "").lower()
            s = 0.0
            for t in set(terms):
                s += 4 * (t in hay_title) + 2 * (t in hay_summary) + 2 * (t in hay_tags) + min(body.count(t), 6) * 0.3
            if query.lower().strip() and query.lower().strip() in title:
                s += 6
            if s > 0:
                s *= 0.6 + 0.4 * d["health"]["score"] / 100   # healthier knowledge ranks higher
                scored.append((s, d))
        scored.sort(key=lambda x: x[0], reverse=True)
        hits = [dict(d, score=round(s, 2), via=None) for s, d in scored[:limit]]
        if expand and hits:   # one hop along the graph: related topics come along
            seen = {h["id"] for h in hits}
            by_id = {d["id"]: d for d in docs}
            for h in list(hits[:3]):
                for rid in h.get("related", [])[:4]:
                    if rid in by_id and rid not in seen and len(hits) < limit + 3:
                        seen.add(rid)
                        hits.append(dict(by_id[rid], score=0, via=h["id"]))
        return hits

    def graph(self) -> dict:
        docs = self.all()
        ids = {d["id"] for d in docs}
        nodes = [{"id": d["id"], "title": d["title"], "category": d["category"], "health": d["health"]["score"],
                  "confidence": int(d.get("confidence") or 0), "created": str(d.get("created") or "")[:10],
                  "last_verified": str(d.get("last_verified") or "")[:10]}
                 for d in docs]
        edges, seen = [], set()
        for d in docs:
            for r in d.get("related", []):
                if r in ids and r != d["id"]:
                    key = tuple(sorted((d["id"], r)))
                    if key not in seen:
                        seen.add(key)
                        edges.append({"from": key[0], "to": key[1]})
        return {"nodes": nodes, "edges": edges}

    def neighbours(self, doc_id: str, depth: int = 2) -> list[list[str]]:
        """Chains of related topics starting from one file, e.g. Robot Arms -> Servo Motors -> Arduino."""
        g = self.graph()
        adj: dict[str, set] = {}
        for e in g["edges"]:
            adj.setdefault(e["from"], set()).add(e["to"])
            adj.setdefault(e["to"], set()).add(e["from"])
        chains, frontier = [], [[doc_id]]
        for _ in range(depth):
            nxt = []
            for chain in frontier:
                for n in sorted(adj.get(chain[-1], ())):
                    if n not in chain:
                        nxt.append(chain + [n])
            chains.extend(nxt)
            frontier = nxt[:40]
        return chains

    # --- writing -------------------------------------------------------------------------
    def _finish_doc(self, doc: dict) -> dict:
        doc["category"] = category_name(doc.get("category") or "Research")
        doc["title"] = " ".join(str(doc["title"]).split())[:120]
        doc.setdefault("topic", doc["category"])
        doc.setdefault("created", today())
        doc.setdefault("last_verified", today())
        doc["sources"] = [{"title": str(s.get("title") or "")[:160], "url": str(s.get("url") or ""),
                           "reliability": round(float(s.get("reliability", source_reliability(s.get("url", "")))), 2),
                           "accessed": str(s.get("accessed") or today())}
                          for s in (doc.get("sources") or []) if isinstance(s, dict) and s.get("url")]
        doc["related"] = sorted({r for r in (doc.get("related") or []) if isinstance(r, str) and "/" in r})
        doc["confidence"] = int(max(0, min(100, int(doc.get("confidence") or 0))))
        doc.setdefault("update_count", 0)
        doc.setdefault("version", 1)
        h = compute_health(doc, review_after=self.review_after)
        doc["knowledge_health"], doc["health_label"] = h["score"], h["label"]
        titles = {}
        for rid in doc["related"]:
            try:
                titles[rid] = self.get(rid)["title"]
            except KeyError:
                titles[rid] = rid.split("/")[1]
        doc["related_titles"] = titles
        return doc

    def _write(self, path: Path, doc: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(render(doc), encoding="utf-8")
        os.replace(tmp, path)

    def create(self, doc: dict, message: str = "") -> dict:
        """New knowledge goes straight into Current (there's nothing old to protect)."""
        with self._lock:
            doc = self._finish_doc(dict(doc))
            doc_id = f"{doc['category']}/{slugify(doc['title'])}"
            path = self._path(doc_id)
            if path.exists():
                raise ValueError(f"'{doc_id}' already exists; propose an update instead.")
            doc["history"] = list(doc.get("history") or []) + [f"{today()}: created ({len(doc['sources'])} source{'' if len(doc['sources']) == 1 else 's'})"]
            self._write(path, doc)
            self._link_back(doc_id, doc["related"])
            self.on_change(message or f"Learn: {doc['title']}")
            return self.get(doc_id)

    def _link_back(self, doc_id: str, related: list[str]) -> None:
        """Relationships go both ways: add this file to each related file's list."""
        for rid in related:
            try:
                other = self.get(rid)
            except KeyError:
                continue
            if doc_id in other["related"]:
                continue
            other = {k: v for k, v in other.items() if k not in ("health", "body", "id", "path")}
            other["related"] = list(other["related"]) + [doc_id]
            other = self._finish_doc(other)
            self._write(self._path(rid), other)

    def relate(self, a: str, b: str) -> None:
        with self._lock:
            self.get(a), self.get(b)
            self._link_back(a, [b])
            self._link_back(b, [a])
            self.on_change(f"Link: {a} <-> {b}")

    def verify(self, doc_id: str, new_sources: list[dict] | None = None, note: str = "") -> dict:
        """Nothing changed after checking: refresh last_verified (and add any new sources)."""
        with self._lock:
            doc = {k: v for k, v in self.get(doc_id).items() if k not in ("health", "body", "id", "path")}
            urls = {s["url"] for s in doc.get("sources", [])}
            doc["sources"] = list(doc.get("sources", [])) + [s for s in (new_sources or []) if s.get("url") not in urls]
            doc["last_verified"] = today()
            doc["history"] = list(doc.get("history") or []) + [f"{today()}: verified, still current{(' — ' + note) if note else ''}"]
            self._write(self._path(doc_id), self._finish_doc(doc))
            self.on_change(f"Verify: {doc['title']}")
            return self.get(doc_id)

    def propose(self, doc_id: str, new: dict, reason: str, auto_threshold: int = 0) -> dict:
        """Suggest a new version. It waits in PendingReview unless confidence clears the threshold."""
        with self._lock:
            old = self.get(doc_id)
            new = dict(new)
            new["category"], new["title"] = old["category"], new.get("title") or old["title"]
            new["created"] = old.get("created", today())
            new["last_verified"] = today()
            new["update_count"] = int(old.get("update_count") or 0) + 1
            new["version"] = int(old.get("version") or 1) + 1
            new["history"] = list(old.get("history") or []) + [f"{today()}: updated — {reason}"]
            new["related"] = sorted(set(old.get("related") or []) | set(new.get("related") or []))
            new = self._finish_doc(new)
            review = {"id": doc_id, "reason": reason, "proposed": time.time(), "old_confidence": old.get("confidence"),
                      "new_confidence": new["confidence"], "old_version": old.get("version", 1)}
            if auto_threshold and new["confidence"] >= auto_threshold and new["confidence"] >= int(old.get("confidence") or 0) - 5:
                self._apply(doc_id, new, reason, auto=True)
                return {"status": "applied", "id": doc_id, "reason": reason, "confidence": new["confidence"]}
            path = self._path(doc_id, "PendingReview")
            self._write(path, new)
            path.with_suffix(".review.json").write_text(json.dumps(review, indent=1), encoding="utf-8")
            self.on_change(f"Propose update: {old['title']} ({reason[:60]})")
            return {"status": "pending", "id": doc_id, "reason": reason, "confidence": new["confidence"]}

    def _apply(self, doc_id: str, new: dict, reason: str, auto: bool = False) -> None:
        current = self._path(doc_id)
        stamp = dt.datetime.now().strftime("%Y-%m-%dT%H-%M-%S")
        archive = self.root / "Knowledge/Archive" / doc_id.split("/")[0] / doc_id.split("/")[1] / f"{stamp}.md"
        archive.parent.mkdir(parents=True, exist_ok=True)
        if current.exists():
            meta, body = parse(current.read_text(encoding="utf-8"))
            meta["archived"] = today()
            meta["archived_reason"] = reason
            archive.write_text(dump(meta, body), encoding="utf-8")
        self._write(current, new)
        self._link_back(doc_id, new.get("related") or [])
        self.on_change(f"{'Auto-approve' if auto else 'Approve'} update: {new['title']} — {reason[:70]}")

    def pending(self) -> list[dict]:
        out = []
        for review in sorted((self.root / "Knowledge/PendingReview").glob("*/*.review.json")):
            info = json.loads(review.read_text(encoding="utf-8"))
            doc_id = info["id"]
            try:
                new = self.get(doc_id, "PendingReview")
                old = self.get(doc_id)
            except KeyError:
                continue
            out.append({**info, "title": new["title"], "new_summary": new.get("summary", ""),
                        "old_summary": old.get("summary", ""), "new_points": new.get("key_points", []),
                        "old_points": old.get("key_points", [])})
        return out

    def approve(self, doc_id: str) -> dict:
        with self._lock:
            path = self._path(doc_id, "PendingReview")
            if not path.exists():
                raise KeyError(f"No pending update for '{doc_id}'.")
            info = json.loads(path.with_suffix(".review.json").read_text(encoding="utf-8"))
            new = {k: v for k, v in self.get(doc_id, "PendingReview").items() if k not in ("health", "body", "id", "path")}
            self._apply(doc_id, self._finish_doc(new), info.get("reason", "approved"))
            path.unlink()
            path.with_suffix(".review.json").unlink()
            return self.get(doc_id)

    def reject(self, doc_id: str, why: str = "") -> None:
        with self._lock:
            path = self._path(doc_id, "PendingReview")
            if not path.exists():
                raise KeyError(f"No pending update for '{doc_id}'.")
            path.unlink()
            path.with_suffix(".review.json").unlink(missing_ok=True)
            self.on_change(f"Reject update: {doc_id}{(' — ' + why) if why else ''}")

    def archive_versions(self, doc_id: str) -> list[dict]:
        cat, _, slug = doc_id.partition("/")
        folder = self.root / "Knowledge/Archive" / cat / slug
        out = []
        for p in sorted(folder.glob("*.md"), reverse=True) if folder.is_dir() else []:
            meta, _ = parse(p.read_text(encoding="utf-8"))
            out.append({"when": p.stem, "reason": meta.get("archived_reason", ""), "version": meta.get("version"),
                        "path": self.rel(p)})
        return out

    # --- upkeep ----------------------------------------------------------------------------
    def due_for_review(self) -> list[dict]:
        """Files older than the review window (or unhealthy), most urgent first."""
        docs = [d for d in self.all() if d["health"]["overdue"] or d["health"]["score"] < 60]
        return sorted(docs, key=lambda d: d["health"]["score"])

    def refresh_scores(self) -> int:
        """Rewrite stored health scores that drifted as files aged."""
        changed = 0
        with self._lock:
            for d in self.all():
                if int(d.get("knowledge_health") or -1) != d["health"]["score"]:
                    doc = {k: v for k, v in d.items() if k not in ("health", "body", "id", "path")}
                    self._write(self._path(d["id"]), self._finish_doc(doc))
                    changed += 1
            if changed:
                self.on_change(f"Health check: {changed} scores updated")
        return changed

    def dashboard(self) -> dict:
        docs = self.all()
        pending = self.pending()
        cats: dict[str, list[int]] = {}
        sources = set()
        for d in docs:
            cats.setdefault(d["category"], []).append(d["health"]["score"])
            sources.update(s.get("url") for s in d.get("sources") or [] if isinstance(s, dict))
        needs = [d for d in docs if d["health"]["score"] < 80 or d["health"]["overdue"]]
        urgent = [d for d in docs if d["health"]["score"] < 40] + [{"id": p["id"], "title": p["title"]} for p in pending]
        overall = round(sum(d["health"]["score"] for d in docs) / len(docs)) if docs else 0
        return {
            "total_files": len(docs), "total_categories": len([c for c in cats if cats[c]]), "total_sources": len(sources),
            "healthy_files": len([d for d in docs if d["health"]["score"] >= 80]),
            "needs_review": len(needs), "high_priority": len(urgent), "pending_reviews": len(pending),
            "overall_health": overall, "overall_label": health_label(overall) if docs else "No knowledge yet",
            "categories": {c: {"files": len(v), "health": round(sum(v) / len(v))} for c, v in sorted(cats.items())},
            "needs_review_list": [{"id": d["id"], "title": d["title"], "health": d["health"]["score"],
                                   "overdue": d["health"]["overdue"]} for d in sorted(needs, key=lambda d: d["health"]["score"])[:20]],
            "relationships": len(self.graph()["edges"]),
        }

    def write_dashboard(self) -> None:
        d = self.dashboard()
        lines = ["# Knowledge Dashboard", "", f"_Updated {dt.datetime.now():%Y-%m-%d %H:%M} by Corvis._", "",
                 "## Knowledge Base Summary", "", "| | |", "|---|---|",
                 f"| Total files | {d['total_files']} |", f"| Total categories | {d['total_categories']} |",
                 f"| Total sources | {d['total_sources']} |", f"| Healthy files | {d['healthy_files']} |",
                 f"| Files needing review | {d['needs_review']} |", f"| High priority updates | {d['high_priority']} |",
                 f"| Relationships | {d['relationships']} |", "",
                 f"**Overall knowledge health: {d['overall_health']}% ({d['overall_label']})**", "",
                 "## Category health", "", "| Category | Files | Health |", "|---|---|---|"]
        lines += [f"| {c} | {v['files']} | {v['health']}% ({health_label(v['health'])}) |" for c, v in d["categories"].items()]
        if d["needs_review_list"]:
            lines += ["", "## Needs review", ""]
            lines += [f"- [{x['title']}](Knowledge/Current/{x['id']}.md) — {x['health']}%"
                      + (" (not verified for over 90 days)" if x["overdue"] else "") for x in d["needs_review_list"]]
        (self.root / "Dashboard.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    # --- reports ---------------------------------------------------------------------------
    def write_report(self, report: dict) -> str:
        """Add a session to today's report, then rebuild this week's and month's."""
        day = dt.date.today()
        path = self.root / "Reports/Daily" / f"{day.isoformat()}.json"
        sessions = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        sessions.append(report)
        path.write_text(json.dumps(sessions, indent=1), encoding="utf-8")
        (self.root / "Reports/Daily" / f"{day.isoformat()}.md").write_text(
            self._report_md(f"Daily Learning Report — {day.isoformat()}", sessions), encoding="utf-8")
        iso = day.isocalendar()
        week = [s for p in (self.root / "Reports/Daily").glob("*.json")
                if dt.date.fromisoformat(p.stem).isocalendar()[:2] == iso[:2]
                for s in json.loads(p.read_text(encoding="utf-8"))]
        (self.root / "Reports/Weekly" / f"{iso[0]}-W{iso[1]:02d}.md").write_text(
            self._report_md(f"Weekly Learning Report — {iso[0]} week {iso[1]}", week), encoding="utf-8")
        month = [s for p in (self.root / "Reports/Daily").glob(f"{day:%Y-%m}-*.json")
                 for s in json.loads(p.read_text(encoding="utf-8"))]
        (self.root / "Reports/Monthly" / f"{day:%Y-%m}.md").write_text(
            self._report_md(f"Monthly Learning Report — {day:%B %Y}", month), encoding="utf-8")
        self.write_dashboard()
        self.on_change(f"Report: {report.get('mode', 'learning')} session on {report.get('topic', '')}")
        return f"Reports/Daily/{day.isoformat()}.md"

    @staticmethod
    def _report_md(title: str, sessions: list[dict]) -> str:
        tot = lambda k: sum(int(s.get(k) or 0) for s in sessions)
        uniq = lambda k: list(dict.fromkeys(x for s in sessions for x in s.get(k) or []))
        lines = [f"# {title}", "", f"Sessions: {len(sessions)}", f"Sources Reviewed: {tot('sources_reviewed')}",
                 f"Topics Researched: {tot('topics_researched')}", f"New Knowledge Files: {tot('new_files')}",
                 f"Updated Files: {tot('updated_files')}", f"Pending Review: {tot('pending')}",
                 f"Archived Files: {tot('archived')}", f"Verified Unchanged: {tot('verified')}",
                 f"Relationships Created: {tot('relationships')}", ""]
        for heading, key in (("Top Learning Topics", "topics"), ("Conflicting Information Found", "conflicts"),
                             ("Low Confidence Topics", "low_confidence"), ("Recommended Future Research", "recommended"),
                             ("Problems", "problems")):
            items = uniq(key)
            if items:
                lines += [f"## {heading}", ""] + [f"- {x}" for x in items[:40]] + [""]
        lines += ["## Sessions", ""]
        for s in sessions:
            lines.append(f"- {s.get('started', '')}: {s.get('mode', 'learn')} “{s.get('topic', '')}” — "
                         f"{s.get('sources_reviewed', 0)} sources, {s.get('new_files', 0)} new, "
                         f"{s.get('updated_files', 0)} updated, {s.get('minutes', 0)} min, {s.get('status', '')}")
        return "\n".join(lines) + "\n"

    def reports(self) -> list[dict]:
        out = []
        for kind in ("Daily", "Weekly", "Monthly"):
            for p in sorted((self.root / "Reports" / kind).glob("*.md"), reverse=True)[:30]:
                out.append({"kind": kind, "name": p.stem, "path": self.rel(p)})
        return out


STOP = {"the", "and", "for", "with", "that", "this", "what", "how", "are", "was", "you", "your", "can", "does",
        "about", "from", "into", "have", "has", "had", "use", "using", "why", "when", "who", "which", "tell", "know",
        "corvis", "please", "would", "could", "should", "there", "their", "them", "then", "than", "our", "did", "discuss"}
