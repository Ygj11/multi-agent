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
    confidence: float
    target_subagent: str | None
    required_tools: list[str]

    recent_messages: list[dict[str, Any]]
    short_summary: str | None

    orchestrator_context: dict[str, Any]
    subagent_result: dict[str, Any] | None
    selected_skill_id: str | None
    selected_skill_metadata: dict[str, Any] | None
    skill_selection_score: float | None
    skill_selection_reason: str | None
    answer: str

    error: str | None
    graph_path: list[str]
