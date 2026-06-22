from __future__ import annotations

"""Prompt manifest loading and validation."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator

from app.llm.output_schemas import SCHEMA_REGISTRY


PROMPTS_ROOT = Path(__file__).resolve().parent
DEFAULT_PROMPT_MANIFEST_PATH = PROMPTS_ROOT / "manifest.yaml"


class PromptSceneManifest(BaseModel):
    scene: str = ""
    version: str
    system: str
    user: str | None = None
    output_schema: str
    eval_suite: str
    default_model: str = "configured-default"
    tools_allowed: bool = False

    @model_validator(mode="after")
    def validate_text_fields(self) -> "PromptSceneManifest":
        if not self.version.strip():
            raise ValueError("prompt scene version is required")
        if not self.system.strip():
            raise ValueError("system prompt path is required")
        if not self.output_schema.strip():
            raise ValueError("output_schema is required")
        if not self.eval_suite.strip():
            raise ValueError("eval_suite is required")
        return self

    def trace(self) -> dict[str, Any]:
        return {
            "prompt_scene": self.scene,
            "prompt_version": self.version,
            "output_schema": self.output_schema,
            "eval_suite": self.eval_suite,
        }


class PromptManifest(BaseModel):
    version: str
    scenes: dict[str, PromptSceneManifest] = Field(default_factory=dict)

    @model_validator(mode="after")
    def attach_scene_names(self) -> "PromptManifest":
        if not self.version.strip():
            raise ValueError("prompt manifest version is required")
        if not self.scenes:
            raise ValueError("prompt manifest must declare scenes")
        for scene, manifest in self.scenes.items():
            manifest.scene = scene
        return self

    @classmethod
    def load(cls, path: Path | str = DEFAULT_PROMPT_MANIFEST_PATH) -> "PromptManifest":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("prompt manifest root must be a mapping")
        return cls(**raw)

    def scene(self, scene: str) -> PromptSceneManifest:
        try:
            return self.scenes[scene]
        except KeyError as exc:
            raise KeyError(f"prompt scene not found: {scene}") from exc

    def validate_assets(self, prompts_root: Path = PROMPTS_ROOT) -> list[str]:
        errors: list[str] = []
        for scene, manifest in self.scenes.items():
            for label, relative_path in (("system", manifest.system), ("user", manifest.user)):
                if not relative_path:
                    continue
                path = (prompts_root / relative_path).resolve()
                if not path.is_file() or not path.is_relative_to(prompts_root):
                    errors.append(f"{scene}.{label} prompt not found: {relative_path}")
            if manifest.output_schema not in SCHEMA_REGISTRY and manifest.output_schema not in {"text", "SubAgentResult", "VerificationResult"}:
                errors.append(f"{scene} references unknown output_schema: {manifest.output_schema}")
        return errors
