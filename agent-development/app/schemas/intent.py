from __future__ import annotations

"""意图识别结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """Intent recognition output.

    The new orchestrator treats this as task understanding only.  Agent
    routing and tool access are decided later from AgentCards.
    """

    intent: str
    sub_intent: str | None = None
    confidence: float
    missing_required_entities: list[str] = Field(default_factory=list)
    need_clarification: bool = False
    clarification_question: str | None = None
    is_follow_up: bool = False
    reason: str = ""
    target_subagent: str | None = None
    llm_status: str | None = None
    fallback_used: bool = False
    fallback_source: str | None = None
    fallback_reason: str | None = None
    decision_trace: dict[str, Any] = Field(default_factory=dict)
