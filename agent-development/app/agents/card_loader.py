from __future__ import annotations

"""AgentCard 加载、校验和规则候选召回。

AgentCard 是子 Agent 的内部能力与治理声明：它说明该 Agent 支持哪些 route、
可见哪些工具、绑定哪些 Skill、使用哪些 namespace。它不是对外 Public
AgentCard，也不直接执行任务。
"""

from pathlib import Path
from typing import Any

import yaml

from app.agents.routing_policy import AgentRoutingPolicy
from app.observability.logger import log_event
from app.schemas.agent_card import AgentCard, AgentCandidate
from app.schemas.intent_taxonomy import IntentTaxonomy
from app.skills.catalog import SkillCatalog


class AgentCardLoader:
    """加载 AgentCard，并提供候选匹配能力。"""

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
        """
        为给定的用户请求匹配最合适的 Agent 候选列表。

        使用多维度加权评分系统，从所有可用 Agent 卡片中计算匹配分数，
        并按分数降序返回候选列表。

        Args:
            intent: 用户意图（如 "book_flight", "check_weather"）
            entities: 从用户查询中提取的实体字典
            query: 原始用户查询文本
            sub_intent: 可选的子意图，用于更精细的意图匹配

        Returns:
            按分数降序排列的 AgentCandidate 列表，分数相同则按名称排序

        Scoring Strategy:
            评分基于以下维度（权重由 routing_policy 配置）：

            1. 意图匹配 (intent_match)
               - 精确匹配: intent 在 card.supported_routes 中
               - 关键词匹配: intent 在 card.capabilities 或 description 中

            2. 子意图匹配 (sub_intent_match)
               - sub_intent 在卡片的支持子意图列表中

            3. 实体匹配
               - required_entity_present: 每个存在的必填实体加分
               - required_entity_missing: 每个缺失的必填实体扣分（负权重）
               - optional_entity_present: 每个存在的可选实体加分

            4. 能力关键词匹配 (capability_keyword)
               - card.capabilities 中的词出现在 query 中

            5. 查询关键词匹配 (query_keyword)
               - query 分词后的每个 token 出现在卡片文本中
               - 卡片文本包括: agent_name, display_name, description,
                 capabilities, supported_intents, supported_sub_intents,
                 supported_routes, optional_entities, rag_namespaces, examples

            6. 启用状态 (enabled)
               - card.enabled == True 时加分

            Note:
                - 所有分数累加，最终得分越高表示 Agent 越匹配
                - 缺失必填实体会产生负分，优先选择能完整处理请求的 Agent
                - 权重值通过 self.routing_policy.weight() 获取，可在配置中调整 -》routing_policy.yaml
        """
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

            # supported_routes 是 Agent 级路由白名单。命中它表示“这个 Agent
            # 声明可处理该 intent/sub_intent”，后续仍需权限、Skill 和工具校验。
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
                # capabilities 只是语义画像和规则加分信号，不是可执行动作。
                # 真正可执行能力必须来自 private_tools/public_tools/MCP tools。
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
        """校验 AgentCard 与 Skill metadata 的声明一致性。

        这里保证 card.skills、supported_routes、private_tools 与 Skill frontmatter
        不漂移；它是启动期静态治理，不参与每次请求的动态路由。
        """
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
        """校验 AgentCard route/example 是否引用合法 taxonomy 值。"""
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
