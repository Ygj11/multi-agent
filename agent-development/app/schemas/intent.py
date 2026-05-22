from __future__ import annotations

"""意图识别结果 schema。"""

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """Intent recognition output.

    The new orchestrator treats this as task understanding only.  Agent
    routing and tool access are decided later from AgentCards.
    """

    intent: str
    confidence: float
    entities: dict[str, str] = Field(default_factory=dict)
    target_subagent: str | None = None
    required_tools: list[str] = Field(default_factory=list)
