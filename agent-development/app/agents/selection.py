from __future__ import annotations

"""Agent 选择节点。

该节点只在 AgentCard 候选中选择本次任务要交给哪个子 Agent。它不加载 Skill
正文、不选择工具、不执行工具；这些动作分别发生在子 Agent 和 ToolExecutor。
"""

from typing import Any

from app.agents.card_loader import AgentCardLoader
from app.agents.llm_router import LLMRouter
from app.agents.routing_policy import AgentRoutingPolicy
from app.llm.base import LLMProvider
from app.observability.logger import log_event
from app.runtime.failure_codes import AGENT_ROUTER_UNUSABLE
from app.schemas.agent_card import AgentSelectionResult


class AgentSelectionNode:
    """混合 AgentCard 路由器：规则召回 Top-K，必要时让 LLM 在候选内重排。"""

    def __init__(
        self,
        card_loader: AgentCardLoader,
        llm_provider: LLMProvider | None = None,
        *,
        rule_confident_threshold: float | None = None,
        rule_margin_threshold: float | None = None,
        top_k: int | None = None,
        routing_policy: AgentRoutingPolicy | None = None,
    ) -> None:
        self.card_loader = card_loader
        self.llm_provider = llm_provider
        self.llm_router = LLMRouter(llm_provider)
        self.routing_policy = routing_policy or card_loader.routing_policy
        self.rule_confident_threshold = (
            rule_confident_threshold
            if rule_confident_threshold is not None
            else self.routing_policy.threshold("rule_confident_threshold", 8.0)
        )
        self.rule_margin_threshold = (
            rule_margin_threshold
            if rule_margin_threshold is not None
            else self.routing_policy.threshold("rule_margin_threshold", 3.0)
        )
        self.top_k = int(top_k if top_k is not None else self.routing_policy.threshold("top_k", 3))

    async def select(
        self,
        *,
        intent: str,
        sub_intent: str | None = None,
        intent_confidence: float = 1.0,
        entities: dict[str, Any],
        query: str,
        is_follow_up: bool = False,
        request_id: str | None = None,
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> AgentSelectionResult:
        """
        规则已经足够确定
        -> 不调用 LLM
        -> _rule_selection(method="rule")

        这是正常规则路由。例如：
            没有 LLM；
            只有一个候选 Agent；
            Top1 分数高，且领先 Top2 的差距足够大；
            intent 置信度高、不是追问、query 不长。
        """
        candidates = self.card_loader.match_candidates(
            intent=intent,
            sub_intent=sub_intent,
            entities=entities,
            query=query,
        )
        if not candidates:
            raise ValueError("no available AgentCard candidates")

        top_candidates = candidates[: self.top_k]
        # LLM router 只在规则不够确定时介入，并且只能从 top_candidates 中选择。
        # 它不是开放式路由，不能绕过 AgentCard 白名单发明新 Agent。
        if self._should_call_llm_router(
            candidates=top_candidates,
            intent_confidence=intent_confidence,
            is_follow_up=is_follow_up,
            query=query,
        ):
            llm_selection = await self.llm_router.route(
                intent=intent,
                sub_intent=sub_intent,
                intent_confidence=intent_confidence,
                entities=entities,
                query=query,
                candidates=top_candidates,
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
            )
            if llm_selection is not None:
                llm_selection.decision_trace = {
                    **self.routing_policy.trace(),
                    **llm_selection.decision_trace,
                }
                self._log_selection(llm_selection, request_id, trace_id, session_key)
                return llm_selection
            attempt = self.llm_router.last_attempt
            # 这里的 fallback rule_selection 表示“尝试 LLM 路由失败后回退规则结果”。
            # 下方 method="rule" 则是“规则本身已足够确定，从未调用 LLM”。
            selection = self._rule_selection(
                candidates,
                method="fallback",
                reason_suffix=f"; {attempt.fallback_reason or AGENT_ROUTER_UNUSABLE}",
                llm_status=attempt.llm_status,
                fallback_reason=attempt.fallback_reason or AGENT_ROUTER_UNUSABLE,
                decision_trace=attempt.trace(source="agent_selection"),
            )
            self._log_selection(selection, request_id, trace_id, session_key)
            return selection

        result = self._rule_selection(candidates, method="rule")
        self._log_selection(result, request_id, trace_id, session_key)
        return result

    def _rule_selection(
        self,
        candidates: list,
        *,
        method: str,
        reason_suffix: str = "",
        llm_status: str | None = None,
        fallback_reason: str | None = None,
        decision_trace: dict[str, Any] | None = None,
    ) -> AgentSelectionResult:
        """
        从候选 Agent 列表中选择最优 Agent，并生成完整的决策结果。

        该方法将原始评分候选转换为结构化的选择结果，包含置信度计算、
        风险评估、是否需要澄清等决策元信息。

        Args:
            candidates: AgentCandidate 列表（已按分数降序排序）
            method: 选择方法标识（如 "rule_based", "llm_based", "fallback"）
            reason_suffix: 附加到选择原因后的后缀文本
            llm_status: LLM 辅助选择的状态（如果使用了 LLM）
            fallback_reason: 降级回退的原因（如果触发了降级）
            decision_trace: 额外的决策追踪信息

        Returns:
            AgentSelectionResult: 完整的选择决策结果，包含：
                - selected_agent: 被选中的 Agent 名称
                - confidence: 置信度 (0-1)
                - reason: 选择原因说明
                - required_context: 需要的实体列表
                - risk_level: 风险等级 ("low" / "medium")
                - candidates: 所有候选列表
                - fallback: 是否使用了降级策略
                - need_clarification: 是否需要向用户澄清
                - clarification_question: 澄清问题时使用的模板
                - decision_trace: 完整的决策追踪信息

        Decision Flow:
            1. 选择最优候选：取 candidates[0]（已排序）
            2. 判断是否降级：method == "fallback" 或 score <= 0
            3. 计算置信度：score / divisor，并限制在 [min_confidence, max_confidence] 区间
            4. 评估风险：有缺失必填实体时为 "medium"，否则为 "low"
            5. 判断需澄清：score <= clarify_threshold
            6. 构建完整结果对象

        Confidence Calculation:
            - 基础公式: confidence = score / divisor
            - 下界限制: min_confidence (默认 0.2)
            - 上界限制: max_confidence (默认 0.99)
            - 作用: 将原始分数归一化为概率级别的置信度

        Risk Assessment:
            - low: 所有必填实体都已提供
            - medium: 有必填实体缺失（可能影响 Agent 执行）

        Clarification Logic:
            - 当 score <= clarify_threshold (默认 0.5) 时触发
            - 表示 Agent 匹配度较低，需要向用户提问以获取更多信息
        """
        selected = candidates[0]
        fallback = method == "fallback" or selected.score <= 0
        min_confidence = self.routing_policy.threshold("min_confidence", 0.2)
        max_confidence = self.routing_policy.threshold("max_confidence", 0.99)
        divisor = self.routing_policy.threshold("score_to_confidence_divisor", 12.0)
        clarify_threshold = self.routing_policy.threshold("clarify_score_threshold", 0.5)
        confidence = min(max_confidence, max(min_confidence, selected.score / divisor))
        risk_level = "medium" if selected.missing_entities else "low"
        need_clarification = selected.score <= clarify_threshold
        result = AgentSelectionResult(
            selected_agent=selected.agent_name,
            confidence=confidence,
            reason=f"{selected.reason}{reason_suffix}",
            required_context=selected.card.required_entities,
            risk_level=risk_level,
            candidates=candidates,
            fallback=fallback,
            selection_method=method,  # type: ignore[arg-type]
            need_clarification=need_clarification,
            clarification_question=self.routing_policy.clarification_question
            if need_clarification
            else None,
            llm_status=llm_status,
            fallback_used=fallback,
            fallback_source="agent_selection" if fallback else None,
            fallback_reason=fallback_reason,
            decision_trace={
                "source": "agent_selection",
                "method": method,
                **self.routing_policy.trace(),
                **(decision_trace or {}),
            },
        )
        return result

    def _should_call_llm_router(
        self,
        *,
        candidates: list,
        intent_confidence: float,
        is_follow_up: bool,
        query: str,
    ) -> bool:
        if self.llm_provider is None or not candidates:
            return False
        if len(candidates) == 1:
            return False
        top1, top2 = candidates[0], candidates[1]
        if top1.score >= self.rule_confident_threshold and top1.score - top2.score >= self.rule_margin_threshold:
            return False
        if intent_confidence < 0.75 or is_follow_up:
            return True
        if top1.score - top2.score < self.rule_margin_threshold:
            return True
        return len(query) > 80

    @staticmethod
    def _log_selection(
        result: AgentSelectionResult,
        request_id: str | None,
        trace_id: str | None,
        session_key: str | None,
    ) -> None:
        log_event(
            "agent_selected",
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            node="agent_selection",
            message="Agent selected from AgentCards",
            data={
                "selected_agent": result.selected_agent,
                "confidence": result.confidence,
                "risk_level": result.risk_level,
                "candidate_count": len(result.candidates),
                "selection_method": result.selection_method,
                "reason": result.reason,
                "fallback_used": result.fallback_used,
                "fallback_reason": result.fallback_reason,
                "llm_status": result.llm_status,
            },
        )
