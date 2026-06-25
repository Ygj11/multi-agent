from __future__ import annotations

"""意图识别节点。

本节点只负责识别系统允许的 intent/sub_intent，并给出置信度、澄清与降级原因。
canonical 实体状态已经在 Query Rewrite 阶段完成，LLM 即使返回实体相关内容，
也不能在这里写回 `entity_bag`。
"""

from typing import Any

from app.llm.base import LLMProvider
from app.llm.output_schemas import IntentRecognitionLLMOutput, parse_llm_json_schema
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.query.entity_resolver import EntityResolver
from app.query.intent_fallback_policy import IntentFallbackPolicy
from app.query.intent_taxonomy_loader import IntentTaxonomyLoader
from app.runtime.decision_trace import LLMAttempt
from app.runtime.failure_codes import (
    INVALID_INTENT,
    INVALID_SUB_INTENT,
    LLM_DISABLED,
    LLM_JSON_PARSE_FAILED,
    LLM_PROVIDER_ERROR,
    LLM_SCHEMA_VALIDATION_FAILED,
    LLM_STATUS_DISABLED,
    LLM_STATUS_INVALID_OUTPUT,
    LLM_STATUS_PARSE_FAILED,
    LLM_STATUS_PROVIDER_ERROR,
    LLM_STATUS_SUCCESS,
)
from app.schemas.entities import ConversationWindow, EntityBag
from app.schemas.intent import IntentResult


class IntentRecognitionNode:
    """识别业务意图，不选择 Agent、Skill 或工具。"""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        entity_resolver: EntityResolver | None = None,
        prompt_loader: PromptLoader | None = None,
        intent_taxonomy_loader: IntentTaxonomyLoader | None = None,
        intent_fallback_policy: IntentFallbackPolicy | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.entity_resolver = entity_resolver or EntityResolver()
        self.prompt_loader = prompt_loader or default_prompt_loader
        self.intent_taxonomy_loader = intent_taxonomy_loader or IntentTaxonomyLoader()
        self.intent_fallback_policy = intent_fallback_policy or IntentFallbackPolicy.load()

    async def recognize(
        self,
        original_query: str,
        rewritten_query: str,
        recent_messages: list[dict[str, Any]] | None = None,
        short_summary: str | None = None,
        current_entities: dict[str, Any] | None = None,
        entity_bag: dict[str, Any] | None = None,
        conversation_window: dict[str, Any] | None = None,
        agent_card_summaries: list[dict[str, Any]] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> IntentResult:
        """分类 intent/sub_intent；实体只读，工具和 Agent 后续再选。"""
        resolved_bag = self._resolved_bag(entity_bag=entity_bag, current_entities=current_entities)
        entities = resolved_bag.to_compact_dict()
        window = self._window(conversation_window, short_summary, recent_messages, resolved_bag)

        llm_result, llm_attempt = await self._recognize_with_llm(
            original_query=original_query,
            rewritten_query=rewritten_query,
            entities=entities,
            window=window,
            agent_card_summaries=agent_card_summaries or [],
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
        )
        if llm_result is not None:
            return llm_result
        # fallback 兜底规则引擎
        return self._recognize_with_rules(
            original_query=original_query,
            rewritten_query=rewritten_query,
            entities=entities,
            window=window,
            llm_attempt=llm_attempt,
        )

    async def _recognize_with_llm(
        self,
        *,
        original_query: str,
        rewritten_query: str,
        entities: dict[str, Any],
        window: ConversationWindow,
        agent_card_summaries: list[dict[str, Any]],
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
    ) -> tuple[IntentResult | None, LLMAttempt]:
        prompt_trace = self.prompt_loader.scene_trace("intent_recognition")
        if not self._should_use_llm_json():
            return None, LLMAttempt(
                llm_status=LLM_STATUS_DISABLED,
                fallback_reason=LLM_DISABLED,
                extra=prompt_trace,
            )
        allowed_intents = self.intent_taxonomy_loader.list_allowed_intents()
        """intent_taxonomy.yaml 中给某个 intent 配置了 sub_intents，就按白名单校验；没配置则表示该 intent 没有合法子意图，而不是跳过校验。"""
        candidate_sub_intents = self.intent_taxonomy_loader.list_candidate_sub_intents()
        intent_taxonomy = self.intent_taxonomy_loader.summaries_for_prompt()
        try:
            response = await self.llm_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self.prompt_loader.render_scene_system("intent_recognition"),
                    },
                    {
                        "role": "user",
                        "content": self.prompt_loader.render_scene_user(
                            "intent_recognition",
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
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
            )
        except Exception as exc:
            return None, LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=str(exc),
                extra=prompt_trace,
            )
        if response.finish_reason == "error" or response.error:
            return None, LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=response.error or "llm_error",
                extra={
                    **prompt_trace,
                    "finish_reason": response.finish_reason,
                    "model": response.model,
                },
            )
        parsed = parse_llm_json_schema(response.content, IntentRecognitionLLMOutput)
        parse_trace = {
            **prompt_trace,
            "finish_reason": response.finish_reason,
            "model": response.model,
            "parse_status": parsed.parse_status,
            "schema_status": "valid" if parsed.success else "invalid",
            "schema_name": parsed.schema_name,
        }
        if not parsed.success:
            return None, LLMAttempt(
                llm_status=LLM_STATUS_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_JSON_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_SCHEMA_VALIDATION_FAILED,
                detail=parsed.error_detail,
                extra=parse_trace,
            )
        output = parsed.data
        if not isinstance(output, IntentRecognitionLLMOutput):
            return None, LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_SCHEMA_VALIDATION_FAILED,
                detail="schema result type mismatch",
                extra=parse_trace,
            )
        intent = output.intent or "unknown"
        # LLM 输出只能在 taxonomy 白名单内选择意图；非法 intent 触发降级，
        # 不允许模型临时发明新业务意图进入主路由。
        if not self._is_allowed_intent(intent, allowed_intents):
            return None, LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=INVALID_INTENT,
                detail=f"intent={intent}",
                extra=parse_trace,
            )
        confidence = output.confidence
        need_clarification = output.need_clarification or confidence < 0.35
        sub_intent_raw = output.sub_intent
        sub_intent = self._validated_sub_intent(sub_intent_raw, intent, candidate_sub_intents)
        # sub_intent 同样按 taxonomy 分组白名单校验。未配置子意图时表示没有合法子意图，
        # 不是“允许任意 sub_intent”。
        invalid_sub_intent = sub_intent_raw not in (None, "") and sub_intent is None
        if sub_intent_raw not in (None, "") and sub_intent is None:
            need_clarification = True if confidence < 0.75 else need_clarification
        return IntentResult(
            intent=intent,
            sub_intent=sub_intent,
            confidence=confidence,
            missing_required_entities=[str(item) for item in output.missing_required_entities],
            need_clarification=need_clarification,
            clarification_question=output.clarification_question,
            is_follow_up=output.is_follow_up,
            reason=output.reason,
            target_subagent=None,
            llm_status=LLM_STATUS_INVALID_OUTPUT if invalid_sub_intent else LLM_STATUS_SUCCESS,
            fallback_used=invalid_sub_intent,
            fallback_source="intent_recognition" if invalid_sub_intent else None,
            fallback_reason=INVALID_SUB_INTENT if invalid_sub_intent else None,
            decision_trace={
                "source": "intent_recognition",
                "method": "llm_json",
                **self.intent_fallback_policy.trace(),
                "llm_status": LLM_STATUS_INVALID_OUTPUT if invalid_sub_intent else LLM_STATUS_SUCCESS,
                "fallback_reason": INVALID_SUB_INTENT if invalid_sub_intent else None,
                "invalid_sub_intent": str(sub_intent_raw) if invalid_sub_intent else None,
                **parse_trace,
            },
        ), LLMAttempt(
            llm_status=LLM_STATUS_INVALID_OUTPUT if invalid_sub_intent else LLM_STATUS_SUCCESS,
            fallback_reason=INVALID_SUB_INTENT if invalid_sub_intent else None,
            extra=parse_trace,
        )

    def _recognize_with_rules(
        self,
        *,
        original_query: str,
        rewritten_query: str,
        entities: dict[str, Any],
        window: ConversationWindow,
        llm_attempt: LLMAttempt,
    ) -> IntentResult:
        query_raw = f"{original_query} {rewritten_query}"
        is_follow_up = bool(window.entity_bag.to_compact_dict()) and original_query.strip() != rewritten_query.strip()

        decision = self.intent_fallback_policy.classify(text=query_raw, entities=entities)
        intent = decision.intent
        sub_intent = decision.sub_intent
        confidence = decision.confidence
        reason = "entity_aware_rule_fallback"

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
            need_clarification=need_clarification,
            clarification_question=decision.clarification_question if need_clarification else None,
            is_follow_up=is_follow_up,
            reason=reason,
            target_subagent=None,
            llm_status=llm_attempt.llm_status,
            fallback_used=True,
            fallback_source="intent_recognition",
            fallback_reason=llm_attempt.fallback_reason or LLM_DISABLED,
            decision_trace={
                "source": "intent_recognition",
                "method": "rule_fallback",
                **self.intent_fallback_policy.trace(),
                "matched_keywords": decision.matched_keywords,
                "matched_entity_hints": decision.matched_entity_hints,
                **llm_attempt.trace(source="intent_recognition"),
            },
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
        return ConversationWindow(session_key="", summary=short_summary, recent_turns=recent_messages or [], entity_bag=current_bag)

    def _resolved_bag(
        self,
        *,
        entity_bag: dict[str, Any] | None,
        current_entities: dict[str, Any] | None,
    ) -> EntityBag:
        # 兼容旧调用：如果上游只给 compact entities，则临时转成 EntityBag 读取。
        # 这是只读兼容路径，不能把转换结果作为新的 canonical entity_bag 写回 Graph。
        if entity_bag:
            try:
                return self.entity_resolver.normalize_bag(EntityBag(**entity_bag), stage="intent_recognition_read")
            except Exception:
                pass
        return self.entity_resolver.resolve(
            base_bag=EntityBag(),
            candidate_bag=EntityBag.from_compact_dict(current_entities or {}, source="rule", confidence=0.9),
            stage="intent_recognition_compat_read",
        ).entity_bag

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
