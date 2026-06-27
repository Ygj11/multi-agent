from __future__ import annotations

"""LangGraph 节点的声明式架构契约。

本模块记录每个节点预期读取/写入的 State 字段、可选路由和失败码，
供架构审查、文档和测试使用。它不是 LangGraph 的运行时拦截器：节点
执行时不会自动按这里校验输入或输出，实际行为仍以 graph.py 与节点实现为准。
"""

from typing import Any

from pydantic import BaseModel, Field

from app.runtime.graph_state import GRAPH_STATE_FIELD_AUTHORITY
from app.runtime import failure_codes


class NodeContract(BaseModel):
    """Graph 节点的静态输入输出契约。

    该契约用于架构检查和测试快照，帮助发现节点悄悄扩大 State 的情况。
    它不参与业务执行，也不会在 LangGraph 运行时自动阻断节点。
    """

    node_name: str
    required_inputs: list[str]
    optional_inputs: list[str] = Field(default_factory=list)
    outputs: list[str]
    routes: list[str] = Field(default_factory=list)
    failure_codes: list[str] = Field(default_factory=list)
    runtime_only_outputs: list[str] = Field(default_factory=list)


def _contract(
    node_name: str,
    required_inputs: list[str],
    outputs: list[str],
    *,
    optional_inputs: list[str] | None = None,
    routes: list[str] | None = None,
    failure_codes: list[str] | None = None,
    runtime_only_outputs: list[str] | None = None,
) -> NodeContract:
    return NodeContract(
        node_name=node_name,
        required_inputs=required_inputs,
        optional_inputs=optional_inputs or [],
        outputs=outputs,
        routes=routes or [],
        failure_codes=failure_codes or [],
        runtime_only_outputs=runtime_only_outputs or [],
    )


# 架构治理清单：测试会校验它与实际注册节点、已知 State 字段和失败码保持一致。
# 修改节点职责、State 字段或分支时，应同步更新这里；不要在这里复制业务逻辑。
NODE_CONTRACTS: dict[str, NodeContract] = {
    "route_entry": _contract(
        "route_entry",
        ["session_key", "request_id"],
        ["graph_path"],
        optional_inputs=["approval_resume"],
        routes=["resume", "normal"],
    ),
    "load_session": _contract(
        "load_session",
        ["session_key"],
        ["recent_messages", "short_summary", "retry_count", "graph_path"]
    ),
    "resume_approved_tool": _contract(
        "resume_approved_tool",
        ["approval_id", "session_key", "request_id"],
        [
            "subagent_result",
            "answer",
            "approval_required",
            "approval_payloads",
            "current_approval_id",
            "root_approval_id",
            "approval_depth",
            "selected_skill_id",
            "execution_mode",
            "graph_path",
        ],
        optional_inputs=["pending_messages", "pending_tools", "pending_tool_call", "auth_context"],
    ),
    "save_user_message": _contract("save_user_message", ["session_key", "original_query"], ["graph_path"], optional_inputs=["request_id", "trace_id"]),
    "query_rewrite": _contract(
        "query_rewrite",
        ["original_query", "session_key"],
        [
            "rewritten_query",
            "rewrite_type",
            "entities",
            "entity_bag",
            "conversation_window",
            "is_follow_up",
            "need_clarification",
            "clarification_question",
            "clarification_source",
            "missing_required_entities",
            "query_rewrite_decision_trace",
            "query_rewrite_llm_status",
            "query_rewrite_fallback_reason",
            "graph_path",
        ],
        optional_inputs=["recent_messages", "short_summary"],
        routes=["clarify", "continue"],
        failure_codes=[
            failure_codes.LLM_DISABLED,
            failure_codes.LLM_PROVIDER_ERROR,
            failure_codes.LLM_JSON_PARSE_FAILED,
            failure_codes.LLM_SCHEMA_VALIDATION_FAILED,
        ],
    ),
    "intent_recognition": _contract(
        "intent_recognition",
        ["original_query", "rewritten_query", "entities", "rewrite_type", "conversation_window"],
        [
            "intent",
            "sub_intent",
            "confidence",
            "need_clarification",
            "clarification_question",
            "clarification_source",
            "intent_decision_trace",
            "intent_llm_status",
            "intent_fallback_reason",
            "graph_path",
        ],
        routes=["clarify", "continue"],
        failure_codes=[
            failure_codes.LLM_DISABLED,
            failure_codes.LLM_PROVIDER_ERROR,
            failure_codes.LLM_JSON_PARSE_FAILED,
            failure_codes.LLM_SCHEMA_VALIDATION_FAILED,
            failure_codes.INVALID_INTENT,
            failure_codes.INVALID_SUB_INTENT,
        ],
    ),
    "build_orchestrator_context": _contract(
        "build_orchestrator_context",
        ["original_query", "session_key"],
        ["orchestrator_context", "graph_path"],
        optional_inputs=["rewritten_query", "intent", "sub_intent", "entities", "conversation_window", "recent_messages", "short_summary"],
    ),
    "select_agent": _contract(
        "select_agent",
        ["intent", "original_query"],
        [
            "agent_selection_summary",
            "selected_agent",
            "need_clarification",
            "clarification_question",
            "clarification_source",
            "error",
            "agent_selection_decision_trace",
            "agent_selection_llm_status",
            "agent_selection_fallback_reason",
            "graph_path",
        ],
        optional_inputs=["sub_intent", "confidence", "entities", "rewritten_query", "is_follow_up"],
        routes=["clarify", "continue"],
        failure_codes=[
            failure_codes.AGENT_ROUTER_UNUSABLE,
            failure_codes.LLM_JSON_PARSE_FAILED,
            failure_codes.LLM_SCHEMA_VALIDATION_FAILED,
            failure_codes.LLM_PROVIDER_ERROR,
        ],
    ),
    "dispatch_agent": _contract(
        "dispatch_agent",
        ["orchestrator_context", "selected_agent", "request_id", "trace_id"],
        [
            "subagent_result",
            "answer",
            "selected_skill_id",
            "execution_mode",
            "repair_round",
            "repair_history",
            "last_repair_fingerprint",
            "repair_no_progress_count",
            "original_subagent_result",
            "previous_subagent_results",
            "need_clarification",
            "clarification_question",
            "clarification_source",
            "missing_required_entities",
            "graph_path",
        ],
        routes=["required", "not_required"],
        failure_codes=[
            failure_codes.NO_CONFIDENT_SKILL,
            failure_codes.NO_ENABLED_SKILLS,
            failure_codes.NO_SKILL_POLICY_BLOCKED,
            failure_codes.SKILL_RERANK_UNUSABLE,
            failure_codes.LLM_JSON_PARSE_FAILED,
            failure_codes.LLM_SCHEMA_VALIDATION_FAILED,
            failure_codes.LLM_PROVIDER_ERROR,
        ],
    ),
    "build_clarification_answer": _contract("build_clarification_answer", ["clarification_question"], ["answer", "need_clarification", "graph_path"]),
    "check_human_approval_required": _contract(
        "check_human_approval_required",
        [],
        ["approval_required", "approval_payloads", "graph_path"],
        optional_inputs=["subagent_result"],
        routes=["required", "not_required", "skip_completion"],
    ),
    "collect_verification_evidence": _contract(
        "collect_verification_evidence",
        ["selected_skill_id", "subagent_result"],
        ["verification_evidence", "selected_skill_version", "graph_path"],
        optional_inputs=["entities", "repair_round", "repair_history"],
    ),
    "verify_task_completion": _contract(
        "verify_task_completion",
        ["selected_skill_id", "subagent_result"],
        [
            "task_completion_verification_result",
            "verification_evidence",
            "selected_skill_version",
            "repair_history",
            "repair_plan",
            "last_repair_fingerprint",
            "repair_no_progress_count",
            "graph_path",
        ],
        optional_inputs=["repair_round", "repair_history", "last_repair_fingerprint", "repair_no_progress_count"],
        routes=["passed", "continue", "need_user", "handoff", "failed"],
    ),
    "build_repair_task": _contract(
        "build_repair_task",
        ["task_completion_verification_result", "repair_plan", "selected_skill_id"],
        ["execution_mode", "repair_round", "graph_path"],
    ),
    "dispatch_repair_agent": _contract(
        "dispatch_repair_agent",
        ["selected_agent", "selected_skill_id", "repair_plan", "repair_round", "subagent_result"],
        [
            "subagent_result",
            "answer",
            "previous_subagent_results",
            "execution_mode",
            "selected_skill_id",
            "need_clarification",
            "clarification_question",
            "clarification_source",
            "missing_required_entities",
            "graph_path",
        ],
        optional_inputs=["orchestrator_context", "entities", "verification_evidence"],
    ),
    "build_verification_clarification": _contract(
        "build_verification_clarification",
        ["task_completion_verification_result"],
        ["answer", "need_clarification", "clarification_source", "clarification_question", "graph_path"],
    ),
    "build_handoff_answer": _contract(
        "build_handoff_answer",
        ["task_completion_verification_result"],
        ["answer", "need_clarification", "manual_intervention_required", "error", "graph_path"],
    ),
    "create_approval_request": _contract(
        "create_approval_request",
        ["session_key", "request_id"],
        [
            "approval_id",
            "approval_status",
            "parent_approval_id",
            "root_approval_id",
            "approval_depth",
            "manual_intervention_required",
            "answer",
            "error",
            "approval_required",
            "graph_path",
        ],
        optional_inputs=["approval_payloads", "current_approval_id", "subagent_result"],
        routes=["submit", "manual"],
    ),
    "submit_approval_request": _contract("submit_approval_request", ["approval_id"], ["approval_status", "approval_submit_result", "graph_path"]),
    "pause_for_approval": _contract("pause_for_approval", ["approval_id"], ["answer", "approval_status", "graph_path"]),
    "pre_answer_verify": _contract(
        "pre_answer_verify",
        ["answer"],
        ["pre_answer_verification_result", "answer", "graph_path"],
        routes=["passed", "retry", "fallback"],
    ),
    "regenerate_compliant_answer": _contract("regenerate_compliant_answer", ["answer"], ["answer", "retry_count", "graph_path"]),
    "fallback_answer": _contract("fallback_answer", [], ["answer", "graph_path"]),
    "save_assistant_message": _contract("save_assistant_message", ["session_key", "answer"], ["graph_path"]),
    "compress_short_memory": _contract("compress_short_memory", ["session_key"], ["short_summary", "graph_path"], optional_inputs=["answer", "intent"]),
    "finalize_response": _contract("finalize_response", ["answer"], ["graph_path"]),
}


GRAPH_NODE_NAMES = tuple(NODE_CONTRACTS)
ALLOWED_FAILURE_CODES = {
    value
    for key, value in vars(failure_codes).items()
    if key.isupper() and isinstance(value, str) and not key.startswith("LLM_STATUS_")
}


def validate_node_contracts() -> list[str]:
    """校验契约引用是否合法，不执行节点，也不验证节点实际读写了哪些字段。"""
    errors: list[str] = []
    known_fields = set(GRAPH_STATE_FIELD_AUTHORITY)
    for node_name, contract in NODE_CONTRACTS.items():
        if contract.node_name != node_name:
            errors.append(f"contract key/name mismatch: {node_name} != {contract.node_name}")
        for field_name in [*contract.required_inputs, *contract.optional_inputs, *contract.outputs]:
            if field_name not in known_fields and field_name not in contract.runtime_only_outputs:
                errors.append(f"{node_name} references unknown graph state field: {field_name}")
        for code in contract.failure_codes:
            if code not in ALLOWED_FAILURE_CODES:
                errors.append(f"{node_name} references unknown failure code: {code}")
    return errors
