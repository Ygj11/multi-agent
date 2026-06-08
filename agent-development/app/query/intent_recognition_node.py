from __future__ import annotations

"""Intent recognition with LLM JSON primary path and entity-aware fallback."""

from typing import Any

from app.llm.base import LLMProvider
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.query.entity_extractor import EntityExtractor
from app.query.intent_taxonomy_loader import IntentTaxonomyLoader
from app.query.json_utils import parse_json_object
from app.schemas.entities import ConversationWindow, EntityBag
from app.schemas.intent import IntentResult


class IntentRecognitionNode:
    """Recognize business intent without choosing tools."""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        entity_extractor: EntityExtractor | None = None,
        prompt_loader: PromptLoader | None = None,
        intent_taxonomy_loader: IntentTaxonomyLoader | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.entity_extractor = entity_extractor or EntityExtractor()
        self.prompt_loader = prompt_loader or default_prompt_loader
        self.intent_taxonomy_loader = intent_taxonomy_loader or IntentTaxonomyLoader()

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
        allowed_intents = self.intent_taxonomy_loader.list_allowed_intents()
        candidate_sub_intents = self.intent_taxonomy_loader.list_candidate_sub_intents()
        intent_taxonomy = self.intent_taxonomy_loader.summaries_for_prompt()
        response = await self.llm_provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_loader.render("intent_recognition/system.md"),
                },
                {
                    "role": "user",
                    "content": self.prompt_loader.render(
                        "intent_recognition/user.md",
                        original_query=original_query,
                        rewritten_query=rewritten_query,
                        entities=entities,
                        conversation_window=window.model_dump(),
                        intent_taxonomy=intent_taxonomy,
                        allowed_intents=allowed_intents,
                        candidate_sub_intents=candidate_sub_intents,
                        agent_card_summaries=agent_card_summaries,
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

        if self._is_pos_query(query_raw, entities):
            intent = "pos_query"
            sub_intent = self._pos_sub_intent(query_raw)
            confidence = 0.86
        elif self._has_any(query_raw, "退保失败", "退保没有成功", "没有成功", "回调失败", "签名", "排查", "报错", "失败", "错误", "异常") or entities.get("request_id") or entities.get("error_code"):
            intent = "troubleshooting"
            sub_intent = self._troubleshooting_sub_intent(query_raw, entities)
            confidence = 0.9

        candidate_sub_intents = self.intent_taxonomy_loader.list_candidate_sub_intents()
        if intent != "unknown" and not self.intent_taxonomy_loader.is_allowed_intent(intent):
            intent = "unknown"
            sub_intent = None
            confidence = 0.42
        else:
            sub_intent = self._validated_sub_intent(sub_intent, intent, candidate_sub_intents)

        need_clarification = intent == "unknown" and confidence < 0.5
        return IntentResult(
            intent=intent,
            sub_intent=sub_intent,
            confidence=confidence,
            entities=entities,
            need_clarification=need_clarification,
            clarification_question="请补充你要办理的业务类型，例如排查或保全实时查询。" if need_clarification else None,
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

    @classmethod
    def _is_pos_query(cls, text: str, entities: dict[str, Any]) -> bool:
        return cls._has_any(
            text,
            "保全实时查询",
            "可做保全项",
            "可办理保全",
            "批文查询",
            "保全批文",
            "退保试算",
            "试算详情",
            "提交校验",
            "退保提交校验",
            "保单标准查询",
            "pos",
        ) or bool(entities.get("customer_no"))

    @classmethod
    def _pos_sub_intent(cls, text: str) -> str:
        if cls._has_any(text, "可做保全项", "可办理保全"):
            return "pos_available_items"
        if cls._has_any(text, "批文查询", "保全批文"):
            return "pos_approval_text_query"
        if cls._has_any(text, "退保试算", "试算详情"):
            return "pos_surrender_premium_calc"
        if cls._has_any(text, "提交校验", "退保提交校验"):
            return "pos_submit_verify"
        if cls._has_any(text, "保单标准查询", "保单查询"):
            return "pos_policy_standard_query"
        return "pos_query"
