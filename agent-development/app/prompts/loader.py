from __future__ import annotations

"""UTF-8 prompt template loader."""

from collections import defaultdict
from pathlib import Path
from typing import Any

from app.prompts.manifest import PromptManifest, PromptSceneManifest


PROMPTS_ROOT = Path(__file__).resolve().parent


class _SafeFormatDict(defaultdict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class PromptLoader:
    """Load prompt templates from app/prompts and render simple named variables."""

    def __init__(self, root: Path = PROMPTS_ROOT, manifest: PromptManifest | None = None) -> None:
        self.root = Path(root)
        self.manifest = manifest or PromptManifest.load(self.root / "manifest.yaml")

    def load(self, relative_path: str) -> str:
        path = self._resolve(relative_path)
        return path.read_text(encoding="utf-8")

    def render(self, relative_path: str, **variables: Any) -> str:
        template = self.load(relative_path)
        values = _SafeFormatDict(str)
        values.update({key: self._stringify(value) for key, value in variables.items()})
        return template.format_map(values)

    def scene(self, scene: str) -> PromptSceneManifest:
        return self.manifest.scene(scene)

    def render_scene_system(self, scene: str, **variables: Any) -> str:
        return self.render(self.scene(scene).system, **variables)

    def render_scene_user(self, scene: str, **variables: Any) -> str:
        user_prompt = self.scene(scene).user
        if not user_prompt:
            raise FileNotFoundError(f"prompt scene has no user template: {scene}")
        return self.render(user_prompt, **variables)

    def scene_trace(self, scene: str) -> dict[str, Any]:
        return self.scene(scene).trace()

    def _resolve(self, relative_path: str) -> Path:
        path = (self.root / relative_path).resolve()
        if not path.is_file() or not path.is_relative_to(self.root):
            raise FileNotFoundError(f"prompt template not found: {relative_path}")
        return path

    @staticmethod
    def _stringify(value: Any) -> str:
        if value is None:
            return ""
        return str(value)


default_prompt_loader = PromptLoader()
