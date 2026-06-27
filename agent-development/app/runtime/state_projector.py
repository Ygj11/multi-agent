from __future__ import annotations

"""Projection helpers from runtime state to durable state contracts."""

from datetime import UTC, datetime
from typing import Any

from app.runtime.state_contracts import AgentResumeState, CheckpointSnapshot, EvidenceRef, MessageRef, ToolLogRef


CREDENTIAL_KEYS = {"api_key", "apikey", "token", "authorization", "password", "secret", "cookie"}


def project_checkpoint_snapshot(state: dict[str, Any]) -> CheckpointSnapshot:
    """Build a compact final-state snapshot from a rich graph state."""
    now = datetime.now(UTC).isoformat()
    subagent_result = _as_dict(state.get("subagent_result"))
    completion_result = _as_dict(state.get("task_completion_verification_result"))
    return CheckpointSnapshot(
        request_id=str(state.get("request_id") or ""),
        trace_id=_optional_str(state.get("trace_id")),
        tenant_id=_optional_str(state.get("tenant_id")),
        channel=_optional_str(state.get("channel")),
        user_id=_optional_str(state.get("user_id")),
        session_id=_optional_str(state.get("session_id")),
        session_key=str(state.get("session_key") or ""),
        thread_id=str(state.get("thread_id") or ""),
        created_at=now,
        updated_at=now,
        original_query=str(state.get("original_query") or ""),
        rewritten_query=_optional_str(state.get("rewritten_query")),
        rewrite_type=_optional_str(state.get("rewrite_type")),
        intent=_optional_str(state.get("intent")),
        sub_intent=_optional_str(state.get("sub_intent")),
        confidence=_optional_float(state.get("confidence")),
        entities=_drop_credential_fields(_as_dict(state.get("entities"))),
        selected_agent=_optional_str(state.get("selected_agent")),
        agent_selection_summary=_drop_credential_fields(_as_dict(state.get("agent_selection_summary"))),
        selected_skill_id=_optional_str(state.get("selected_skill_id") or subagent_result.get("selected_skill_id")),
        selected_skill_version=_optional_str(state.get("selected_skill_version")),
        task_completion_status=_optional_str(completion_result.get("status")),
        task_completion_summary=_optional_str(completion_result.get("summary")),
        task_completion_evidence_ids=_as_str_list(completion_result.get("evidence_ids")),
        repair_round=int(state.get("repair_round") or 0),
        repair_plan=_drop_credential_fields(_as_dict(state.get("repair_plan") or completion_result.get("repair_plan"))),
        last_repair_fingerprint=_optional_str(state.get("last_repair_fingerprint")),
        repair_no_progress_count=int(state.get("repair_no_progress_count") or 0),
        execution_mode=_optional_str(state.get("execution_mode")) or "initial",
        approval_required=bool(state.get("approval_required")),
        approval_id=_optional_str(state.get("approval_id")),
        approval_status=_optional_str(state.get("approval_status")),
        answer=_optional_str(state.get("answer")),
        error=_optional_str(state.get("error")),
        graph_path=[str(item) for item in state.get("graph_path") or []],
        tool_log_refs=_tool_refs_from_subagent_result(subagent_result),
        evidence_refs=_evidence_refs_from_subagent_result(subagent_result),
        message_refs=_message_refs_from_state(state),
    )


def project_approval_resume_state(
    state: dict[str, Any],
    *,
    pending_tool_call: dict[str, Any] | None = None,
    pending_messages: list[dict[str, Any]] | None = None,
    pending_tools: list[dict[str, Any]] | None = None,
    approval_id: str | None = None,
    approval_status: str | None = None,
    parent_approval_id: str | None = None,
    root_approval_id: str | None = None,
    approval_depth: int | None = None,
    resume_reason: str = "human_approval",
) -> AgentResumeState:
    """Build the minimal execution-resume payload for an interrupted flow."""
    subagent_result = _as_dict(state.get("subagent_result"))
    tool_call = _drop_credential_fields(_as_dict(pending_tool_call or state.get("pending_tool_call")))
    tool_name = _optional_str(tool_call.get("name") or tool_call.get("tool_name"))
    tool_arguments = _drop_credential_fields(_as_dict(tool_call.get("arguments") or {}))
    auth_context = _as_dict(state.get("auth_context"))
    principal = _as_dict(auth_context.get("principal"))
    return AgentResumeState(
        request_id=str(state.get("request_id") or ""),
        trace_id=_optional_str(state.get("trace_id")),
        tenant_id=_optional_str(state.get("tenant_id") or principal.get("tenant_id")),
        channel=_optional_str(state.get("channel")),
        user_id=_optional_str(state.get("user_id") or principal.get("user_id")),
        session_id=_optional_str(state.get("session_id")),
        session_key=str(state.get("session_key") or ""),
        thread_id=str(state.get("thread_id") or ""),
        auth_context_summary={
            "tenant_id": state.get("tenant_id") or principal.get("tenant_id"),
            "user_id": state.get("user_id") or principal.get("user_id"),
            "subject": principal.get("subject"),
            "org_id": principal.get("org_id"),
        },
        original_query=str(state.get("original_query") or ""),
        rewritten_query=_optional_str(state.get("rewritten_query")),
        intent=_optional_str(state.get("intent")),
        sub_intent=_optional_str(state.get("sub_intent")),
        entities=_drop_credential_fields(_as_dict(state.get("entities"))),
        selected_agent=_optional_str(state.get("selected_agent") or subagent_result.get("agent_name") or subagent_result.get("name")),
        selected_skill_id=_optional_str(state.get("selected_skill_id") or subagent_result.get("selected_skill_id")),
        selected_skill_metadata=_as_dict_or_none(subagent_result.get("selected_skill_metadata")),
        skill_selection_score=_optional_float(subagent_result.get("skill_selection_score")),
        skill_selection_reason=_optional_str(subagent_result.get("skill_selection_reason")),
        selected_skill_version=_optional_str(state.get("selected_skill_version")),
        execution_mode=_optional_str(state.get("execution_mode")) or "initial",
        repair_round=int(state.get("repair_round") or 0),
        repair_plan=_drop_credential_fields(_as_dict(state.get("repair_plan"))),
        repair_history=_drop_credential_fields(list(state.get("repair_history") or [])),
        last_repair_fingerprint=_optional_str(state.get("last_repair_fingerprint")),
        repair_no_progress_count=int(state.get("repair_no_progress_count") or 0),
        approval_id=approval_id or _optional_str(state.get("approval_id")),
        approval_status=approval_status or _optional_str(state.get("approval_status")),
        parent_approval_id=parent_approval_id or _optional_str(state.get("parent_approval_id")),
        root_approval_id=root_approval_id or _optional_str(state.get("root_approval_id")),
        approval_depth=int(approval_depth if approval_depth is not None else state.get("approval_depth") or 0),
        pending_tool_call=tool_call,
        pending_tool_name=tool_name,
        pending_tool_arguments=tool_arguments,
        pending_tool_is_write=True,
        pending_messages=list(pending_messages if pending_messages is not None else state.get("pending_messages") or []),
        pending_tools=list(pending_tools if pending_tools is not None else state.get("pending_tools") or []),
        tool_log_refs=_tool_refs_from_subagent_result(subagent_result),
        evidence_refs=_evidence_refs_from_subagent_result(subagent_result),
        resume_reason=resume_reason,
    )


def _tool_refs_from_subagent_result(subagent_result: dict[str, Any]) -> list[ToolLogRef]:
    refs: list[ToolLogRef] = []
    for item in subagent_result.get("tool_calls") or []:
        if not isinstance(item, dict):
            continue
        success = item.get("success")
        status = "success" if success is True else "failed" if success is False else None
        if item.get("needs_human_approval"):
            status = "pending_approval"
        refs.append(
            ToolLogRef(
                tool_name=_optional_str(item.get("name") or item.get("tool_name")),
                tool_call_id=_optional_str(item.get("tool_call_id") or item.get("id")),
                execution_id=_optional_str(item.get("execution_id")),
                status=status,
                approval_id=_optional_str(item.get("approval_id")),
                error=_optional_str(item.get("error")),
            )
        )
    for payload in subagent_result.get("approval_payloads") or []:
        if isinstance(payload, dict):
            refs.append(
                ToolLogRef(
                    tool_name=_optional_str(payload.get("tool_name")),
                    status="pending_approval",
                    approval_id=_optional_str(payload.get("approval_id")),
                )
            )
    return refs


def _evidence_refs_from_subagent_result(subagent_result: dict[str, Any]) -> list[EvidenceRef]:
    refs: list[EvidenceRef] = []
    for item in subagent_result.get("evidence") or []:
        if not isinstance(item, dict):
            continue
        refs.append(
            EvidenceRef(
                evidence_id=_optional_str(item.get("evidence_id") or item.get("id")),
                type=_optional_str(item.get("type")),
                source=_optional_str(item.get("source")),
                tool_name=_optional_str(item.get("tool_name")),
                summary=_optional_str(item.get("summary")),
                created_at=_optional_str(item.get("created_at")),
            )
        )
    return refs


def _message_refs_from_state(state: dict[str, Any]) -> list[MessageRef]:
    session_key = str(state.get("session_key") or "")
    request_id = _optional_str(state.get("request_id"))
    if not session_key:
        return []
    return [
        MessageRef(session_key=session_key, request_id=request_id, role="user"),
        MessageRef(session_key=session_key, request_id=request_id, role="assistant"),
    ]


def _drop_credential_fields(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if str(key).lower() in CREDENTIAL_KEYS:
                continue
            sanitized[key] = _drop_credential_fields(item)
        return sanitized
    if isinstance(value, list):
        return [_drop_credential_fields(item) for item in value]
    return value


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_dict_or_none(value: Any) -> dict[str, Any] | None:
    return value if isinstance(value, dict) else None


def _optional_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_float(value: Any) -> float | None:
    try:
        return float(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _as_str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if item not in (None, "")]
