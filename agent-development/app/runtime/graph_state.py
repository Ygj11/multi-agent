from __future__ import annotations

"""LangGraph StateGraph 使用的状态定义。"""

from typing import Any, TypedDict


GRAPH_STATE_FIELD_AUTHORITY: dict[str, dict[str, str]] = {
    "request_id": {"owner": "request_identity", "source": "RequestAdapter / AgentOrchestrator", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "trace_id": {"owner": "request_identity", "source": "RequestAdapter / AgentOrchestrator", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "tenant_id": {"owner": "request_identity", "source": "RequestAdapter auth_context", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "channel": {"owner": "request_identity", "source": "RequestAdapter", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "user_id": {"owner": "request_identity", "source": "RequestAdapter auth_context", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "session_id": {"owner": "session_identity", "source": "RequestAdapter", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "session_key": {"owner": "session_identity", "source": "RequestAdapter", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "thread_id": {"owner": "graph_execution", "source": "AgentOrchestrator", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "auth_context": {"owner": "auth", "source": "RequestAdapter", "kind": "resume", "persistence": "approval_store"},
    "original_query": {"owner": "request", "source": "RequestAdapter", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "rewritten_query": {"owner": "understanding", "source": "query_rewrite", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "intent": {"owner": "understanding", "source": "intent_recognition", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "sub_intent": {"owner": "understanding", "source": "intent_recognition", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "confidence": {"owner": "understanding", "source": "intent_recognition / agent_selection", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "entities": {"owner": "routing_compact_entities", "source": "query_rewrite + intent_recognition", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "entity_bag": {"owner": "rich_entities", "source": "query_rewrite", "kind": "runtime", "persistence": "none"},
    "conversation_window": {"owner": "history_snapshot", "source": "query_rewrite", "kind": "runtime", "persistence": "none"},
    "is_follow_up": {"owner": "understanding", "source": "query_rewrite", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "need_clarification": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / select_agent / subagent_result",
        "kind": "checkpoint",
        "persistence": "checkpoint_snapshot",
    },
    "clarification_question": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / select_agent / subagent_result",
        "kind": "checkpoint",
        "persistence": "checkpoint_snapshot",
    },
    "clarification_source": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / select_agent / subagent_result",
        "kind": "checkpoint",
        "persistence": "checkpoint_snapshot",
    },
    "missing_required_entities": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / subagent required-entity check",
        "kind": "checkpoint",
        "persistence": "checkpoint_snapshot",
    },
    "recent_messages": {"owner": "memory_snapshot", "source": "load_session", "kind": "runtime", "persistence": "none"},
    "short_summary": {"owner": "memory_snapshot", "source": "load_session / compress_short_memory", "kind": "memory", "persistence": "message_store"},
    "orchestrator_context": {"owner": "derived_context_snapshot", "source": "build_orchestrator_context", "kind": "runtime", "persistence": "none"},
    "available_agents": {"owner": "debug_trace", "source": "discover_agents", "kind": "debug_temporary", "persistence": "none"},
    "agent_selection": {"owner": "routing_trace", "source": "select_agent", "kind": "debug_temporary", "persistence": "none"},
    "selected_agent": {"owner": "routing", "source": "select_agent", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "selected_agent_card": {"owner": "routing", "source": "select_agent", "kind": "runtime", "persistence": "none"},
    "assembled_task": {"owner": "execution_input", "source": "assemble_task", "kind": "runtime", "persistence": "none"},
    "subagent_result": {"owner": "execution_result", "source": "dispatch_agent / resume_approved_tool", "kind": "runtime", "persistence": "none"},
    "verification_results": {"owner": "verification_trace", "source": "pre_answer_verify", "kind": "debug_temporary", "persistence": "none"},
    "pre_answer_verification_result": {"owner": "verification_route", "source": "pre_answer_verify", "kind": "runtime", "persistence": "none"},
    "approval_required": {"owner": "approval_summary", "source": "check_human_approval_required", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "approval_payloads": {"owner": "approval_summary", "source": "subagent_result.approval_payloads", "kind": "runtime", "persistence": "none"},
    "approval_id": {"owner": "approval_summary", "source": "create_approval_request / ApprovalStore", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "approval_status": {"owner": "approval_summary", "source": "ApprovalStore", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "approval_submit_result": {"owner": "approval_trace", "source": "submit_approval_request", "kind": "audit", "persistence": "approval_store"},
    "approval_resume": {"owner": "approval_route", "source": "ApprovalService.resume_graph_after_approval", "kind": "runtime", "persistence": "none"},
    "pending_messages": {"owner": "approval_resume_snapshot", "source": "ApprovalStore.pending_messages", "kind": "resume", "persistence": "resume_state"},
    "pending_tools": {"owner": "approval_resume_snapshot", "source": "ApprovalStore.pending_tools", "kind": "resume", "persistence": "resume_state"},
    "pending_tool_call": {"owner": "approval_resume_snapshot", "source": "ApprovalStore.pending_tool_call", "kind": "resume", "persistence": "resume_state"},
    "current_approval_id": {"owner": "approval_chain", "source": "ApprovalStore / resume_approved_tool", "kind": "resume", "persistence": "approval_store"},
    "root_approval_id": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "resume", "persistence": "approval_store"},
    "parent_approval_id": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "resume", "persistence": "approval_store"},
    "next_approval_id": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "resume", "persistence": "approval_store"},
    "approval_depth": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "resume", "persistence": "approval_store"},
    "manual_intervention_required": {
        "owner": "approval_route",
        "source": "create_approval_request chain-depth guard",
        "kind": "checkpoint",
        "persistence": "checkpoint_snapshot",
    },
    "retry_count": {"owner": "verification_route", "source": "load_session / regenerate_compliant_answer", "kind": "runtime", "persistence": "none"},
    "answer": {"owner": "response_text", "source": "dispatch / clarification / approval / pre_answer_verify", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "error": {"owner": "error_trace", "source": "node-specific controlled failures", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "graph_path": {"owner": "debug_trace", "source": "AgentGraphFactory node wrappers", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
}


class AgentGraphState(TypedDict, total=False):
    """贯穿 LangGraph 节点的共享状态。"""

    request_id: str
    trace_id: str
    tenant_id: str
    channel: str
    user_id: str
    session_id: str
    session_key: str
    thread_id: str
    auth_context: dict[str, Any] | None

    original_query: str
    rewritten_query: str
    intent: str
    sub_intent: str | None
    confidence: float
    entities: dict[str, Any]
    entity_bag: dict[str, Any]
    conversation_window: dict[str, Any]
    is_follow_up: bool
    need_clarification: bool
    clarification_question: str | None
    clarification_source: str | None
    missing_required_entities: list[str]

    recent_messages: list[dict[str, Any]]
    short_summary: str | None

    orchestrator_context: dict[str, Any]
    available_agents: list[dict[str, Any]]
    agent_selection: dict[str, Any]
    selected_agent: str | None
    selected_agent_card: dict[str, Any] | None
    assembled_task: dict[str, Any] | None
    subagent_result: dict[str, Any] | None
    verification_results: list[dict[str, Any]]
    pre_answer_verification_result: dict[str, Any] | None
    approval_required: bool
    approval_payloads: list[dict[str, Any]]
    approval_id: str | None
    approval_status: str | None
    approval_submit_result: dict[str, Any] | None
    approval_resume: bool
    pending_messages: list[dict[str, Any]]
    pending_tools: list[dict[str, Any]]
    pending_tool_call: dict[str, Any] | None
    current_approval_id: str | None
    root_approval_id: str | None
    parent_approval_id: str | None
    next_approval_id: str | None
    approval_depth: int
    manual_intervention_required: bool
    retry_count: int
    answer: str

    error: str | None
    graph_path: list[str]
