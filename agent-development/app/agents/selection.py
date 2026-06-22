from __future__ import annotations

"""Agent selection node implementation."""

from typing import Any

from app.agents.card_loader import AgentCardLoader
from app.agents.llm_router import LLMRouter
from app.agents.routing_policy import AgentRoutingPolicy
from app.llm.base import LLMProvider
from app.observability.logger import log_event
from app.runtime.failure_codes import AGENT_ROUTER_UNUSABLE
from app.schemas.agent_card import AgentSelectionResult


class AgentSelectionNode:
    """Hybrid AgentCard router: rule Top-K recall plus optional LLM re-rank."""

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
        candidates = self.card_loader.match_candidates(
            intent=intent,
            sub_intent=sub_intent,
            entities=entities,
            query=query,
        )
        if not candidates:
            raise ValueError("no available AgentCard candidates")

        top_candidates = candidates[: self.top_k]
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
