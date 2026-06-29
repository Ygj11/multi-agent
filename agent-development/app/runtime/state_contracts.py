from __future__ import annotations

"""Durable runtime-state contracts.

These models are the explicit persistence boundary for graph execution state.
`AgentGraphState` may stay rich while the stored payloads remain compact and
purpose-specific.
"""

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


StateFieldKind = Literal[
    "runtime",
    "checkpoint",
    "resume",
    "memory",
    "audit",
    "debug_temporary",
    "reference",
    "deprecated",
]

StatePersistenceTarget = Literal[
    "none",
    "checkpoint_snapshot",
    "resume_state",
    "message_store",
    "tool_log_store",
    "evidence_store",
    "approval_store",
]


class ToolLogRef(BaseModel):
    """Lightweight reference to a tool execution fact."""

    tool_name: str | None = None
    tool_call_id: str | None = None
    execution_id: str | None = None
    status: str | None = None
    approval_id: str | None = None
    error: str | None = None


class EvidenceRef(BaseModel):
    """Lightweight reference to structured evidence."""

    evidence_id: str | None = None
    type: str | None = None
    source: str | None = None
    tool_name: str | None = None
    summary: str | None = None
    created_at: str | None = None


class MessageRef(BaseModel):
    """Lightweight reference to messages related to a request."""

    session_key: str
    request_id: str | None = None
    role: str | None = None


class CheckpointSnapshot(BaseModel):
    """Compact final-state snapshot for one graph request."""

    schema_version: int = 1
    request_id: str
    trace_id: str | None = None
    tenant_id: str | None = None
    channel: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    session_key: str
    thread_id: str
    created_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    updated_at: str = Field(default_factory=lambda: datetime.now(UTC).isoformat())
    original_query: str
    rewritten_query: str | None = None
    rewrite_type: str | None = None
    intent: str | None = None
    sub_intent: str | None = None
    confidence: float | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    selected_agent: str | None = None
    agent_selection_summary: dict[str, Any] = Field(default_factory=dict)
    selected_skill_id: str | None = None
    selected_skill_version: str | None = None
    task_completion_status: str | None = None
    task_completion_summary: str | None = None
    task_completion_evidence_ids: list[str] = Field(default_factory=list)
    repair_round: int = 0
    repair_plan: dict[str, Any] = Field(default_factory=dict)
    last_repair_fingerprint: str | None = None
    repair_no_progress_count: int = 0
    execution_mode: str = "initial"
    approval_required: bool = False
    approval_id: str | None = None
    approval_status: str | None = None
    answer: str | None = None
    error: str | None = None
    graph_path: list[str] = Field(default_factory=list)
    tool_log_refs: list[ToolLogRef] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    message_refs: list[MessageRef] = Field(default_factory=list)


class AgentResumeState(BaseModel):
    """Minimal state needed to resume an interrupted agent flow."""

    schema_version: int = 1
    request_id: str
    trace_id: str | None = None
    tenant_id: str | None = None
    channel: str | None = None
    user_id: str | None = None
    session_id: str | None = None
    session_key: str
    thread_id: str
    auth_context_summary: dict[str, Any] = Field(default_factory=dict)
    result_callback_url: str | None = None
    original_query: str
    rewritten_query: str | None = None
    intent: str | None = None
    sub_intent: str | None = None
    entities: dict[str, Any] = Field(default_factory=dict)
    selected_agent: str | None = None
    selected_skill_id: str | None = None
    selected_skill_metadata: dict[str, Any] | None = None
    skill_selection_score: float | None = None
    skill_selection_reason: str | None = None
    selected_skill_version: str | None = None
    execution_mode: str = "initial"
    repair_round: int = 0
    repair_plan: dict[str, Any] = Field(default_factory=dict)
    repair_history: list[dict[str, Any]] = Field(default_factory=list)
    last_repair_fingerprint: str | None = None
    repair_no_progress_count: int = 0
    approval_id: str | None = None
    approval_status: str | None = None
    parent_approval_id: str | None = None
    root_approval_id: str | None = None
    approval_depth: int = 0
    pending_tool_call: dict[str, Any] = Field(default_factory=dict)
    pending_tool_name: str | None = None
    pending_tool_arguments: dict[str, Any] = Field(default_factory=dict)
    pending_tool_is_write: bool = True
    pending_messages: list[dict[str, Any]] = Field(default_factory=list)
    pending_tools: list[dict[str, Any]] = Field(default_factory=list)
    tool_log_refs: list[ToolLogRef] = Field(default_factory=list)
    evidence_refs: list[EvidenceRef] = Field(default_factory=list)
    resume_reason: str = "human_approval"

    def to_graph_state(self) -> dict[str, Any]:
        """Build the minimal runtime state required by the resume graph path."""
        return {
            "request_id": self.request_id,
            "trace_id": self.trace_id,
            "tenant_id": self.tenant_id,
            "channel": self.channel,
            "user_id": self.user_id,
            "session_id": self.session_id,
            "session_key": self.session_key,
            "thread_id": self.thread_id,
            "result_callback_url": self.result_callback_url,
            "original_query": self.original_query,
            "rewritten_query": self.rewritten_query or self.original_query,
            "intent": self.intent or "unknown",
            "sub_intent": self.sub_intent,
            "entities": dict(self.entities),
            "selected_agent": self.selected_agent,
            "selected_skill_id": self.selected_skill_id,
            "selected_skill_version": self.selected_skill_version,
            "execution_mode": self.execution_mode,
            "repair_round": self.repair_round,
            "repair_plan": dict(self.repair_plan),
            "repair_history": list(self.repair_history),
            "last_repair_fingerprint": self.last_repair_fingerprint,
            "repair_no_progress_count": self.repair_no_progress_count,
            "approval_id": self.approval_id,
            "approval_status": self.approval_status,
            "parent_approval_id": self.parent_approval_id,
            "root_approval_id": self.root_approval_id,
            "approval_depth": self.approval_depth,
            "pending_messages": list(self.pending_messages),
            "pending_tools": list(self.pending_tools),
            "pending_tool_call": dict(self.pending_tool_call),
            "subagent_result": {
                "selected_skill_id": self.selected_skill_id,
                "selected_skill_metadata": self.selected_skill_metadata,
                "skill_selection_score": self.skill_selection_score,
                "skill_selection_reason": self.skill_selection_reason,
            },
            "error": None,
            "graph_path": [],
        }


class StateFieldPolicy(BaseModel):
    """Lifecycle policy for a field in `AgentGraphState`."""

    owner: str
    source: str
    kind: StateFieldKind
    persistence: StatePersistenceTarget = "none"
