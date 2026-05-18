from __future__ import annotations

"""知识检索结果 schema。"""

from typing import Any

from pydantic import BaseModel, Field


class KnowledgeChunk(BaseModel):
    """KnowledgeService 返回的最小知识片段。"""

    content: str
    source: str
    score: float
    metadata: dict[str, Any] = Field(default_factory=dict)

