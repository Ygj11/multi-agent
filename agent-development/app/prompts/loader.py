from __future__ import annotations

"""UTF-8 prompt template loader."""

from collections import defaultdict
from pathlib import Path
from typing import Any


PROMPTS_ROOT = Path(__file__).resolve().parent


class _SafeFormatDict(defaultdict):
    def __missing__(self, key: str) -> str:
        return "{" + key + "}"


class PromptLoader:
    """Load prompt templates from app/prompts and render simple named variables."""

    def __init__(self, root: Path = PROMPTS_ROOT) -> None:
        self.root = Path(root)

    def load(self, relative_path: str) -> str:
        path = self._resolve(relative_path)
        return path.read_text(encoding="utf-8")

    def render(self, relative_path: str, **variables: Any) -> str:
        template = self.load(relative_path)
        values = _SafeFormatDict(str)
        values.update({key: self._stringify(value) for key, value in variables.items()})
        return template.format_map(values)

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
