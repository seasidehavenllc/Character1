"""Corvis's memory.

Two kinds:
- Facts: lasting things about the owner ("projects live in D:/Games", "prefers C#").
  Stored in data/memory/facts.json and included in every prompt.
- Chat recall: a ranked search over every saved chat (data/conversations/*.json),
  so Corvis can pull in what was said before, automatically or on request.

Everything stays on this PC. Search is keyword-based (BM25), so it needs no extra
model and works offline.
"""
from __future__ import annotations

import datetime
import json
import math
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been before being
below between both but by can could did do does doing down during each few for from further
had has have having he her here hers him his how i if in into is it its itself just let me
more most my no nor not now of off on once only or other our ours out over own same she
should so some such than that the their them then there these they this those through to
too under until up very was we were what when where which while who whom why will with
would you your yours yourself please thanks thank hey hi hello ok okay yes yeah also get
got make made want need like know think tell say said one two can't don't i'm it's that's
corvis jarvis
""".split())

CHUNK_CHARS = 700
# Words that mean "this connects to something from before". With one of these, a lighter
# match is enough to pull in an earlier chat; without, it has to be clearly the same topic.
BACK_REFERENCE = re.compile(
    r"\b(last time|before|earlier|previous(ly)?|again|yesterday|last (week|night|chat)|remember|recall|"
    r"we (did|made|built|wrote|talked|discussed|said|had|tried|fixed)|you (said|told|did|made|built|wrote|fixed)|"
    r"(that|the same) (bug|error|file|project|thing|script|issue|problem|idea|code)|like (last|before)|"
    r"other chat|old chat)\b", re.I)
MAX_FACTS = 300
FACTS_BLOCK_CHARS = 4000


# --- text helpers ---------------------------------------------------------------
def tokenize(text: str) -> list[str]:
    out = []
    for w in re.findall(r"[a-z0-9_+#.]+", text.lower()):
        w = w.strip(".")
        if len(w) < 2 or w in STOPWORDS:
            continue
        if len(w) > 4 and w.endswith("ies"):
            w = w[:-3] + "y"
        elif len(w) > 3 and w.endswith("s") and not w.endswith("ss"):
            w = w[:-1]
        out.append(w)
    return out


def chunk_text(text: str, size: int = CHUNK_CHARS) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    chunks, cur = [], ""
    for para in re.split(r"\n\s*\n", text):
        if len(cur) + len(para) + 2 <= size:
            cur = f"{cur}\n\n{para}" if cur else para
            continue
        if cur:
            chunks.append(cur)
        while len(para) > size:
            chunks.append(para[:size])
            para = para[size:]
        cur = para
    if cur:
        chunks.append(cur)
    return chunks


def snippet(text: str, terms: set[str], width: int = 360) -> str:
    flat = " ".join(text.split())
    if len(flat) <= width:
        return flat
    low = flat.lower()
    pos = min((low.find(t) for t in terms if low.find(t) >= 0), default=0)
    start = max(0, pos - width // 3)
    piece = flat[start:start + width]
    return ("…" if start else "") + piece + ("…" if start + width < len(flat) else "")


def fmt_date(ts: float) -> str:
    return datetime.datetime.fromtimestamp(ts).strftime("%b %d, %Y")


# --- facts ----------------------------------------------------------------------
class FactStore:
    def __init__(self, folder: Path):
        self.path = Path(folder) / "facts.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def list(self) -> list[dict]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []

    def _write(self, facts: list[dict]) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(facts, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.path)

    def add(self, text: str, bot: str | None = None) -> tuple[dict, bool]:
        """Returns (fact, created). An identical fact isn't saved twice.

        bot=None: shared by every bot (facts about the owner). bot=<id>: something that bot
        learned doing its job, only in its own memory."""
        text = " ".join(str(text).split())[:500]
        if not text:
            raise ValueError("Nothing to remember.")
        with self._lock:
            facts = self.list()
            for f in facts:
                if f["text"].lower() == text.lower() and f.get("bot") == bot:
                    return f, False
            next_n = max((int(f["id"][1:]) for f in facts if f["id"][1:].isdigit()), default=0) + 1
            fact = {"id": f"m{next_n}", "text": text, "ts": time.time()}
            if bot:
                fact["bot"] = bot
            facts.append(fact)
            self._write(facts[-MAX_FACTS:])
            return fact, True

    def remove(self, ref: str) -> dict | None:
        """Remove by id ("m3") or by matching text."""
        ref = str(ref).strip()
        with self._lock:
            facts = self.list()
            for i, f in enumerate(facts):
                if f["id"] == ref or f["text"].lower() == ref.lower():
                    facts.pop(i)
                    self._write(facts)
                    return f
            low = ref.lower()
            matches = [f for f in facts if low and low in f["text"].lower()]
            if len(matches) == 1:
                facts.remove(matches[0])
                self._write(facts)
                return matches[0]
        return None

    def block(self, bot: str | None = None) -> str:
        """Shared facts, plus what this bot learned (its own memory)."""
        all_ = self.list()
        shared = [f for f in all_ if not f.get("bot")]
        own = [f for f in all_ if bot and f.get("bot") == bot]
        out = ""
        for facts, title in ((shared, "What you remember about the owner (long-term memory; ids in "
                                       "brackets, use forget to remove one):"),
                             (own, "What you've learned doing your job (your own memory):")):
            lines, used = [], 0
            for f in reversed(facts):  # newest first if we have to cut
                line = f"- [{f['id']}] {f['text']}"
                if used + len(line) > FACTS_BLOCK_CHARS:
                    break
                lines.append(line)
                used += len(line)
            if lines:
                out += f"\n{title}\n" + "\n".join(reversed(lines)) + "\n"
        return out


# --- chat search ----------------------------------------------------------------
class ChatIndex:
    """BM25 search over saved chats. Re-reads only chats that changed."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._cache: dict[str, tuple[float, dict, list[dict]]] = {}
        self._lock = threading.Lock()

    def _load(self) -> list[tuple[dict, list[dict]]]:
        out = []
        seen = set()
        if not self.folder.is_dir():
            return out
        with self._lock:
            for path in self.folder.glob("*.json"):
                key = str(path)
                seen.add(key)
                try:
                    mtime = path.stat().st_mtime
                except OSError:
                    continue
                cached = self._cache.get(key)
                if not cached or cached[0] != mtime:
                    try:
                        conv = json.loads(path.read_text(encoding="utf-8"))
                    except (OSError, json.JSONDecodeError):
                        continue
                    meta = {k: conv.get(k) for k in ("id", "title", "updated", "mode", "workspace")}
                    chunks = []
                    msgs = conv.get("messages", [])
                    for i, m in enumerate(msgs):
                        who = "You" if m.get("role") == "user" else "Corvis"
                        # A question is only half the memory: keep the answer that followed it.
                        nxt = msgs[i + 1] if i + 1 < len(msgs) else None
                        reply = (nxt.get("text", "") if who == "You" and nxt
                                 and nxt.get("role") == "assistant" else "")
                        names = [a.get("name", "") for a in m.get("attachments") or []]
                        body = m.get("text", "") + (f"\n[Attached: {', '.join(names)}]" if names else "")
                        for piece in chunk_text(body):
                            chunks.append({"who": who, "text": piece, "tokens": tokenize(piece),
                                           "reply": reply, "ts": m.get("ts", conv.get("updated", 0))})
                    cached = (mtime, meta, chunks)
                    self._cache[key] = cached
                out.append((cached[1], cached[2]))
            for key in list(self._cache):
                if key not in seen:
                    del self._cache[key]
        return out

    def search(self, query: str, limit: int = 5, exclude: str | None = None,
               per_chat: int = 2) -> list[dict]:
        q = set(tokenize(query))
        if not q:
            return []
        docs = [(meta, c) for meta, chunks in self._load() if meta["id"] != exclude for c in chunks]
        if not docs:
            return []
        n = len(docs)
        avg = sum(len(c["tokens"]) for _, c in docs) / n or 1
        df = Counter()
        for _, c in docs:
            df.update(set(c["tokens"]) & q)
        idf = {t: math.log(1 + (n - df[t] + 0.5) / (df[t] + 0.5)) for t in q}
        now = time.time()
        scored = []
        for meta, c in docs:
            tf = Counter(t for t in c["tokens"] if t in q)
            if not tf:
                continue
            length = len(c["tokens"]) or 1
            score = sum(idf[t] * f * 2.5 / (f + 1.5 * (0.25 + 0.75 * length / avg)) for t, f in tf.items())
            age_days = max(0.0, (now - (c["ts"] or now)) / 86400)
            score *= 1 + 0.15 * math.exp(-age_days / 30)  # slight preference for recent
            scored.append((score, len(tf), meta, c))
        scored.sort(key=lambda s: s[0], reverse=True)
        results, per = [], Counter()
        for score, matched, meta, c in scored:
            if per[meta["id"]] >= per_chat:
                continue
            per[meta["id"]] += 1
            results.append({
                "chat_id": meta["id"], "title": meta["title"], "date": fmt_date(c["ts"] or 0),
                "who": c["who"], "snippet": snippet(c["text"], q), "score": round(score, 2),
                "reply": snippet(c["reply"], q, width=420) if c.get("reply") else "",
                "matched": matched, "query_terms": len(q),
            })
            if len(results) >= limit:
                break
        return results

    def recent(self, limit: int = 10, exclude: str | None = None) -> list[dict]:
        metas = [meta for meta, _ in self._load() if meta["id"] != exclude]
        metas.sort(key=lambda m: m.get("updated") or 0, reverse=True)
        return metas[:limit]

    def read(self, chat_id: str, start: int = 0, max_chars: int = 9000) -> str:
        if not re.fullmatch(r"[A-Za-z0-9-]+", chat_id or ""):
            raise KeyError(chat_id)
        path = self.folder / f"{chat_id}.json"
        if not path.is_file():
            raise KeyError(chat_id)
        conv = json.loads(path.read_text(encoding="utf-8"))
        lines = []
        for m in conv.get("messages", []):
            who = "You" if m.get("role") == "user" else "Corvis"
            lines.append(f"{who}: {m.get('text', '').strip()}")
        body = "\n\n".join(lines)
        piece = body[start:start + max_chars]
        where = "Corvis himself" if conv.get("mode") == "self" else conv.get("workspace", "")
        head = f"Chat \"{conv.get('title')}\" ({fmt_date(conv.get('updated', 0))}, working in {where})\n\n"
        more = (f"\n\n[Chat continues. Call read_chat with start={start + max_chars} to read more.]"
                if start + max_chars < len(body) else "")
        return head + piece + more


class Memory:
    def __init__(self, data_dir: str | Path):
        data_dir = Path(data_dir)
        self.facts = FactStore(data_dir / "memory")
        self.chats = ChatIndex(data_dir / "conversations")

    def recall(self, text: str, exclude: str | None = None, limit: int = 3) -> tuple[str, list[str]]:
        """Snippets from earlier chats worth attaching to a new message.

        Strict on purpose: weak matches would distract the model more than help.
        Returns (block for the model, chat titles used).
        """
        hits = []
        refers_back = bool(BACK_REFERENCE.search(text))
        for r in self.chats.search(text, limit=limit * 2, exclude=exclude, per_chat=1):
            if refers_back:  # "like we did last time": a modest match is enough
                ok = r["matched"] >= (1 if r["query_terms"] == 1 else 2) and r["score"] >= 1.0
            else:            # otherwise only an earlier chat that is clearly about the same thing
                ok = r["matched"] >= 3 and r["score"] >= 2.0
            if ok:
                hits.append(r)
            if len(hits) >= limit:
                break
        if not hits:
            return "", []
        lines = []
        for h in hits:
            line = f"- From \"{h['title']}\" ({h['date']}, chat {h['chat_id']}): {h['who']} said: {h['snippet']}"
            if h["reply"]:
                line += f"\n  Corvis replied: {h['reply']}"
            lines.append(line)
        block = ("\n\n[Recalled from earlier chats. Use only if it helps with the message above; "
                 "call read_chat for the full chat.]\n" + "\n".join(lines))
        titles = list(dict.fromkeys(h["title"] for h in hits))
        return block, titles
