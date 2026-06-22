from __future__ import annotations

"""AgentCard loading and rule-based matching."""

from pathlib import Path
from typing import Any

import yaml

from app.agents.routing_policy import AgentRoutingPolicy
from app.observability.logger import log_event
from app.schemas.agent_card import AgentCard, AgentCandidate
from app.schemas.intent_taxonomy import IntentTaxonomy
from app.skills.catalog import SkillCatalog


class AgentCardLoader:
    """Loads AgentCards and exposes discovery/matching APIs."""

    def __init__(self, cards_root: Path, routing_policy: AgentRoutingPolicy | None = None) -> None:
        self.cards_root = cards_root
        self.routing_policy = routing_policy or AgentRoutingPolicy.load()
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
        sub_intent: str | None = None,
    ) -> list[AgentCandidate]:
        """Score cards using intent, entity, capability, keyword, and enabled signals."""
        candidates: list[AgentCandidate] = []
        query_l = query.lower()
        entity_keys = {key for key, value in entities.items() if value not in (None, "", [])}

        for card in self.list_available_agents():
            score = 0.0
            reasons: list[str] = []
            routes = card.normalized_supported_routes()
            # 实体包中，卡片缺失的实体
            missing_entities = [name for name in card.required_entities if name not in entity_keys]
            matched_entities: list[str] = []

            if intent in routes:
                score += self.routing_policy.weight("intent_match")
                reasons.append(f"intent matched: {intent}")
            elif intent != "unknown" and intent in " ".join(card.capabilities + [card.description]):
                score += self.routing_policy.weight("intent_capability_keyword")
                reasons.append(f"intent keyword matched capability: {intent}")

            if sub_intent:
                route_sub_intents = routes.get(intent, []) if intent != "unknown" else [item for values in routes.values() for item in values]
                card_sub_intents = {item.lower() for item in route_sub_intents}
                if sub_intent.lower() in card_sub_intents:
                    score += self.routing_policy.weight("sub_intent_match")
                    reasons.append(f"sub_intent matched: {sub_intent}")

            if card.required_entities:
                matched = len(card.required_entities) - len(missing_entities)
                score += matched * self.routing_policy.weight("required_entity_present")
                if matched:
                    matched_entities.extend([name for name in card.required_entities if name in entity_keys])
                    reasons.append(f"required entities matched: {matched}")
                if missing_entities:
                    score += len(missing_entities) * self.routing_policy.weight("required_entity_missing")
                    reasons.append(f"required entities missing: {missing_entities}")
            else:
                score += self.routing_policy.weight("no_required_entities")
                reasons.append("no required entities")

            optional_matches = [name for name in card.optional_entities if name in entity_keys]
            if optional_matches:
                matched_entities.extend(optional_matches)
                score += len(optional_matches) * self.routing_policy.weight("optional_entity_present")
                reasons.append(f"optional entities matched: {optional_matches}")

            for capability in card.capabilities:
                normalized = capability.replace("_", " ").lower()
                if capability.lower() in query_l or normalized in query_l:
                    score += self.routing_policy.weight("capability_keyword")
                    reasons.append(f"capability keyword matched: {capability}")

            card_text = " ".join(
                [
                    card.agent_name,
                    card.display_name,
                    card.description,
                    " ".join(card.capabilities),
                    " ".join(card.supported_intents),
                    " ".join(card.supported_sub_intents),
                    " ".join(card.normalized_supported_routes()),
                    " ".join(item for values in card.normalized_supported_routes().values() for item in values),
                    " ".join(card.optional_entities),
                    " ".join(card.rag_namespaces),
                    " ".join(str(example.get("query", "")) for example in card.examples),
                ]
            ).lower()
            for token in self.routing_policy.tokens(query):
                if token in card_text:
                    score += self.routing_policy.weight("query_keyword")
                    reasons.append(f"keyword matched: {token}")

            if card.enabled:
                score += self.routing_policy.weight("enabled")
                reasons.append("enabled")

            candidates.append(
                AgentCandidate(
                    agent_name=card.agent_name,
                    card=card,
                    score=score,
                    reason="; ".join(reasons) or "no match",
                    missing_entities=missing_entities,
                    matched_entities=sorted(set(matched_entities)),
                )
            )

        candidates.sort(key=lambda item: (-item.score, item.agent_name))
        return candidates

    def validate_with_skill_catalog(self, skill_catalog: SkillCatalog) -> None:
        """Validate AgentCard declarations against SkillCatalog metadata."""
        cards = {card.agent_name: card for card in self.load_all()}
        skills = skill_catalog.scan(force_reload=True)
        skills_by_id = {skill.skill_id: skill for skill in skills}
        errors: list[str] = []

        for card in cards.values():
            for skill_id in card.skills:
                skill = skills_by_id.get(skill_id)
                if skill is None:
                    errors.append(f"{card.agent_name} declares missing skill_id {skill_id}")
                    continue
                if skill.agent != card.agent_name:
                    errors.append(f"{skill_id} agent {skill.agent} does not match card {card.agent_name}")
                routes = card.normalized_supported_routes()
                if skill.intent and skill.intent not in routes:
                    errors.append(f"{skill_id} intent {skill.intent} is outside AgentCard supported_routes")
                for sub_intent in skill.sub_intents:
                    if skill.intent and sub_intent not in set(routes.get(skill.intent, [])):
                        errors.append(f"{skill_id} sub_intent {skill.intent}.{sub_intent} is outside AgentCard supported_routes")
                extra_tools = sorted(set(skill.private_tools) - set(card.private_tools))
                if extra_tools:
                    errors.append(f"{skill_id} declares private tools outside AgentCard: {extra_tools}")

        for skill in skills:
            if skill.agent not in cards:
                errors.append(f"{skill.skill_id} references unknown AgentCard agent {skill.agent}")

        if errors:
            raise ValueError("; ".join(errors))

    def validate_with_intent_taxonomy(self, taxonomy: IntentTaxonomy, *, require_full_coverage: bool = False) -> None:
        """Validate AgentCard routes and examples against the global taxonomy."""
        errors: list[str] = []
        for card in self.load_all():
            for intent, sub_intents in card.normalized_supported_routes().items():
                if not taxonomy.is_allowed_intent(intent):
                    errors.append(f"{card.agent_name} references unknown intent {intent}")
                    continue
                for sub_intent in sub_intents:
                    if not taxonomy.is_allowed_sub_intent(intent, sub_intent):
                        errors.append(f"{card.agent_name} references invalid sub_intent {intent}.{sub_intent}")
            for example in card.examples:
                example_intent = example.get("intent")
                example_sub_intent = example.get("sub_intent")
                if example_intent and not taxonomy.is_allowed_intent(str(example_intent)):
                    errors.append(f"{card.agent_name} example references unknown intent {example_intent}")
                if example_intent and example_sub_intent and not taxonomy.is_allowed_sub_intent(str(example_intent), str(example_sub_intent)):
                    errors.append(f"{card.agent_name} example references invalid sub_intent {example_intent}.{example_sub_intent}")
        if require_full_coverage:
            covered: dict[str, set[str]] = {}
            for card in self.list_available_agents():
                for intent, sub_intents in card.normalized_supported_routes().items():
                    values = covered.setdefault(intent, set())
                    values.update(sub_intents)
            for intent, expected_sub_intents in taxonomy.candidate_sub_intents().items():
                if intent not in covered:
                    errors.append(f"taxonomy intent has no enabled AgentCard coverage: {intent}")
                    continue
                missing_sub_intents = sorted(set(expected_sub_intents) - covered[intent])
                for sub_intent in missing_sub_intents:
                    errors.append(f"taxonomy sub_intent has no enabled AgentCard coverage: {intent}.{sub_intent}")
        if errors:
            raise ValueError("; ".join(errors))
def _parse_card_yaml(text: str) -> dict[str, Any]:
    """Parse AgentCard YAML."""
    parsed = yaml.safe_load(text) or {}
    if not isinstance(parsed, dict):
        raise ValueError("AgentCard YAML root must be a mapping")
    return parsed
