from __future__ import annotations

"""Human approval extension point for write-side tools."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ApprovalStatus = Literal["pending", "approved", "rejected", "expired"]


class ApprovalRequest(BaseModel):
    """A local approval request created before executing a write operation."""

    approval_id: str
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    agent_name: str
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    status: ApprovalStatus = "pending"
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
