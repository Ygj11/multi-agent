from __future__ import annotations

"""LLM re-ranker for ambiguous AgentCard candidates."""

from typing import Any

from app.llm.base import LLMProvider
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.query.json_utils import parse_json_object
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
    ) -> AgentSelectionResult | None:
        """Return LLM-selected candidate or None when the router output is unusable."""
        if self.llm_provider is None or not candidates:
            return None
        top_names = {candidate.agent_name for candidate in candidates}
        summaries = [
            {
                "agent_name": candidate.agent_name,
                "description": candidate.card.description,
                "supported_intents": candidate.card.supported_intents,
                "capabilities": candidate.card.capabilities,
                "required_entities": candidate.card.required_entities,
                "optional_entities": candidate.card.optional_entities,
                "examples": candidate.card.examples,
                "rule_score": candidate.score,
                "missing_entities": candidate.missing_entities,
            }
            for candidate in candidates
        ]
        response = await self.llm_provider.chat(
            messages=[
                {
                    "role": "system",
                    "content": self.prompt_loader.render("agent_selection/system.md"),
                },
                {
                    "role": "user",
                    "content": self.prompt_loader.render(
                        "agent_selection/user.md",
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
        )
        data = parse_json_object(response.content)
        if data is None:
            return None
        selected_agent = str(data.get("selected_agent") or "")
        if selected_agent not in top_names:
            return None
        selected = next(candidate for candidate in candidates if candidate.agent_name == selected_agent)
        confidence = float(data.get("confidence", 0.0) or 0.0)
        need_clarification = bool(data.get("need_clarification", False)) or confidence < self.min_confidence
        return AgentSelectionResult(
            selected_agent=selected.agent_name,
            confidence=max(0.0, min(1.0, confidence)),
            reason=str(data.get("reason") or "llm_router"),
            required_context=selected.card.required_entities,
            risk_level="medium" if selected.missing_entities else "low",
            candidates=candidates,
            fallback=False,
            selection_method="llm_router",
            need_clarification=need_clarification,
            clarification_question=data.get("clarification_question"),
        )
