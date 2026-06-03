from __future__ import annotations

"""Intent recognition with LLM JSON primary path and entity-aware fallback."""

from typing import Any

from app.llm.base import LLMProvider
from app.query.entity_extractor import EntityExtractor
from app.query.json_utils import parse_json_object
from app.schemas.entities import ConversationWindow, EntityBag
from app.schemas.intent import IntentResult


class IntentRecognitionNode:
    """Recognize business intent without choosing tools."""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        entity_extractor: EntityExtractor | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.entity_extractor = entity_extractor or EntityExtractor()

    async def recognize(
        self,
        original_query: str,
        rewritten_query: str,
        recent_messages: list[dict[str, Any]] | None = None,
        short_summary: str | None = None,
        current_entities: dict[str, Any] | None = None,
        conversation_window: dict[str, Any] | None = None,
        agent_card_summaries: list[dict[str, Any]] | None = None,
    ) -> IntentResult:
        """Classify intent and sub_intent; never select tools."""
        extracted_bag = self.entity_extractor.extract(f"{original_query}\n{rewritten_query}", source="current_query")
        extracted_bag.merge(EntityBag.from_compact_dict(current_entities or {}, source="rule", confidence=0.9))
        window = self._window(conversation_window, short_summary, recent_messages, extracted_bag)

        llm_result = await self._recognize_with_llm(
            original_query=original_query,
            rewritten_query=rewritten_query,
            entities=extracted_bag.to_compact_dict(),
            window=window,
            agent_card_summaries=agent_card_summaries or [],
        )
        if llm_result is not None:
            return llm_result
        # fallback 兜底规则引擎
        return self._recognize_with_rules(
            original_query=original_query,
            rewritten_query=rewritten_query,
            entities=extracted_bag.to_compact_dict(),
            window=window,
        )

    async def _recognize_with_llm(
        self,
        *,
        original_query: str,
        rewritten_query: str,
        entities: dict[str, Any],
        window: ConversationWindow,
        agent_card_summaries: list[dict[str, Any]],
    ) -> IntentResult | None:
        if not self._should_use_llm_json():
            return None
        allowed_intents = self._allowed_intents(agent_card_summaries)
        candidate_sub_intents = self._candidate_sub_intents(agent_card_summaries)
        response = await self.llm_provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are the intent recognition node of a multi-agent health insurance system. "
                        "Classify the user's business intent, but do not select an agent or tools. "
                        "Rules: intent must be one of allowed_intents, or unknown. Do not invent intent values. "
                        "sub_intent should be selected from candidate_sub_intents when possible; use null if none fits. "
                        "Never output required_tools, selected_agent, or tool names. If confidence is below 0.5, "
                        "set need_clarification=true. Confidence scoring guide: 0.90-1.00 means the query clearly "
                        "matches exactly one allowed_intent with strong evidence from rewritten_query, entities, "
                        "AgentCard summaries, examples, or capabilities; use this range only for a clear single best "
                        "intent. 0.75-0.89 means one intent is likely, but sub_intent or some context may be uncertain. "
                        "0.50-0.74 means partial evidence or multiple plausible intents; set need_clarification=true "
                        "when the user action is ambiguous. 0.35-0.49 means low confidence and must set "
                        "need_clarification=true. 0.00-0.34 means unknown, out of domain, or insufficient information; "
                        "intent should be unknown and need_clarification=true. Increase confidence when entities match "
                        "the candidate intent domain, examples/capabilities clearly match the query, and sub_intent is "
                        "selected from candidate_sub_intents. Decrease confidence when multiple intents are plausible, "
                        "key business objects are missing, the query is a vague follow-up, or the sub_intent is uncertain. "
                        "Return strict JSON only with keys: intent, sub_intent, "
                        "confidence, entities, missing_required_entities, need_clarification, clarification_question, "
                        "is_follow_up, reason."
                    ),
                },
                {
                    "role": "user",
                    "content": (
                        f"Original query: {original_query}\n"
                        f"Rewritten query: {rewritten_query}\n"
                        f"Entities: {entities}\n"
                        f"Conversation window: {window.model_dump()}\n"
                        f"Allowed intents: {allowed_intents}\n"
                        f"Candidate sub intents by intent: {candidate_sub_intents}\n"
                        f"AgentCard summaries: {agent_card_summaries}"
                    ),
                },
            ],
            tools=None,
            scene="intent_recognition",
        )
        data = parse_json_object(response.content)
        if data is None:
            return None
        intent = str(data.get("intent") or "unknown")
        if not self._is_allowed_intent(intent, allowed_intents):
            return None
        confidence = float(data.get("confidence", 0.0) or 0.0)
        need_clarification = bool(data.get("need_clarification", False)) or confidence < 0.35
        llm_entities = data.get("entities") if isinstance(data.get("entities"), dict) else {}
        merged_entities = {**entities, **llm_entities}
        sub_intent = self._validated_sub_intent(data.get("sub_intent"), intent, candidate_sub_intents)
        return IntentResult(
            intent=intent,
            sub_intent=sub_intent,
            confidence=confidence,
            entities=merged_entities,
            missing_required_entities=[str(item) for item in data.get("missing_required_entities") or []],
            need_clarification=need_clarification,
            clarification_question=data.get("clarification_question"),
            is_follow_up=bool(data.get("is_follow_up", False)),
            reason=str(data.get("reason") or "llm_json_classification"),
            target_subagent=None,
        )

    def _recognize_with_rules(
        self,
        *,
        original_query: str,
        rewritten_query: str,
        entities: dict[str, Any],
        window: ConversationWindow,
    ) -> IntentResult:
        query = f"{original_query} {rewritten_query}".lower()
        query_raw = f"{original_query} {rewritten_query}"
        is_follow_up = bool(window.entity_bag.to_compact_dict()) and original_query.strip() != rewritten_query.strip()

        intent = "unknown"
        sub_intent: str | None = None
        confidence = 0.42
        reason = "entity_aware_rule_fallback"

        if self._has_any(query_raw, "合规", "隐私", "敏感", "脱敏", "外发", "token", "secret", "身份证", "手机号"):
            intent, sub_intent, confidence = "compliance_review", "privacy_review", 0.86
        elif self._has_any(query_raw, "文档", "解析文档", "接口文档", "markdown", "json", "yaml", "提取字段"):
            intent, sub_intent, confidence = "document_parse", "api_doc_parse", 0.84
        elif self._has_any(query_raw, "变更影响", "影响分析", "字段变更", "接口变更", "签名规则变更", "change impact"):
            intent, sub_intent, confidence = "change_impact_analysis", "signature_rule_change", 0.86
        elif self._has_any(query_raw, "理赔", "赔案", "claim") or entities.get("claim_no"):
            intent, sub_intent, confidence = "claim_query", "claim_progress", 0.84
        elif self._has_any(query_raw, "退保失败", "退保没有成功", "没有成功", "回调失败", "签名", "排查", "报错", "失败", "错误", "异常") or entities.get("request_id") or entities.get("error_code"):
            intent = "troubleshooting"
            sub_intent = self._troubleshooting_sub_intent(query_raw, entities)
            confidence = 0.9
        elif self._has_any(query_raw, "保单", "保单状态", "policy") or entities.get("policy_no"):
            intent, sub_intent, confidence = "policy_query", "policy_status", 0.84
        elif self._has_any(query_raw, "等待期", "责任", "条款", "product rule"):
            intent, sub_intent, confidence = "product_rule_qa", "product_rule_qa", 0.78

        need_clarification = intent == "unknown" and confidence < 0.5
        return IntentResult(
            intent=intent,
            sub_intent=sub_intent,
            confidence=confidence,
            entities=entities,
            need_clarification=need_clarification,
            clarification_question="请补充你要办理的业务类型，例如排查、保单查询、理赔查询、文档解析或合规审查。" if need_clarification else None,
            is_follow_up=is_follow_up,
            reason=reason,
            target_subagent=None,
        )

    def _window(
        self,
        conversation_window: dict[str, Any] | None,
        short_summary: str | None,
        recent_messages: list[dict[str, Any]] | None,
        current_bag: EntityBag,
    ) -> ConversationWindow:
        if conversation_window:
            try:
                return ConversationWindow(**conversation_window)
            except Exception:
                pass
        bag = EntityBag().merge(self.entity_extractor.extract_from_summary(short_summary))
        bag.merge(self.entity_extractor.extract_from_recent_turns(recent_messages or []))
        bag.merge(current_bag)
        return ConversationWindow(session_key="", summary=short_summary, recent_turns=recent_messages or [], entity_bag=bag)

    @staticmethod
    def _has_any(text: str, *keywords: str) -> bool:
        lower = text.lower()
        return any(keyword.lower() in lower for keyword in keywords)

    def _should_use_llm_json(self) -> bool:
        if self.llm_provider is None:
            return False
        if self.llm_provider.__class__.__name__ == "InternalLLMProvider" and not getattr(self.llm_provider, "base_url", None):
            return False
        return True

    @staticmethod
    def _allowed_intents(agent_card_summaries: list[dict[str, Any]]) -> list[str]:
        intents: set[str] = set()
        for card in agent_card_summaries:
            for intent in card.get("supported_intents") or []:
                if intent:
                    intents.add(str(intent))
        return sorted(intents)

    @classmethod
    def _candidate_sub_intents(cls, agent_card_summaries: list[dict[str, Any]]) -> dict[str, list[str]]:
        by_intent: dict[str, set[str]] = {}
        for card in agent_card_summaries:
            supported = [str(item) for item in card.get("supported_intents") or [] if item]
            capabilities = [str(item) for item in card.get("capabilities") or [] if item]
            examples = cls._example_intents(card.get("examples") or [])
            candidates = set(supported + capabilities + examples)
            for intent in supported:
                values = by_intent.setdefault(intent, set())
                values.update(item for item in candidates if item != intent)
        return {intent: sorted(values) for intent, values in sorted(by_intent.items())}

    @staticmethod
    def _example_intents(examples: Any) -> list[str]:
        values: list[str] = []
        if not isinstance(examples, list):
            return values
        for item in examples:
            if isinstance(item, dict) and item.get("intent"):
                values.append(str(item["intent"]))
        return values

    @staticmethod
    def _is_allowed_intent(intent: str, allowed_intents: list[str]) -> bool:
        if intent == "unknown":
            return True
        if not allowed_intents:
            return True
        return intent in set(allowed_intents)

    @staticmethod
    def _validated_sub_intent(value: Any, intent: str, candidate_sub_intents: dict[str, list[str]]) -> str | None:
        if value in (None, ""):
            return None
        sub_intent = str(value)
        if not candidate_sub_intents:
            return sub_intent
        allowed = set(candidate_sub_intents.get(intent) or [])
        if not allowed:
            return sub_intent
        return sub_intent if sub_intent in allowed else None

    @classmethod
    def _troubleshooting_sub_intent(cls, text: str, entities: dict[str, Any]) -> str:
        if cls._has_any(text, "退保失败", "退保没有成功", "没有成功"):
            return "refund_failure"
        if cls._has_any(text, "回调失败", "回调超时", "未收到回调"):
            return "callback_failure"
        if cls._has_any(text, "字段缺失", "不能为空", "必填"):
            return "missing_field"
        if entities.get("error_code") or cls._has_any(text, "E102", "签名"):
            return "signature_error"
        return "general_troubleshooting"
