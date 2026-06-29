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
from app.schemas.enums.llm import LLMScene
from app.schemas.enums.query import RewriteType
from app.schemas.entities import ConversationWindow
from app.schemas.intent import IntentResult


class IntentRecognitionNode:
    """识别业务意图，不选择 Agent、Skill 或工具。"""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        prompt_loader: PromptLoader | None = None,
        intent_taxonomy_loader: IntentTaxonomyLoader | None = None,
        intent_fallback_policy: IntentFallbackPolicy | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.prompt_loader = prompt_loader or default_prompt_loader
        self.intent_taxonomy_loader = intent_taxonomy_loader or IntentTaxonomyLoader()
        self.intent_fallback_policy = intent_fallback_policy or IntentFallbackPolicy.load()

    async def recognize(
        self,
        original_query: str,
        rewritten_query: str,
        entities: dict[str, Any] | None = None,
        rewrite_type: RewriteType | None = None,
        conversation_window: dict[str, Any] | None = None,
        agent_card_summaries: list[dict[str, Any]] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> IntentResult:
        """分类 intent/sub_intent；实体只读，工具和 Agent 后续再选。"""
        if entities is None:
            raise ValueError("intent_recognition_requires_entities_projection")
        if not rewrite_type:
            raise ValueError("intent_recognition_requires_rewrite_type")
        window = self._window(conversation_window)

        llm_result, llm_attempt = await self._recognize_with_llm(
            original_query=original_query,
            rewritten_query=rewritten_query,
            entities=entities,
            rewrite_type=rewrite_type,
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
            rewrite_type=rewrite_type,
            llm_attempt=llm_attempt,
        )

    async def _recognize_with_llm(
        self,
        *,
        original_query: str,
        rewritten_query: str,
        entities: dict[str, Any],
        rewrite_type: RewriteType,
        window: ConversationWindow,
        agent_card_summaries: list[dict[str, Any]],
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
    ) -> tuple[IntentResult | None, LLMAttempt]:
        prompt_trace = self.prompt_loader.scene_trace(str(LLMScene.INTENT_RECOGNITION))
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
                        "content": self.prompt_loader.render_scene_system(str(LLMScene.INTENT_RECOGNITION)),
                    },
                    {
                        "role": "user",
                        "content": self.prompt_loader.render_scene_user(
                            str(LLMScene.INTENT_RECOGNITION),
                            original_query=original_query,
                            rewritten_query=rewritten_query,
                            entities=entities,
                            rewrite_type=str(rewrite_type),
                            conversation_window=window.model_dump(),
                            intent_taxonomy=intent_taxonomy,
                            allowed_intents=allowed_intents,
                            candidate_sub_intents=candidate_sub_intents,
                            agent_card_summaries=agent_card_summaries,
                        ),
                    },
                ],
                tools=None,
                scene=LLMScene.INTENT_RECOGNITION,
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
            need_clarification=need_clarification,
            clarification_question=output.clarification_question,
            reason=output.reason,
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
        rewrite_type: RewriteType,
        llm_attempt: LLMAttempt,
    ) -> IntentResult:
        """LLM 不可用、输出非法或置信不足时的确定性意图兜底。

        规则兜底不重新抽取实体，也不修改 canonical entity_bag。
        它只读取 Query Rewrite 已经产出的 rewritten_query 与 entities，
        再结合 intent_fallback_policy.yaml 中的关键词、实体提示和澄清话术，
        给出一个受 taxonomy 约束的 intent/sub_intent。
        """
        # 步骤 1：把原始问题和改写后的自包含问题拼在一起作为规则匹配文本。
        # rewritten_query 通常比 original_query 信息更完整；保留 original_query
        # 是为了让规则仍能命中用户原话中的关键词。
        query_raw = f"{original_query} {rewritten_query}"
        # 步骤 2：规则侧不再读取历史窗口做实体继承，也不重新判断是否追问。
        # rewrite_type 已由 Query Rewrite 判定，这里只作为 trace 背景记录；
        # 规则兜底只消费 rewritten_query 与实体投影视图，避免二次维护上下文。

        # 步骤 3：调用 YAML 驱动的 fallback policy 做初步分类。
        # classify 会根据文本关键词、已有实体提示等返回 intent/sub_intent/confidence，
        # 但它的结果还不是最终路由结果，后面必须再经过 taxonomy 白名单约束。
        decision = self.intent_fallback_policy.classify(text=query_raw, entities=entities)
        intent = decision.intent
        sub_intent = decision.sub_intent
        confidence = decision.confidence
        reason = "entity_aware_rule_fallback"

        # 步骤 4：用 intent_taxonomy.yaml 约束兜底结果。
        # intent 不在系统允许值域内时，强制降为 unknown；
        # sub_intent 不在该 intent 的候选集合内时，丢弃 sub_intent，避免规则把非法子意图送入路由。
        candidate_sub_intents = self.intent_taxonomy_loader.list_candidate_sub_intents()
        if intent != "unknown" and not self.intent_taxonomy_loader.is_allowed_intent(intent):
            intent = "unknown"
            sub_intent = None
            confidence = 0.42
        else:
            sub_intent = self._validated_sub_intent(sub_intent, intent, candidate_sub_intents)

        # 步骤 5：只有 unknown 且低置信时才要求澄清。
        # 这保证“规则无法判断业务类型”的场景不会静默进入错误 Agent。
        need_clarification = intent == "unknown" and confidence < 0.5
        # 步骤 6：把规则命中过程写入 decision_trace，便于排查到底是 LLM 失败后兜底，
        # 还是命中了哪些关键词/实体提示导致当前意图。
        return IntentResult(
            intent=intent,
            sub_intent=sub_intent,
            confidence=confidence,
            need_clarification=need_clarification,
            clarification_question=decision.clarification_question if need_clarification else None,
            reason=reason,
            llm_status=llm_attempt.llm_status,
            fallback_used=True,
            fallback_source="intent_recognition",
            fallback_reason=llm_attempt.fallback_reason or LLM_DISABLED,
            decision_trace={
                "source": "intent_recognition",
                "method": "rule_fallback",
                **self.intent_fallback_policy.trace(),
                "rewrite_type": str(rewrite_type),
                "matched_keywords": decision.matched_keywords,
                "matched_entity_hints": decision.matched_entity_hints,
                **llm_attempt.trace(source="intent_recognition"),
            },
        )

    def _window(
        self,
        conversation_window: dict[str, Any] | None,
    ) -> ConversationWindow:
        if not conversation_window:
            raise ValueError("intent_recognition_requires_conversation_window")
        return ConversationWindow(**conversation_window)

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
