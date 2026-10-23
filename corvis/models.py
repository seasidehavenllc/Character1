"""The models Corvis can switch between: local models on this device, plus optional cloud models."""

from __future__ import annotations

import json
import re
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from .hardware import DeviceInfo, detect

MODELS_FILE = Path(__file__).resolve().parent.parent / "config" / "models.yaml"


@dataclass(frozen=True)
class ModelConfig:
    id: str
    label: str
    provider: str            # "local", "anthropic" or "openai"
    description: str = ""
    base_url: str = ""       # local models: the OpenAI-compatible server address
    fallbacks: bool = False  # anthropic only
    web_tools: bool = False  # anthropic only

    @property
    def group(self) -> str:
        return "This device" if self.provider == "local" else "Cloud"


def list_local_models(server: str, timeout: float = 2.0) -> list[str]:
    """Ask a local OpenAI-compatible server (Ollama, LM Studio, llama.cpp...) which models it has."""
    try:
        with urllib.request.urlopen(server.rstrip("/") + "/models", timeout=timeout) as resp:
            data = json.load(resp)
        return [m["id"] for m in data.get("data", [])]
    except (OSError, ValueError, KeyError):
        return []


def _size_b(model_id: str) -> float:
    """Parameter count from a tag like 'qwen2.5-coder:7b' (0 if unknown)."""
    m = re.search(r"(\d+(?:\.\d+)?)b\b", model_id.lower())
    return float(m.group(1)) if m else 0.0


class ModelCatalog:
    def __init__(self, cloud: list[ModelConfig], local_server: str = "", default: str = "auto",
                 device: DeviceInfo | None = None):
        self.cloud = cloud
        self.local_server = local_server
        self.default_setting = default
        self.device = device or detect()
        self.local: list[ModelConfig] = []
        self.refresh()

    @classmethod
    def load(cls, path: str | Path = MODELS_FILE) -> "ModelCatalog":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cloud = [ModelConfig(**m) for m in data.get("cloud", [])]
        return cls(cloud, data.get("local", {}).get("server", ""), data.get("default", "auto"))

    def refresh(self) -> None:
        """Re-check which models are installed on this device."""
        if not self.local_server:
            return
        self.local = [
            ModelConfig(name, name, "local", "Runs on this device", base_url=self.local_server)
            for name in list_local_models(self.local_server)
        ]

    def list(self) -> list[ModelConfig]:
        return self.local + self.cloud

    def get(self, model_id: str) -> ModelConfig:
        for m in self.list():
            if m.id == model_id:
                return m
        raise KeyError(f"Unknown model {model_id!r}. Options: {', '.join(m.id for m in self.list())}")

    @property
    def default(self) -> str:
        if self.default_setting != "auto":
            return self.default_setting
        if self.local:
            ids = [m.id for m in self.local]
            if self.device.recommended_model in ids:
                return self.device.recommended_model
            # Otherwise the largest installed model that fits in memory (~0.75 GB per billion params at 4-bit).
            fits = [m for m in ids if _size_b(m) * 0.75 <= self.device.ram_gb * 0.7] or ids
            return max(fits, key=_size_b)
        if self.cloud:
            return self.cloud[0].id
        raise RuntimeError("No models available. Install Ollama and pull a model (see README).")
