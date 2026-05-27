from __future__ import annotations

"""YAML-configured generic entity extraction."""

import re
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Pattern

from app.schemas.entities import EntityBag, EntityMention


@dataclass(frozen=True)
class EntityPattern:
    """Compiled entity pattern from app/query/entity_patterns.yaml."""

    entity_type: str
    description: str
    regex: tuple[Pattern[str], ...]
    normalized_type: str = "string"
    keyword_allowlist: tuple[str, ...] = ()
    sensitive: bool = False
    confidence: float = 1.0


class EntityPatternLoader:
    """Loads and validates generic entity regex rules."""

    REQUIRED_PATTERN_FIELDS = {"entity_type", "description", "regex"}

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).with_name("entity_patterns.yaml")

    def load(self) -> list[EntityPattern]:
        """Read YAML, validate fields, and compile regex rules."""
        if not self.path.exists():
            raise ValueError(f"entity pattern file not found: {self.path}")
        raw = self._parse_patterns_yaml(self.path.read_text(encoding="utf-8"))
        patterns = raw.get("patterns")
        if not isinstance(patterns, list):
            raise ValueError(f"{self.path} must contain a patterns list")

        compiled: list[EntityPattern] = []
        for index, item in enumerate(patterns):
            if not isinstance(item, dict):
                raise ValueError(f"{self.path} patterns[{index}] must be a mapping")
            missing = sorted(self.REQUIRED_PATTERN_FIELDS - set(item))
            if missing:
                raise ValueError(f"{self.path} patterns[{index}] missing required fields: {missing}")
            regex_values = item["regex"]
            if not isinstance(regex_values, list) or not regex_values:
                raise ValueError(f"{self.path} patterns[{index}].regex must be a non-empty list")
            try:
                regex = tuple(re.compile(str(pattern), flags=re.IGNORECASE) for pattern in regex_values)
            except re.error as exc:
                raise ValueError(f"{self.path} patterns[{index}] invalid regex: {exc}") from exc
            compiled.append(
                EntityPattern(
                    entity_type=str(item["entity_type"]),
                    description=str(item["description"]),
                    regex=regex,
                    normalized_type=str(item.get("normalized_type") or "string"),
                    keyword_allowlist=tuple(str(value) for value in item.get("keyword_allowlist", [])),
                    sensitive=self._as_bool(item.get("sensitive", False)),
                    confidence=float(item.get("confidence", 1.0)),
                )
            )
        return compiled

    @staticmethod
    def _parse_patterns_yaml(text: str) -> dict[str, Any]:
        """Parse the small YAML subset used by entity_patterns.yaml."""
        result: dict[str, Any] = {}
        patterns: list[dict[str, Any]] = []
        current_pattern: dict[str, Any] | None = None
        current_list_key: str | None = None

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "patterns:":
                result["patterns"] = patterns
                current_pattern = None
                current_list_key = None
                continue
            if stripped.startswith("- entity_type:"):
                current_pattern = {"entity_type": _parse_scalar(stripped.split(":", 1)[1].strip())}
                patterns.append(current_pattern)
                current_list_key = None
                continue
            if current_pattern is not None and stripped.startswith("- ") and current_list_key:
                current_pattern.setdefault(current_list_key, []).append(_parse_scalar(stripped[2:].strip()))
                continue
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip()
                if current_pattern is None:
                    result[key] = _parse_scalar(value) if value else []
                    continue
                if value:
                    current_pattern[key] = _parse_scalar(value)
                    current_list_key = None
                else:
                    current_pattern[key] = []
                    current_list_key = key
        result.setdefault("patterns", patterns)
        return result

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class EntityExtractor:
    """Generic rule extractor that is not tied to any Agent."""

    def __init__(self, patterns: list[EntityPattern] | None = None, loader: EntityPatternLoader | None = None) -> None:
        self.patterns = patterns if patterns is not None else (loader or EntityPatternLoader()).load()

    def extract(self, text: str | None, source: str = "current_query", turn_id: str | None = None) -> EntityBag:
        """Extract entities from text. Empty input returns an empty bag."""
        bag = EntityBag()
        if not text:
            return bag
        for pattern in self.patterns:
            for regex in pattern.regex:
                for match in regex.finditer(text):
                    value = self._match_value(match)
                    if not value or not self._allow_value(pattern, value):
                        continue
                    normalized = self._normalize(pattern, value)
                    bag.add(
                        EntityMention(
                            type=pattern.entity_type,
                            value=value,
                            normalized_value=normalized,
                            confidence=pattern.confidence,
                            source=source,
                            turn_id=turn_id,
                            sensitive=pattern.sensitive,
                            metadata={"description": pattern.description},
                        )
                    )
        return bag

    def extract_from_summary(self, summary: str | None) -> EntityBag:
        """Extract from short-term memory summary."""
        return self.extract(summary, source="summary")

    def extract_from_recent_turns(self, turns: list[dict[str, Any]] | None) -> EntityBag:
        """Extract from recent user/assistant turns."""
        bag = EntityBag()
        for index, turn in enumerate(turns or []):
            content = str(turn.get("content", ""))
            turn_id = str(turn.get("id") or turn.get("message_id") or index)
            bag.merge(self.extract(content, source="recent_turn", turn_id=turn_id))
        return bag

    @staticmethod
    def _match_value(match: re.Match[str]) -> str:
        if match.groups():
            for group in match.groups():
                if group:
                    return group.strip()
        return match.group(0).strip()

    @staticmethod
    def _allow_value(pattern: EntityPattern, value: str) -> bool:
        """Apply entity-specific allowlist rules, e.g. for policy_no we require a specific numeric format to reduce false positives."""
        if pattern.entity_type == "policy_no":
            if re.fullmatch(r"1[3-9]\d{9}", value) or re.fullmatch(r"\d{17}[0-9Xx]", value):
                return False
        if not pattern.keyword_allowlist:
            return True
        return value in pattern.keyword_allowlist

    @staticmethod
    def _normalize(pattern: EntityPattern, value: str) -> str:
        """Apply entity-specific normalization rules, e.g. for error_code we convert to uppercase to unify different casings."""
        if pattern.normalized_type == "string":
            return value.strip()
        return value.strip()


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        try:
            return json.loads(value) if value.startswith('"') else value[1:-1]
        except json.JSONDecodeError:
            return value[1:-1]
    return value
