from __future__ import annotations

"""Configurable scoring weights for metadata-only skill selection."""

from dataclasses import dataclass, field
from pathlib import Path


DEFAULT_SCORING_POLICY_PATH = Path(__file__).with_name("scoring_policy.yaml")


@dataclass(frozen=True)
class SkillScoringPolicy:
    """Named scoring weights used by SkillRuleScorer.

    YAML 按字段覆盖内置基线；未配置的权重保留基线值，而不是关闭对应打分规则。
    """

    weights: dict[str, float] = field(default_factory=dict)

    @classmethod
    def default(cls) -> "SkillScoringPolicy":
        return cls(
            weights={
                "intent_tag_match": 3.0,
                "sub_intent_tag_match": 3.0,
                "intent_tag_keyword_match": 2.0,
                "description_keyword_match": 1.0,
                "required_entity_present": 2.0,
                "optional_entity_present": 1.0,
                "required_context_present": 1.0,
                "business_domain_match": 1.0,
                "error_code_match": 3.0,
                "routing_keyword_match": 4.0,
                "routing_negative_keyword_match": -4.0,
            }
        )

    @classmethod
    def load(cls, path: Path = DEFAULT_SCORING_POLICY_PATH) -> "SkillScoringPolicy":
        policy = cls.default()
        if not path.exists():
            return policy
        return cls(weights={**policy.weights, **_load_weights(path)})

    def weight(self, name: str) -> float:
        return float(self.weights.get(name, 0.0))


def _load_weights(path: Path) -> dict[str, float]:
    """Load a small YAML subset: weights: followed by numeric key/value pairs."""
    weights: dict[str, float] = {}
    section: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.endswith(":"):
            section = line[:-1].strip()
            continue
        if section != "weights" or ":" not in line:
            continue
        key, value = line.split(":", 1)
        try:
            weights[key.strip()] = float(value.strip())
        except ValueError as exc:
            raise ValueError(f"{path} has non-numeric skill scoring weight for {key.strip()}") from exc
    return weights
