from __future__ import annotations

"""Human approval schemas for write-side tools."""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


ApprovalStatus = Literal[
    "created",
    "pending",
    "approved",
    "executing",
    "rejected",
    "expired",
    "submit_failed",
    "completed",
    "failed",
    "manual_intervention_required",
]


class ApprovalRequest(BaseModel):
    """A local approval request created before executing a write operation."""

    approval_id: str
    external_approval_id: str | None = None
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    thread_id: str | None = None
    checkpoint_id: str | None = None
    parent_approval_id: str | None = None
    root_approval_id: str | None = None
    approval_depth: int = 0
    next_approval_id: str | None = None
    approval_scope: str = "single_tool_call"
    idempotency_key: str | None = None
    tenant_id: str | None = None
    subject: str | None = None
    user_id: str | None = None
    org_id: str | None = None
    org_path: list[str] = Field(default_factory=list)
    principal_snapshot: dict[str, Any] = Field(default_factory=dict)
    auth_context_snapshot: dict[str, Any] = Field(default_factory=dict)
    resource_type: str | None = None
    resource_id: str | None = None
    tool_required_scopes: list[str] = Field(default_factory=list)
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
    resume_state: dict[str, Any] = Field(default_factory=dict)
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
