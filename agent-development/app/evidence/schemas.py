from __future__ import annotations

"""Evidence schemas used by verification and audit."""

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
    content: Any
    summary: str | None = None
    citations: list[dict[str, Any]] = Field(default_factory=list)
    redactions: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())

