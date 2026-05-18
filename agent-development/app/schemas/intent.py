from __future__ import annotations

"""意图识别结果 schema。"""

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """意图识别节点输出，供 LangGraph 条件路由和工具授权使用。"""

    intent: str
    confidence: float
    target_subagent: str | None = None
    required_tools: list[str] = Field(default_factory=list)
