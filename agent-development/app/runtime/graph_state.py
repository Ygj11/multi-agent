from __future__ import annotations

"""LangGraph StateGraph 使用的状态定义。"""

from typing import Any, TypedDict


GRAPH_STATE_FIELD_AUTHORITY: dict[str, dict[str, str]] = {
    "request_id": {"owner": "request_identity", "source": "RequestAdapter / AgentOrchestrator", "kind": "authoritative"},
    "trace_id": {"owner": "request_identity", "source": "RequestAdapter / AgentOrchestrator", "kind": "authoritative"},
    "tenant_id": {"owner": "request_identity", "source": "RequestAdapter auth_context", "kind": "authoritative"},
    "channel": {"owner": "request_identity", "source": "RequestAdapter", "kind": "authoritative"},
    "user_id": {"owner": "request_identity", "source": "RequestAdapter auth_context", "kind": "authoritative"},
    "session_id": {"owner": "session_identity", "source": "RequestAdapter", "kind": "authoritative"},
    "session_key": {"owner": "session_identity", "source": "RequestAdapter", "kind": "authoritative"},
    "thread_id": {"owner": "graph_execution", "source": "AgentOrchestrator", "kind": "authoritative"},
    "auth_context": {"owner": "auth", "source": "RequestAdapter", "kind": "authoritative"},
    "original_query": {"owner": "request", "source": "RequestAdapter", "kind": "authoritative"},
    "rewritten_query": {"owner": "understanding", "source": "query_rewrite", "kind": "authoritative"},
    "intent": {"owner": "understanding", "source": "intent_recognition", "kind": "authoritative"},
    "sub_intent": {"owner": "understanding", "source": "intent_recognition", "kind": "authoritative"},
    "confidence": {"owner": "understanding", "source": "intent_recognition / agent_selection", "kind": "authoritative"},
    "entities": {"owner": "routing_compact_entities", "source": "query_rewrite + intent_recognition", "kind": "authoritative"},
    "entity_bag": {"owner": "rich_entities", "source": "query_rewrite", "kind": "authoritative"},
    "conversation_window": {"owner": "history_snapshot", "source": "query_rewrite", "kind": "snapshot"},
    "is_follow_up": {"owner": "understanding", "source": "query_rewrite", "kind": "authoritative"},
    "need_clarification": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / select_agent / subagent_result",
        "kind": "authoritative",
    },
    "clarification_question": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / select_agent / subagent_result",
        "kind": "authoritative",
    },
    "clarification_source": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / select_agent / subagent_result",
        "kind": "authoritative",
    },
    "missing_required_entities": {
        "owner": "clarification_route",
        "source": "query_rewrite / intent_recognition / subagent required-entity check",
        "kind": "authoritative",
    },
    "recent_messages": {"owner": "memory_snapshot", "source": "load_session", "kind": "snapshot"},
    "short_summary": {"owner": "memory_snapshot", "source": "load_session / compress_short_memory", "kind": "snapshot"},
    "orchestrator_context": {"owner": "derived_context_snapshot", "source": "build_orchestrator_context", "kind": "snapshot"},
    "available_agents": {"owner": "debug_trace", "source": "discover_agents", "kind": "debug"},
    "agent_selection": {"owner": "routing_trace", "source": "select_agent", "kind": "snapshot"},
    "selected_agent": {"owner": "routing", "source": "select_agent", "kind": "authoritative"},
    "selected_agent_card": {"owner": "routing", "source": "select_agent", "kind": "snapshot"},
    "assembled_task": {"owner": "execution_input", "source": "assemble_task", "kind": "authoritative"},
    "subagent_result": {"owner": "execution_result", "source": "dispatch_agent / resume_approved_tool", "kind": "authoritative"},
    "verification_results": {"owner": "verification_trace", "source": "pre_answer_verify", "kind": "debug"},
    "pre_answer_verification_result": {"owner": "verification_route", "source": "pre_answer_verify", "kind": "authoritative"},
    "approval_required": {"owner": "approval_summary", "source": "check_human_approval_required", "kind": "authoritative"},
    "approval_payloads": {"owner": "approval_summary", "source": "subagent_result.approval_payloads", "kind": "snapshot"},
    "approval_id": {"owner": "approval_summary", "source": "create_approval_request / ApprovalStore", "kind": "authoritative"},
    "approval_status": {"owner": "approval_summary", "source": "ApprovalStore", "kind": "authoritative"},
    "approval_submit_result": {"owner": "approval_trace", "source": "submit_approval_request", "kind": "snapshot"},
    "approval_resume": {"owner": "approval_route", "source": "ApprovalService.resume_graph_after_approval", "kind": "authoritative"},
    "pending_messages": {"owner": "approval_resume_snapshot", "source": "ApprovalStore.pending_messages", "kind": "snapshot"},
    "pending_tools": {"owner": "approval_resume_snapshot", "source": "ApprovalStore.pending_tools", "kind": "snapshot"},
    "pending_tool_call": {"owner": "approval_resume_snapshot", "source": "ApprovalStore.pending_tool_call", "kind": "snapshot"},
    "current_approval_id": {"owner": "approval_chain", "source": "ApprovalStore / resume_approved_tool", "kind": "authoritative"},
    "root_approval_id": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "authoritative"},
    "parent_approval_id": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "authoritative"},
    "next_approval_id": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "authoritative"},
    "approval_depth": {"owner": "approval_chain", "source": "ApprovalStore", "kind": "authoritative"},
    "manual_intervention_required": {
        "owner": "approval_route",
        "source": "create_approval_request chain-depth guard",
        "kind": "authoritative",
    },
    "retry_count": {"owner": "verification_route", "source": "load_session / regenerate_compliant_answer", "kind": "authoritative"},
    "answer": {"owner": "response_text", "source": "dispatch / clarification / approval / pre_answer_verify", "kind": "authoritative"},
    "error": {"owner": "error_trace", "source": "node-specific controlled failures", "kind": "debug"},
    "graph_path": {"owner": "debug_trace", "source": "AgentGraphFactory node wrappers", "kind": "debug"},
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
