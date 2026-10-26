"""Voice input: turn recorded speech into text on this PC with Whisper (faster-whisper).

Optional: install with Install_Voice.bat (pip install faster-whisper). The first use
downloads the speech model once (base is about 150 MB). After that it works offline.
Without it, the chat app can fall back to the browser's own speech recognition.
"""
from __future__ import annotations

import importlib.util
import os
import tempfile
import threading

_model = None
_model_name = None
_lock = threading.Lock()


def voice_cfg(cfg: dict) -> dict:
    v = cfg.get("voice", {}) or {}
    return {"engine": str(v.get("speech_to_text", "auto")).lower(),   # auto | local | browser | off
            "model": v.get("whisper_model", "base"),
            "device": v.get("device", "auto"),
            "language": v.get("language") or None}


def local_available() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def engine(cfg: dict) -> str:
    """Which speech-to-text the chat app should use: 'local', 'browser' or 'off'."""
    e = voice_cfg(cfg)["engine"]
    if e == "off":
        return "off"
    if e == "browser":
        return "browser"
    if e == "local":
        return "local" if local_available() else "off"
    return "local" if local_available() else "browser"


def _load(cfg: dict):
    global _model, _model_name
    vc = voice_cfg(cfg)
    if _model is None or _model_name != vc["model"]:
        from faster_whisper import WhisperModel
        compute = "int8" if vc["device"] == "cpu" else "default"
        _model = WhisperModel(vc["model"], device=vc["device"], compute_type=compute)
        _model_name = vc["model"]
    return _model


def transcribe(audio: bytes, cfg: dict, suffix: str = ".webm") -> str:
    if not local_available():
        raise RuntimeError("Voice input on this PC isn't installed. Double-click Install_Voice.bat.")
    fd, path = tempfile.mkstemp(suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(audio)
        with _lock:  # one transcription at a time; the model isn't thread-safe
            model = _load(cfg)
            segments, _info = model.transcribe(path, language=voice_cfg(cfg)["language"],
                                               vad_filter=True, beam_size=5)
            return " ".join(s.text.strip() for s in segments).strip()
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass
