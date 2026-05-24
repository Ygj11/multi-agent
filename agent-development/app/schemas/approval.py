from __future__ import annotations

"""Human approval schemas for write-side tools."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ApprovalStatus = Literal["created", "pending", "approved", "rejected", "expired", "submit_failed", "completed"]


class ApprovalRequest(BaseModel):
    """A local approval request created before executing a write operation."""

    approval_id: str
    external_approval_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    agent_name: str
    tool_name: str
    operation_type: str = "write"
    risk_level: str = "high"
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str
    status: ApprovalStatus = "created"
    callback_url: str | None = None
    pending_state: dict[str, Any] = Field(default_factory=dict)
    pending_messages: list[dict[str, Any]] = Field(default_factory=list)
    pending_tools: list[dict[str, Any]] = Field(default_factory=list)
    pending_tool_call: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any] | None = None
    final_answer: str | None = None
    error: str | None = None
    approver: str | None = None
    comment: str | None = None
    decided_at: str | None = None
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())


class ApprovalSubmitResult(BaseModel):
    """Result returned by the external approval system."""

    accepted: bool
    external_approval_id: str | None = None
    status: ApprovalStatus = "pending"
    error: str | None = None
    raw_response: dict[str, Any] | None = None


class ApprovalCallbackRequest(BaseModel):
    """Callback payload sent by the external approval system."""

    approval_id: str
    external_approval_id: str | None = None
    status: Literal["approved", "rejected"]
    approver: str | None = None
    comment: str | None = None
    decided_at: str | None = None
    signature: str | None = None


class ApprovalCallbackResponse(BaseModel):
    """API response for approval callbacks."""

    approval_id: str
    status: ApprovalStatus
    resumed: bool
    final_answer: str | None = None
    error: str | None = None


class ApprovalCallbackHandleResult(BaseModel):
    """Internal result of callback handling."""

    approval_request: ApprovalRequest
    resumed: bool = False
    final_answer: str | None = None
    error: str | None = None
    already_processed: bool = False


class ApprovalResumeResult(BaseModel):
    """Internal result after resuming a paused approval flow."""

    approval_id: str
    status: ApprovalStatus
    final_answer: str | None = None
    error: str | None = None
    tool_result: dict[str, Any] | None = None
