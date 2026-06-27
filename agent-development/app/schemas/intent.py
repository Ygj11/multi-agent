from __future__ import annotations

"""意图识别结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class IntentResult(BaseModel):
    """意图识别输出。

    该结果只表达业务 intent/sub_intent、置信度和澄清状态。Agent 路由、
    Skill 选择和工具权限都在后续阶段完成；这里也不携带 canonical entities。
    """

    intent: str
    sub_intent: str | None = None
    confidence: float
    need_clarification: bool = False
    clarification_question: str | None = None
    reason: str = ""
    llm_status: str | None = None
    fallback_used: bool = False
    fallback_source: str | None = None
    fallback_reason: str | None = None
    decision_trace: dict[str, Any] = Field(default_factory=dict)
