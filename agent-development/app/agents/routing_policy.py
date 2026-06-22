from __future__ import annotations

"""Declarative policy for AgentCard routing and scoring."""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


DEFAULT_AGENT_ROUTING_POLICY_PATH = Path(__file__).with_name("routing_policy.yaml")


@dataclass(frozen=True)
class AgentRoutingPolicy:
    """AgentCard scoring weights and route thresholds."""

    version: str
    weights: dict[str, float]
    thresholds: dict[str, float]
    keyword_tokens: tuple[str, ...]
    clarification_question: str
    policy_name: str = "agent_routing_policy"

    @classmethod
    def load(cls, path: Path | str = DEFAULT_AGENT_ROUTING_POLICY_PATH) -> "AgentRoutingPolicy":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("agent routing policy root must be a mapping")
        weights = {str(key): float(value) for key, value in (raw.get("weights") or {}).items()}
        thresholds = {str(key): float(value) for key, value in (raw.get("thresholds") or {}).items()}
        return cls(
            version=str(raw.get("version") or "unknown"),
            weights=weights,
            thresholds=thresholds,
            keyword_tokens=tuple(str(item) for item in raw.get("keyword_tokens") or []),
            clarification_question=str(raw.get("clarification_question") or "请补充你希望处理的业务场景。"),
        )

    def trace(self) -> dict[str, str]:
        return {"policy_name": self.policy_name, "policy_version": self.version}

    def weight(self, name: str) -> float:
        return self.weights.get(name, 0.0)

    def threshold(self, name: str, default: float) -> float:
        return self.thresholds.get(name, default)

    def tokens(self, text: str) -> list[str]:
        separators = ",.;:，。；：|()[]{}<> \n\t"
        cleaned = text.lower()
        for sep in separators:
            cleaned = cleaned.replace(sep, " ")
        tokens = {item.strip() for item in cleaned.split() if len(item.strip()) >= 2}
        lower = text.lower()
        for keyword in self.keyword_tokens:
            if keyword in lower:
                tokens.add(keyword)
        return sorted(tokens)
