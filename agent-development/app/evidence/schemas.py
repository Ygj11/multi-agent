from __future__ import annotations

"""验证与审计使用的 Evidence schema。

Evidence 是给答案验证、Repair 和审计使用的轻量证据索引，不保存完整工具
返回。工具执行完整事实保存在 tool_execution_logs，Evidence 只通过
tool_log_id 建立引用，并保留可直接给 Verifier 使用的 summary。
"""

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, Field


EvidenceSourceType = Literal["tool", "knowledge", "user", "system", "approval"]


class Evidence(BaseModel):
    evidence_id: str = Field(default_factory=lambda: f"evidence_{uuid4().hex}")
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str
    source_type: EvidenceSourceType
    source_name: str
    tool_log_id: int | None = None
    summary: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
