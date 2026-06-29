from __future__ import annotations

"""LangGraph StateGraph 使用的状态定义。"""

from typing import Any, TypedDict

from app.schemas.enums.query import RewriteType


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
    "result_callback_url": {
        "owner": "approval_result_callback",
        "source": "RequestAdapter",
        "kind": "resume",
        "persistence": "resume_state",
    },
    "original_query": {"owner": "request", "source": "RequestAdapter", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "rewritten_query": {"owner": "understanding", "source": "query_rewrite", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "rewrite_type": {"owner": "understanding", "source": "query_rewrite", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "query_rewrite_decision_trace": {"owner": "understanding_trace", "source": "query_rewrite", "kind": "debug_temporary", "persistence": "none"},
    "query_rewrite_llm_status": {"owner": "understanding_trace", "source": "query_rewrite", "kind": "debug_temporary", "persistence": "none"},
    "query_rewrite_fallback_reason": {"owner": "understanding_trace", "source": "query_rewrite", "kind": "debug_temporary", "persistence": "none"},
    "intent": {"owner": "understanding", "source": "intent_recognition", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "sub_intent": {"owner": "understanding", "source": "intent_recognition", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "intent_decision_trace": {"owner": "understanding_trace", "source": "intent_recognition", "kind": "debug_temporary", "persistence": "none"},
    "intent_llm_status": {"owner": "understanding_trace", "source": "intent_recognition", "kind": "debug_temporary", "persistence": "none"},
    "intent_fallback_reason": {"owner": "understanding_trace", "source": "intent_recognition", "kind": "debug_temporary", "persistence": "none"},
    "confidence": {"owner": "understanding", "source": "intent_recognition / agent_selection", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "entities": {"owner": "routing_compact_entities", "source": "query_rewrite entity_bag projection", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "entity_bag": {"owner": "canonical_entities", "source": "query_rewrite + EntityResolver", "kind": "runtime", "persistence": "none"},
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
        "source": "query_rewrite / subagent required-entity check",
        "kind": "checkpoint",
        "persistence": "checkpoint_snapshot",
    },
    "recent_messages": {"owner": "memory_snapshot", "source": "load_session", "kind": "runtime", "persistence": "none"},
    "short_summary": {"owner": "memory_snapshot", "source": "load_session / compress_short_memory", "kind": "memory", "persistence": "message_store"},
    "orchestrator_context": {"owner": "derived_context_snapshot", "source": "build_orchestrator_context", "kind": "runtime", "persistence": "none"},
    "agent_selection_summary": {"owner": "routing_trace", "source": "select_agent", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "agent_selection_decision_trace": {"owner": "routing_trace", "source": "select_agent", "kind": "debug_temporary", "persistence": "none"},
    "agent_selection_llm_status": {"owner": "routing_trace", "source": "select_agent", "kind": "debug_temporary", "persistence": "none"},
    "agent_selection_fallback_reason": {"owner": "routing_trace", "source": "select_agent", "kind": "debug_temporary", "persistence": "none"},
    "selected_agent": {"owner": "routing", "source": "select_agent", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "selected_skill_id": {"owner": "skill_pin", "source": "dispatch_agent / dispatch_repair_agent", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "selected_skill_version": {"owner": "skill_pin", "source": "collect_verification_evidence", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "subagent_result": {"owner": "execution_result", "source": "dispatch_agent / resume_approved_tool", "kind": "runtime", "persistence": "none"},
    "task_completion_verification_result": {
        "owner": "completion_verification",
        "source": "verify_task_completion",
        "kind": "runtime",
        "persistence": "none",
    },
    "verification_evidence": {"owner": "completion_evidence", "source": "collect_verification_evidence", "kind": "runtime", "persistence": "none"},
    "task_completion_verification_context": {
        "owner": "completion_evidence",
        "source": "collect_verification_evidence",
        "kind": "runtime",
        "persistence": "none",
    },
    "repair_plan": {"owner": "repair_control", "source": "verify_task_completion", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "repair_round": {"owner": "repair_control", "source": "build_repair_task", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "repair_history": {"owner": "repair_audit", "source": "verify_task_completion", "kind": "resume", "persistence": "resume_state"},
    "last_repair_fingerprint": {"owner": "repair_guard", "source": "verify_task_completion", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "repair_no_progress_count": {"owner": "repair_guard", "source": "verify_task_completion", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "execution_mode": {"owner": "execution_control", "source": "dispatch_agent / dispatch_repair_agent", "kind": "checkpoint", "persistence": "checkpoint_snapshot"},
    "original_subagent_result": {"owner": "repair_audit", "source": "dispatch_agent", "kind": "runtime", "persistence": "none"},
    "previous_subagent_results": {"owner": "repair_audit", "source": "dispatch_repair_agent", "kind": "runtime", "persistence": "none"},
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
    """贯穿 LangGraph 节点的共享状态。

    字段的 owner/source/persistence 以 `GRAPH_STATE_FIELD_AUTHORITY` 为准。
    这里保留字段类型和关键分组，不把 State Key 机械抽成常量，避免只是移动字符串。
    写入 State 的复杂 Pydantic 模型应使用 `model_dump(mode="json")`，
    读取时在边界处 `model_validate(...)` 恢复强类型。
    """

    # 请求身份与会话身份：由 RequestAdapter / Orchestrator 初始化，贯穿全链路。
    request_id: str
    trace_id: str
    tenant_id: str
    channel: str
    user_id: str
    session_id: str
    session_key: str
    thread_id: str
    auth_context: dict[str, Any] | None
    result_callback_url: str | None

    # 问题理解阶段：Query Rewrite 负责 rewritten_query/entity_bag，
    # Intent Recognition 只负责 intent/sub_intent，不再维护第二份实体状态。
    original_query: str
    rewritten_query: str
    rewrite_type: RewriteType
    query_rewrite_decision_trace: dict[str, Any]
    query_rewrite_llm_status: str | None
    query_rewrite_fallback_reason: str | None
    intent: str
    sub_intent: str | None
    intent_decision_trace: dict[str, Any]
    intent_llm_status: str | None
    intent_fallback_reason: str | None
    confidence: float
    entities: dict[str, Any]
    entity_bag: dict[str, Any]
    conversation_window: dict[str, Any]
    is_follow_up: bool
    need_clarification: bool
    clarification_question: str | None
    clarification_source: str | None
    missing_required_entities: list[str]

    # 会话上下文快照：用于 Query Rewrite / Intent / ContextBuilder，不长期进入 checkpoint。
    recent_messages: list[dict[str, Any]]
    short_summary: str | None

    # 路由与执行：Agent/Skill pinning、子 Agent 结果、任务完成度验收和 Repair 控制。
    orchestrator_context: dict[str, Any]
    agent_selection_summary: dict[str, Any]
    agent_selection_decision_trace: dict[str, Any]
    agent_selection_llm_status: str | None
    agent_selection_fallback_reason: str | None
    selected_agent: str | None
    selected_skill_id: str | None
    selected_skill_version: str | None
    subagent_result: dict[str, Any] | None
    task_completion_verification_result: dict[str, Any] | None
    verification_evidence: list[dict[str, Any]]
    task_completion_verification_context: dict[str, Any] | None
    repair_plan: dict[str, Any] | None
    repair_round: int
    repair_history: list[dict[str, Any]]
    last_repair_fingerprint: str | None
    repair_no_progress_count: int
    execution_mode: str
    original_subagent_result: dict[str, Any] | None
    previous_subagent_results: list[dict[str, Any]]
    pre_answer_verification_result: dict[str, Any] | None

    # 审批链路：pending_* 是恢复工具循环所需快照；approval_id/status 是对外摘要。
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

    # 最终外发：retry_count 是最终合规重试次数，不是任务 Repair 轮次。
    retry_count: int
    answer: str

    # 诊断字段：graph_path 保留稳定节点名字符串，便于日志和 checkpoint 排查。
    error: str | None
    graph_path: list[str]
