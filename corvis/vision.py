"""Seeing images. Most coding models are blind, so Corvis hands pictures to a vision model
(e.g. qwen2.5vl or gemma3 in Ollama) and works from its description.

config.yaml:
  vision:
    model: qwen2.5vl:7b            # a model that can see images
    main_model_sees_images: false  # or: true if your main llm.model can see images itself
"""
from __future__ import annotations

import base64
import io
from pathlib import Path

from .llm import ChatLLM, LLMError

DESCRIBE_PROMPT = (
    "Describe this image for a software developer who can't see it. Transcribe every piece of "
    "visible text, code, error message, file path and number exactly. Then describe what matters: "
    "UI layout, game scene, 3D model, diagram, chart or photo contents. Be specific and factual; "
    "don't guess at things you can't see.")
MAX_SIDE = 1600


def _api_key(llm: dict) -> str:
    from .config import api_key
    return api_key(llm)


def vision_cfg(cfg: dict) -> dict | None:
    """Which model looks at images, or None if nothing can."""
    v = cfg.get("vision", {}) or {}
    llm = cfg.get("llm", {}) or {}
    model = (v.get("model") or "").strip()
    if not model and v.get("main_model_sees_images"):
        model = llm.get("model", "")
    if not model:
        return None
    return {
        "model": model,
        "base_url": v.get("base_url") or llm.get("base_url", "http://localhost:11434/v1"),
        "api_key": _api_key(llm),
        "timeout": int(v.get("timeout", 300)),
    }


def _image_data_url(path: Path, mime: str) -> str:
    data = path.read_bytes()
    try:  # Pillow is optional: shrink huge photos so they upload to the model quickly
        from PIL import Image
        img = Image.open(io.BytesIO(data))
        if max(img.size) > MAX_SIDE:
            img.thumbnail((MAX_SIDE, MAX_SIDE))
            buf = io.BytesIO()
            if img.mode in ("RGBA", "LA", "P"):
                img.save(buf, "PNG")
                mime = "image/png"
            else:
                img.convert("RGB").save(buf, "JPEG", quality=88)
                mime = "image/jpeg"
            data = buf.getvalue()
    except Exception:
        pass
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def look(path: Path, mime: str, cfg: dict, question: str = "") -> str:
    """Ask the vision model about an image. Raises LLMError with a helpful message on failure."""
    vc = vision_cfg(cfg)
    if vc is None:
        raise LLMError("No vision model is set up, so Corvis can't see images. Add one under "
                       "vision: in config.yaml (for example: ollama pull qwen2.5vl:7b, then "
                       "model: qwen2.5vl:7b).")
    llm = ChatLLM(base_url=vc["base_url"], model=vc["model"], api_key=vc["api_key"],
                  temperature=0.1, max_tokens=1500, timeout=vc["timeout"])
    prompt = question.strip() or DESCRIBE_PROMPT
    reply = llm.chat([{"role": "user", "content": [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": _image_data_url(path, mime)}},
    ]}])
    text = (reply.content or "").strip()
    if not text:
        raise LLMError(f"The vision model '{vc['model']}' returned nothing. Is it a model that can see images?")
    return text
