from __future__ import annotations

"""Agent selection node implementation."""

from typing import Any

from app.agents.card_loader import AgentCardLoader
from app.llm.base import LLMProvider
from app.observability.logger import log_event
from app.schemas.agent_card import AgentSelectionResult


class AgentSelectionNode:
    """Selects the best sub agent from AgentCards.

    The first implementation is deterministic rule scoring.  The return shape
    mirrors the future LLM JSON decision so the node can be swapped later.
    """

    def __init__(self, card_loader: AgentCardLoader, llm_provider: LLMProvider | None = None) -> None:
        self.card_loader = card_loader
        self.llm_provider = llm_provider

    async def select(
        self,
        *,
        intent: str,
        entities: dict[str, Any],
        query: str,
        request_id: str | None = None,
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> AgentSelectionResult:
        candidates = self.card_loader.match_candidates(intent=intent, entities=entities, query=query)
        if not candidates:
            raise ValueError("no available AgentCard candidates")

        selected = candidates[0]
        fallback = selected.score <= 0
        confidence = min(0.99, max(0.2, selected.score / 12))
        risk_level = "medium" if selected.missing_entities else "low"
        result = AgentSelectionResult(
            selected_agent=selected.agent_name,
            confidence=confidence,
            reason=selected.reason,
            required_context=selected.card.required_entities,
            risk_level=risk_level,
            candidates=candidates,
            fallback=fallback,
        )
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
                "candidate_count": len(candidates),
                "reason": result.reason,
            },
        )
        return result
