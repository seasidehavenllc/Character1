"""Model inventory and comparison helpers for OpenAI-compatible inference endpoints."""
from __future__ import annotations
import time
import requests
from .llm import ChatLLM
from .config import api_key


def inventory(cfg: dict) -> dict:
    llm = cfg.get("llm", {}) or {}
    base = str(llm.get("base_url", "http://localhost:11434/v1")).rstrip("/")
    key = api_key(llm)
    try:
        r = requests.get(base + "/models", headers={"Authorization": f"Bearer {key}"}, timeout=4)
        r.raise_for_status()
        data = r.json().get("data", [])
        models = [{"id": str(m.get("id", "")), "owned_by": str(m.get("owned_by", ""))} for m in data if m.get("id")]
        return {"online": True, "base_url": base, "models": models, "configured_model": llm.get("model", ""), "provider_type": "openai-compatible"}
    except (requests.RequestException, ValueError) as exc:
        return {"online": False, "base_url": base, "models": [], "configured_model": llm.get("model", ""), "provider_type": "openai-compatible", "error": str(exc)[:240]}


def compare(cfg: dict, prompt: str, model_ids: list[str]) -> dict:
    prompt = prompt.strip()
    if not prompt or len(prompt) > 12000: raise ValueError("Prompt is required and must be at most 12,000 characters.")
    if not isinstance(model_ids, list): raise ValueError("models must be a list.")
    model_ids = list(dict.fromkeys(str(x).strip() for x in model_ids if str(x).strip()))[:4]
    if not model_ids: raise ValueError("Select at least one model.")
    lcfg = cfg.get("llm", {}) or {}
    base = str(lcfg.get("base_url", "http://localhost:11434/v1"))
    key = api_key(lcfg)
    outputs = []
    for model in model_ids:
        started = time.monotonic()
        try:
            client = ChatLLM(base_url=base, model=model, api_key=key, temperature=0.2, max_tokens=4096, timeout=120, native_tools=False)
            reply = client.chat([{"role": "system", "content": "Answer the user's request accurately. State uncertainty and do not invent sources."}, {"role": "user", "content": prompt}])
            outputs.append({"model": model, "ok": True, "answer": reply.content, "elapsed_seconds": round(time.monotonic()-started, 2)})
        except Exception as exc:
            outputs.append({"model": model, "ok": False, "error": str(exc)[:600], "elapsed_seconds": round(time.monotonic()-started, 2)})
    return {"prompt": prompt, "results": outputs, "completed": sum(1 for x in outputs if x["ok"]), "total": len(outputs)}
