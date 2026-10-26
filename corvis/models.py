"""The models Corvis can switch between: local models on this device, plus optional cloud models."""

from __future__ import annotations

import json
import re
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from .hardware import DeviceInfo, detect

if TYPE_CHECKING:
    from .account import Account

MODELS_FILE = Path(__file__).resolve().parent.parent / "config" / "models.yaml"


@dataclass(frozen=True)
class ModelConfig:
    id: str
    label: str
    provider: str            # "local", "home", "auto", "anthropic" or "openai"
    description: str = ""
    base_url: str = ""       # local / home models: the OpenAI-compatible server address
    api_key: str = ""        # home models: the account session token
    api_model: str = ""      # name to send to the server, if different from id
    fallbacks: bool = False  # anthropic only
    web_tools: bool = False  # anthropic only

    @property
    def group(self) -> str:
        return {"auto": "Auto", "local": "This device", "home": "Home PC"}.get(self.provider, "Cloud")


AUTO = ModelConfig("auto", "Auto", "auto", "Home PC when it's reachable, this device when it isn't")


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


VISION_HINTS = ("vision", "llava", "-vl", "vl:", "qwen2.5vl", "gemma3", "moondream", "minicpm-v", "bakllava")


def supports_vision(model: ModelConfig | None) -> bool:
    """Can this model look at images? Cloud models can; local ones only if they're vision models."""
    if model is None:
        return False
    if model.provider in ("anthropic", "openai"):
        return True
    name = (model.api_model or model.id).lower()
    return any(h in name for h in VISION_HINTS)


def best_fit(ids: list[str], device: DeviceInfo) -> str:
    """The recommended model if installed, else the largest that fits in memory (~0.75 GB per billion params)."""
    if device.recommended_model in ids:
        return device.recommended_model
    fits = [m for m in ids if _size_b(m) * 0.75 <= device.ram_gb * 0.7] or ids
    return max(fits, key=_size_b)


class ModelCatalog:
    HUB_RECHECK_S = 20

    def __init__(self, cloud: list[ModelConfig], local_server: str = "", default: str = "auto",
                 device: DeviceInfo | None = None, account: "Account | None" = None):
        self.cloud = cloud
        self.local_server = local_server
        self.default_setting = default
        self.device = device or detect()
        self.account = account
        self.local: list[ModelConfig] = []
        self.home: list[ModelConfig] = []
        self._home_checked = 0.0
        self.refresh()

    @classmethod
    def load(cls, path: str | Path = MODELS_FILE, account: "Account | None" = None) -> "ModelCatalog":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        cloud = [ModelConfig(**m) for m in data.get("cloud", [])]
        return cls(cloud, data.get("local", {}).get("server", ""), data.get("default", "auto"), account=account)

    def refresh(self) -> None:
        """Re-check which models are installed on this device and on the home PC."""
        if self.local_server:
            self.local = [
                ModelConfig(name, name, "local", "Runs on this device", base_url=self.local_server)
                for name in list_local_models(self.local_server)
            ]
        self.refresh_home(force=True)

    def refresh_home(self, force: bool = False) -> None:
        if not force and time.time() - self._home_checked < self.HUB_RECHECK_S:
            return
        self._home_checked = time.time()
        acct = self.account
        if acct is None or not acct.signed_in or not acct.check_hub():
            self.home = []
            return
        self.home = [
            ModelConfig(f"home:{name}", f"{name} · Home PC", "home", "Runs on your home PC",
                        base_url=acct.hub_url + "/brain/v1", api_key=acct.token, api_model=name)
            for name in acct.hub_models()
        ]

    def list(self) -> list[ModelConfig]:
        auto = [AUTO] if (self.local or self.home or (self.account and self.account.signed_in)) else []
        return auto + self.home + self.local + self.cloud

    def get(self, model_id: str) -> ModelConfig:
        for m in self.list():
            if m.id == model_id:
                return m
        raise KeyError(f"Unknown model {model_id!r}. Options: {', '.join(m.id for m in self.list())}")

    def resolve_auto(self) -> ModelConfig:
        """Pick where to think right now: home PC if reachable, else this device, else cloud."""
        self.refresh_home()
        if self.home:
            # The PC is usually the strongest device: take its largest model.
            return max(self.home, key=lambda m: _size_b(m.api_model))
        if self.local:
            return self.get(best_fit([m.id for m in self.local], self.device))
        if self.cloud:
            return self.cloud[0]
        raise RuntimeError("No models available: the home PC is offline and no model is installed on this "
                           "device. Install Ollama and pull a model (see README).")

    @property
    def default(self) -> str:
        if self.default_setting != "auto":
            return self.default_setting
        if self.local or self.home or (self.account and self.account.signed_in):
            return "auto"
        if self.cloud:
            return self.cloud[0].id
        raise RuntimeError("No models available. Install Ollama and pull a model (see README).")
