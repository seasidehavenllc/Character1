"""Persistent, source-aware belief ledger for Corvis.

Beliefs are claims Corvis currently considers plausible, not ground truth. Evidence
is recorded with provenance so later reasoning can revisit and revise conclusions.
"""
from __future__ import annotations
import json, time, uuid
from pathlib import Path
from threading import RLock
from typing import Any

class BeliefStore:
    def __init__(self, data_dir: str | Path):
        self.path = Path(data_dir) / "beliefs.json"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()
        if not self.path.exists(): self._write({"beliefs": []})

    def _read(self) -> dict:
        try:
            obj = json.loads(self.path.read_text(encoding="utf-8"))
            return obj if isinstance(obj, dict) and isinstance(obj.get("beliefs"), list) else {"beliefs": []}
        except (OSError, json.JSONDecodeError): return {"beliefs": []}

    def _write(self, obj: dict) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.path)

    def add(self, claim: str, *, confidence: float = 0.5, evidence: list[dict] | None = None,
            category: str = "general", source: str = "reasoning", belief_id: str | None = None) -> dict:
        claim = claim.strip()
        if not claim: raise ValueError("claim must not be empty")
        confidence = max(0.0, min(1.0, float(confidence)))
        now = time.time()
        item = {"id": belief_id or uuid.uuid4().hex, "claim": claim, "confidence": confidence,
                "category": category, "evidence": evidence or [], "source": source,
                "created_at": now, "updated_at": now, "history": []}
        with self._lock:
            data = self._read(); data["beliefs"].append(item); self._write(data)
        return item

    def revise(self, belief_id: str, claim: str | None = None, *, confidence: float | None = None,
               evidence: list[dict] | None = None, reason: str = "new evidence") -> dict:
        with self._lock:
            data = self._read()
            for item in data["beliefs"]:
                if item["id"] != belief_id: continue
                item["history"].append({"claim": item["claim"], "confidence": item["confidence"],
                    "evidence": item["evidence"], "reason": reason, "at": time.time()})
                if claim is not None: item["claim"] = claim.strip()
                if confidence is not None: item["confidence"] = max(0.0, min(1.0, float(confidence)))
                if evidence is not None: item["evidence"] = evidence
                item["updated_at"] = time.time(); self._write(data); return item
        raise KeyError(f"Unknown belief: {belief_id}")

    def search(self, query: str = "", limit: int = 10) -> list[dict]:
        terms = set(query.lower().split())
        items = self._read()["beliefs"]
        if terms:
            def score(item):
                hay = (item.get("claim", "") + " " + json.dumps(item.get("evidence", []))).lower()
                return sum(1 for t in terms if t in hay)
            # Best matches first, so keep the front of the list.
            return sorted((x for x in items if score(x)), key=score, reverse=True)[:max(1, limit)]
        return items[-max(1, limit):]  # no query: the most recent beliefs

    def delete(self, belief_id: str) -> bool:
        with self._lock:
            data = self._read(); old = len(data["beliefs"])
            data["beliefs"] = [x for x in data["beliefs"] if x.get("id") != belief_id]
            if len(data["beliefs"]) != old: self._write(data); return True
            return False

    def context(self, query: str, limit: int = 5) -> str:
        items = self.search(query, limit)
        if not items: return ""
        lines = ["Relevant recorded beliefs (treat as revisable claims, not facts):"]
        for x in items:
            lines.append(f"- {x['claim']} [confidence={x['confidence']:.2f}; source={x.get('source','unknown')}; id={x['id']}]")
            for ev in x.get("evidence", [])[:3]:
                if isinstance(ev, dict): lines.append(f"  Evidence: {ev.get('summary', str(ev))} (source: {ev.get('source','unspecified')})")
        return "\n".join(lines) + "\n"
