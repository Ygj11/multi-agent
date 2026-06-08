from __future__ import annotations

"""Load and expose the global intent taxonomy."""

from pathlib import Path
from typing import Any

import yaml

from app.schemas.intent_taxonomy import IntentTaxonomy


DEFAULT_TAXONOMY_PATH = Path(__file__).resolve().parents[1] / "config" / "intent_taxonomy.yaml"


class IntentTaxonomyLoader:
    """Small cached loader for `intent_taxonomy.yaml`."""

    def __init__(self, taxonomy_path: Path | str = DEFAULT_TAXONOMY_PATH) -> None:
        self.taxonomy_path = Path(taxonomy_path)
        self._taxonomy: IntentTaxonomy | None = None

    def load(self, force_reload: bool = False) -> IntentTaxonomy:
        """Load and validate the taxonomy."""
        if self._taxonomy is not None and not force_reload:
            return self._taxonomy
        if not self.taxonomy_path.exists():
            raise FileNotFoundError(f"intent taxonomy file not found: {self.taxonomy_path}")
        raw = yaml.safe_load(self.taxonomy_path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("intent taxonomy root must be a mapping")
        self._taxonomy = IntentTaxonomy(**raw)
        return self._taxonomy

    def list_allowed_intents(self) -> list[str]:
        """Return legal top-level intent values."""
        return self.load().allowed_intents()

    def list_candidate_sub_intents(self) -> dict[str, list[str]]:
        """Return legal sub-intents grouped by top-level intent."""
        return self.load().candidate_sub_intents()

    def is_allowed_intent(self, intent: str) -> bool:
        """True when `intent` exists in the taxonomy."""
        return self.load().is_allowed_intent(intent)

    def is_allowed_sub_intent(self, intent: str, sub_intent: str) -> bool:
        """True when `sub_intent` belongs to `intent` in the taxonomy."""
        return self.load().is_allowed_sub_intent(intent, sub_intent)

    def summaries_for_prompt(self) -> list[dict[str, Any]]:
        """Return compact prompt summaries."""
        return self.load().summaries_for_prompt()
