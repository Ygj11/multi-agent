from __future__ import annotations

"""Policy-backed rule fallback for intent recognition."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml


DEFAULT_INTENT_FALLBACK_POLICY_PATH = Path(__file__).with_name("intent_fallback_policy.yaml")


@dataclass(frozen=True)
class IntentFallbackDecision:
    intent: str
    sub_intent: str | None
    confidence: float
    matched_keywords: list[str] = field(default_factory=list)
    matched_entity_hints: list[str] = field(default_factory=list)
    clarification_question: str | None = None


class IntentFallbackPolicy:
    """Classify fallback intent using declarative keyword/entity policy.

    ``keywords`` 和 ``entity_hints`` 是按需启用的匹配信号。某个 intent
    两者均未配置时不会被该兜底规则选中；未配置 ``default_sub_intent`` 时，
    不产生兜底 sub_intent。
    """

    policy_name = "intent_fallback_policy"

    def __init__(self, *, version: str, intents: dict[str, Any], unknown: dict[str, Any]) -> None:
        self.version = version
        self.intents = intents
        self.unknown = unknown

    @classmethod
    def load(cls, path: Path | str = DEFAULT_INTENT_FALLBACK_POLICY_PATH) -> "IntentFallbackPolicy":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("intent fallback policy root must be a mapping")
        intents = raw.get("intents") or {}
        if not isinstance(intents, dict):
            raise ValueError("intent fallback policy intents must be a mapping")
        unknown = raw.get("unknown") or {}
        if not isinstance(unknown, dict):
            raise ValueError("intent fallback policy unknown must be a mapping")
        return cls(version=str(raw.get("version") or "unknown"), intents=intents, unknown=unknown)

    def trace(self) -> dict[str, str]:
        return {"policy_name": self.policy_name, "policy_version": self.version}

    def classify(self, *, text: str, entities: dict[str, Any]) -> IntentFallbackDecision:
        for intent, definition in self.intents.items():
            if not isinstance(definition, dict):
                continue
            matched_keywords = self._matched_keywords(text, definition.get("keywords") or [])
            matched_entity_hints = self._matched_entity_hints(entities, definition.get("entity_hints") or [])
            if not matched_keywords and not matched_entity_hints:
                continue
            return IntentFallbackDecision(
                intent=str(intent),
                sub_intent=self._sub_intent(text=text, definition=definition),
                confidence=float(definition.get("confidence", 0.0) or 0.0),
                matched_keywords=matched_keywords,
                matched_entity_hints=matched_entity_hints,
            )
        return IntentFallbackDecision(
            intent="unknown",
            sub_intent=None,
            confidence=float(self.unknown.get("confidence", 0.42) or 0.42),
            clarification_question=str(self.unknown.get("clarification_question") or ""),
        )

    def _sub_intent(self, *, text: str, definition: dict[str, Any]) -> str | None:
        sub_intents = definition.get("sub_intents") or {}
        if isinstance(sub_intents, dict):
            for sub_intent, sub_definition in sub_intents.items():
                if isinstance(sub_definition, dict) and self._matched_keywords(text, sub_definition.get("keywords") or []):
                    return str(sub_intent)
        default_sub_intent = definition.get("default_sub_intent")
        return str(default_sub_intent) if default_sub_intent else None

    @staticmethod
    def _matched_keywords(text: str, keywords: list[Any]) -> list[str]:
        lower = text.lower()
        return [str(keyword) for keyword in keywords if str(keyword).lower() in lower]

    @staticmethod
    def _matched_entity_hints(entities: dict[str, Any], hints: list[Any]) -> list[str]:
        return [str(hint) for hint in hints if entities.get(str(hint)) not in (None, "", [])]
