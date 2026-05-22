from __future__ import annotations

"""AgentCard loading and rule-based matching."""

import json
from pathlib import Path
from typing import Any

from app.observability.logger import log_event
from app.schemas.agent_card import AgentCard, AgentCandidate
from app.skills.catalog import SkillCatalog


class AgentCardLoader:
    """Loads AgentCards and exposes discovery/matching APIs."""

    def __init__(self, cards_root: Path) -> None:
        self.cards_root = cards_root
        self._cards: dict[str, AgentCard] = {}
        self._loaded = False

    def load_all(self, force_reload: bool = False) -> list[AgentCard]:
        """Load and validate all cards from disk."""
        if self._loaded and not force_reload:
            return list(self._cards.values())

        cards: dict[str, AgentCard] = {}
        if self.cards_root.exists():
            for path in sorted(self.cards_root.glob("*.yaml")):
                raw = _parse_card_yaml(path.read_text(encoding="utf-8"))
                card = AgentCard(**raw)
                cards[card.agent_name] = card

        self._cards = cards
        self._loaded = True
        log_event(
            "agent_cards_loaded",
            node="agent_card_loader",
            message="Agent cards loaded",
            data={"agent_count": len(cards), "agents": sorted(cards)},
        )
        return list(cards.values())

    def list_available_agents(self) -> list[AgentCard]:
        """Return enabled cards only."""
        return [card for card in self.load_all() if card.enabled]

    def get_agent_card(self, agent_name: str) -> AgentCard | None:
        """Return one card by name."""
        self.load_all()
        return self._cards.get(agent_name)

    def match_candidates(
        self,
        intent: str,
        entities: dict[str, Any],
        query: str,
    ) -> list[AgentCandidate]:
        """Score cards using intent, entity, capability, keyword, and enabled signals."""
        candidates: list[AgentCandidate] = []
        query_l = query.lower()
        entity_keys = {key for key, value in entities.items() if value}

        for card in self.list_available_agents():
            score = 0.0
            reasons: list[str] = []
            missing_entities = [name for name in card.required_entities if name not in entity_keys]

            if intent in card.supported_intents:
                score += 5
                reasons.append(f"intent matched: {intent}")

            if card.required_entities:
                matched = len(card.required_entities) - len(missing_entities)
                score += matched * 2
                if matched:
                    reasons.append(f"required entities matched: {matched}")
            else:
                score += 1
                reasons.append("no required entities")

            for capability in card.capabilities:
                normalized = capability.replace("_", " ").lower()
                if capability.lower() in query_l or normalized in query_l:
                    score += 1.5
                    reasons.append(f"capability keyword matched: {capability}")

            card_text = " ".join(
                [
                    card.agent_name,
                    card.display_name,
                    card.description,
                    " ".join(card.capabilities),
                    " ".join(card.supported_intents),
                    " ".join(card.rag_namespaces),
                ]
            ).lower()
            for token in _tokens(query):
                if token in card_text:
                    score += 1
                    reasons.append(f"keyword matched: {token}")

            if card.enabled:
                score += 0.5
                reasons.append("enabled")

            candidates.append(
                AgentCandidate(
                    agent_name=card.agent_name,
                    card=card,
                    score=score,
                    reason="; ".join(reasons) or "no match",
                    missing_entities=missing_entities,
                )
            )

        candidates.sort(key=lambda item: item.score, reverse=True)
        return candidates

    def validate_with_skill_catalog(self, skill_catalog: SkillCatalog) -> None:
        """Validate AgentCard declarations against SkillCatalog metadata."""
        cards = {card.agent_name: card for card in self.load_all()}
        skills = skill_catalog.scan(force_reload=True)
        skills_by_id = {skill.skill_id: skill for skill in skills}
        errors: list[str] = []

        for card in cards.values():
            enabled_agent_skills = skill_catalog.list_skills(card.agent_name)
            if not any(skill.is_default for skill in enabled_agent_skills):
                errors.append(f"{card.agent_name} must have at least one enabled default skill")

            for skill_id in card.skills:
                skill = skills_by_id.get(skill_id)
                if skill is None:
                    errors.append(f"{card.agent_name} declares missing skill_id {skill_id}")
                    continue
                if skill.agent != card.agent_name:
                    errors.append(f"{skill_id} agent {skill.agent} does not match card {card.agent_name}")
                extra_tools = sorted(set(skill.private_tools) - set(card.private_tools))
                if extra_tools:
                    errors.append(f"{skill_id} declares private tools outside AgentCard: {extra_tools}")

        for skill in skills:
            if skill.agent not in cards:
                errors.append(f"{skill.skill_id} references unknown AgentCard agent {skill.agent}")

        if errors:
            raise ValueError("; ".join(errors))


def _tokens(text: str) -> list[str]:
    separators = ",.;:，。；：|()[]{}<> \n\t"
    cleaned = text.lower()
    for sep in separators:
        cleaned = cleaned.replace(sep, " ")
    tokens = {item.strip() for item in cleaned.split() if len(item.strip()) >= 2}
    for keyword in [
        "troubleshooting",
        "refund",
        "callback",
        "claim",
        "policy",
        "status",
        "privacy",
        "compliance",
        "e102",
        "submitproposal",
        "requestid",
        "request_id",
    ]:
        if keyword in text.lower():
            tokens.add(keyword)
    return sorted(tokens)


def _parse_card_yaml(text: str) -> dict[str, Any]:
    """Parse the small YAML subset used by AgentCard files.

    Inline JSON is supported for nested fields such as memory_policy/examples.
    """
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            result.setdefault(current_key, []).append(_parse_scalar(stripped[2:].strip()))
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            if value:
                result[current_key] = _parse_scalar(value)
            else:
                result[current_key] = []
    return result


def _parse_scalar(value: str) -> Any:
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.startswith(("{", "[")):
        return json.loads(value)
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value
