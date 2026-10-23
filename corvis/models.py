"""The list of AI models Corvis can switch between (config/models.yaml)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

MODELS_FILE = Path(__file__).resolve().parent.parent / "config" / "models.yaml"


@dataclass(frozen=True)
class ModelConfig:
    id: str
    label: str
    provider: str
    description: str = ""
    fallbacks: bool = False
    web_tools: bool = False


class ModelCatalog:
    def __init__(self, models: list[ModelConfig], default: str):
        self.models = {m.id: m for m in models}
        self.default = default if default in self.models else next(iter(self.models))

    @classmethod
    def load(cls, path: str | Path = MODELS_FILE) -> "ModelCatalog":
        with open(path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
        models = [ModelConfig(**m) for m in data["models"]]
        return cls(models, data.get("default", models[0].id))

    def get(self, model_id: str) -> ModelConfig:
        if model_id not in self.models:
            raise KeyError(f"Unknown model {model_id!r}. Options: {', '.join(self.models)}")
        return self.models[model_id]

    def list(self) -> list[ModelConfig]:
        return list(self.models.values())
