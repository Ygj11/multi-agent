from __future__ import annotations

"""LLM re-ranker for ambiguous AgentCard candidates."""

from typing import Any

from app.llm.base import LLMProvider
from app.llm.output_schemas import AgentSelectionLLMOutput, parse_llm_json_schema
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.runtime.decision_trace import LLMAttempt
from app.runtime.failure_codes import (
    AGENT_ROUTER_UNUSABLE,
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
from app.schemas.agent_card import AgentCandidate, AgentSelectionResult


class LLMRouter:
    """Select one agent from Top-K rule candidates using JSON-only LLM output."""

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        min_confidence: float = 0.45,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.min_confidence = min_confidence
        self.prompt_loader = prompt_loader or default_prompt_loader
        self.last_attempt = LLMAttempt(llm_status=LLM_STATUS_DISABLED, fallback_reason=LLM_DISABLED)

    async def route(
        self,
        *,
        intent: str,
        sub_intent: str | None,
        intent_confidence: float,
        entities: dict[str, Any],
        query: str,
        candidates: list[AgentCandidate],
        request_id: str | None = None,
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> AgentSelectionResult | None:
        """Return LLM-selected candidate or None when the router output is unusable."""
        prompt_trace = self.prompt_loader.scene_trace("agent_selection")
        if self.llm_provider is None:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_DISABLED,
                fallback_reason=LLM_DISABLED,
                extra=prompt_trace,
            )
            return None
        if not candidates:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=AGENT_ROUTER_UNUSABLE,
                detail="no_candidates",
                extra=prompt_trace,
            )
            return None
        top_names = {candidate.agent_name for candidate in candidates}
        summaries = [
            {
                "agent_name": candidate.agent_name,
                "description": candidate.card.description,
                "supported_routes": candidate.card.normalized_supported_routes(),
                "capabilities": candidate.card.capabilities,
                "required_entities": candidate.card.required_entities,
                "optional_entities": candidate.card.optional_entities,
                "examples": candidate.card.examples,
                "rule_score": candidate.score,
                "missing_entities": candidate.missing_entities,
            }
            for candidate in candidates
        ]
        try:
            response = await self.llm_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self.prompt_loader.render_scene_system("agent_selection"),
                    },
                    {
                        "role": "user",
                        "content": self.prompt_loader.render_scene_user(
                            "agent_selection",
                            query=query,
                            intent=intent,
                            sub_intent=sub_intent,
                            intent_confidence=intent_confidence,
                            entities=entities,
                            candidates=summaries,
                        ),
                    },
                ],
                tools=None,
                scene="agent_selection",
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
            )
        except Exception as exc:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=str(exc),
                extra=prompt_trace,
            )
            return None
        if response.finish_reason == "error" or response.error:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_PROVIDER_ERROR,
                fallback_reason=LLM_PROVIDER_ERROR,
                detail=response.error or "llm_error",
                extra={
                    **prompt_trace,
                    "finish_reason": response.finish_reason,
                    "model": response.model,
                },
            )
            return None
        parsed = parse_llm_json_schema(response.content, AgentSelectionLLMOutput)
        parse_trace = {
            **prompt_trace,
            "finish_reason": response.finish_reason,
            "model": response.model,
            "parse_status": parsed.parse_status,
            "schema_status": "valid" if parsed.success else "invalid",
            "schema_name": parsed.schema_name,
        }
        if not parsed.success:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_JSON_PARSE_FAILED
                if parsed.error_code == LLM_JSON_PARSE_FAILED
                else LLM_SCHEMA_VALIDATION_FAILED,
                detail=parsed.error_detail,
                extra=parse_trace,
            )
            return None
        output = parsed.data
        if not isinstance(output, AgentSelectionLLMOutput):
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=LLM_SCHEMA_VALIDATION_FAILED,
                detail="schema result type mismatch",
                extra=parse_trace,
            )
            return None
        selected_agent = output.selected_agent
        if selected_agent not in top_names:
            self.last_attempt = LLMAttempt(
                llm_status=LLM_STATUS_INVALID_OUTPUT,
                fallback_reason=AGENT_ROUTER_UNUSABLE,
                detail=f"selected_agent={selected_agent}",
                extra=parse_trace,
            )
            return None
        selected = next(candidate for candidate in candidates if candidate.agent_name == selected_agent)
        confidence = output.confidence
        need_clarification = output.need_clarification or confidence < self.min_confidence
        self.last_attempt = LLMAttempt(
            llm_status=LLM_STATUS_SUCCESS,
            extra=parse_trace,
        )
        return AgentSelectionResult(
            selected_agent=selected.agent_name,
            confidence=max(0.0, min(1.0, confidence)),
            reason=output.reason,
            required_context=selected.card.required_entities,
            risk_level="medium" if selected.missing_entities else "low",
            candidates=candidates,
            fallback=False,
            selection_method="llm_router",
            need_clarification=need_clarification,
            clarification_question=output.clarification_question,
            llm_status=LLM_STATUS_SUCCESS,
            fallback_used=False,
            decision_trace={
                "source": "agent_selection",
                "method": "llm_router",
                "llm_status": LLM_STATUS_SUCCESS,
                **parse_trace,
            },
        )
