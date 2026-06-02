from __future__ import annotations

"""Verification service schemas."""

from typing import Any, Literal

from pydantic import BaseModel, Field


VerificationStage = Literal["request_access", "agent_access", "pre_skill", "pre_tool", "post_tool", "pre_answer"]
VerificationAction = Literal["allow", "patch", "block", "manual", "retry"]


class VerificationInput(BaseModel):
    stage: VerificationStage
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
    principal: dict[str, Any] | None = None
    auth_context: dict[str, Any] = Field(default_factory=dict)
    agent_name: str | None = None
    skill_id: str | None = None
    tool_name: str | None = None
    tool_arguments: dict[str, Any] = Field(default_factory=dict)
    tool_result: Any | None = None
    answer: str | None = None
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VerificationResult(BaseModel):
    passed: bool
    stage: str
    verifier_name: str
    severity: Literal["info", "warning", "error", "blocking"] = "info"
    action: VerificationAction = "allow"
    code: str | None = None
    reason: str | None = None
    patched_output: Any | None = None
    redactions: list[dict[str, Any]] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)

