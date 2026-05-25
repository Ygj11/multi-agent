from __future__ import annotations

"""LangGraph StateGraph 使用的状态定义。"""

from typing import Any, TypedDict


class AgentGraphState(TypedDict, total=False):
    """贯穿 LangGraph 节点的共享状态。"""

    request_id: str
    trace_id: str
    tenant_id: str
    channel: str
    user_id: str
    session_id: str
    session_key: str

    original_query: str
    rewritten_query: str
    intent: str
    sub_intent: str | None
    confidence: float
    entities: dict[str, Any]
    entity_bag: dict[str, Any]
    conversation_window: dict[str, Any]
    is_follow_up: bool
    target_subagent: str | None
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
    final_compliance_result: dict[str, Any] | None
    approval_required: bool
    approval_payloads: list[dict[str, Any]]
    approval_id: str | None
    approval_status: str | None
    approval_request: dict[str, Any] | None
    approval_submit_result: dict[str, Any] | None
    retry_count: int
    selected_skill_id: str | None
    selected_skill_metadata: dict[str, Any] | None
    skill_selection_score: float | None
    skill_selection_reason: str | None
    answer: str

    error: str | None
    graph_path: list[str]
