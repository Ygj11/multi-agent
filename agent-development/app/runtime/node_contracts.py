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
from app.schemas.enums.graph import (
    AfterApprovalCreateRoute,
    ApprovalRequiredRoute,
    ClarificationRoute,
    EntryRoute,
    GraphNode,
    TaskCompletionRoute,
    VerificationRoute,
)


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
    node_name: GraphNode | str,
    required_inputs: list[str],
    outputs: list[str],
    *,
    optional_inputs: list[str] | None = None,
    routes: list[str] | None = None,
    failure_codes: list[str] | None = None,
    runtime_only_outputs: list[str] | None = None,
) -> NodeContract:
    node_value = str(node_name)
    return NodeContract(
        node_name=node_value,
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
    str(GraphNode.ROUTE_ENTRY): _contract(
        GraphNode.ROUTE_ENTRY,
        ["session_key", "request_id"],
        ["graph_path"],
        optional_inputs=["approval_resume"],
        routes=[str(EntryRoute.RESUME), str(EntryRoute.NORMAL)],
    ),
    str(GraphNode.LOAD_SESSION): _contract(
        GraphNode.LOAD_SESSION,
        ["session_key"],
        ["recent_messages", "short_summary", "retry_count", "graph_path"]
    ),
    str(GraphNode.RESUME_APPROVED_TOOL): _contract(
        GraphNode.RESUME_APPROVED_TOOL,
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
    str(GraphNode.SAVE_USER_MESSAGE): _contract(GraphNode.SAVE_USER_MESSAGE, ["session_key", "original_query"], ["graph_path"], optional_inputs=["request_id", "trace_id"]),
    str(GraphNode.QUERY_REWRITE): _contract(
        GraphNode.QUERY_REWRITE,
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
        routes=[str(ClarificationRoute.CLARIFY), str(ClarificationRoute.CONTINUE)],
        failure_codes=[
            failure_codes.LLM_DISABLED,
            failure_codes.LLM_PROVIDER_ERROR,
            failure_codes.LLM_JSON_PARSE_FAILED,
            failure_codes.LLM_SCHEMA_VALIDATION_FAILED,
        ],
    ),
    str(GraphNode.INTENT_RECOGNITION): _contract(
        GraphNode.INTENT_RECOGNITION,
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
        routes=[str(ClarificationRoute.CLARIFY), str(ClarificationRoute.CONTINUE)],
        failure_codes=[
            failure_codes.LLM_DISABLED,
            failure_codes.LLM_PROVIDER_ERROR,
            failure_codes.LLM_JSON_PARSE_FAILED,
            failure_codes.LLM_SCHEMA_VALIDATION_FAILED,
            failure_codes.INVALID_INTENT,
            failure_codes.INVALID_SUB_INTENT,
        ],
    ),
    str(GraphNode.BUILD_ORCHESTRATOR_CONTEXT): _contract(
        GraphNode.BUILD_ORCHESTRATOR_CONTEXT,
        ["original_query", "session_key"],
        ["orchestrator_context", "graph_path"],
        optional_inputs=["rewritten_query", "intent", "sub_intent", "entities", "conversation_window", "recent_messages", "short_summary"],
    ),
    str(GraphNode.SELECT_AGENT): _contract(
        GraphNode.SELECT_AGENT,
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
        routes=[str(ClarificationRoute.CLARIFY), str(ClarificationRoute.CONTINUE)],
        failure_codes=[
            failure_codes.AGENT_ROUTER_UNUSABLE,
            failure_codes.LLM_JSON_PARSE_FAILED,
            failure_codes.LLM_SCHEMA_VALIDATION_FAILED,
            failure_codes.LLM_PROVIDER_ERROR,
        ],
    ),
    str(GraphNode.DISPATCH_AGENT): _contract(
        GraphNode.DISPATCH_AGENT,
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
        routes=[str(ApprovalRequiredRoute.REQUIRED), str(ApprovalRequiredRoute.NOT_REQUIRED)],
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
    str(GraphNode.BUILD_CLARIFICATION_ANSWER): _contract(GraphNode.BUILD_CLARIFICATION_ANSWER, ["clarification_question"], ["answer", "need_clarification", "graph_path"]),
    str(GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED): _contract(
        GraphNode.CHECK_HUMAN_APPROVAL_REQUIRED,
        [],
        ["approval_required", "approval_payloads", "graph_path"],
        optional_inputs=["subagent_result"],
        routes=[str(ApprovalRequiredRoute.REQUIRED), str(ApprovalRequiredRoute.NOT_REQUIRED), str(ApprovalRequiredRoute.SKIP_COMPLETION)],
    ),
    str(GraphNode.COLLECT_VERIFICATION_EVIDENCE): _contract(
        GraphNode.COLLECT_VERIFICATION_EVIDENCE,
        ["selected_skill_id", "subagent_result"],
        ["task_completion_verification_context", "verification_evidence", "selected_skill_version", "graph_path"],
        optional_inputs=["entities", "repair_round", "repair_history"],
    ),
    str(GraphNode.VERIFY_TASK_COMPLETION): _contract(
        GraphNode.VERIFY_TASK_COMPLETION,
        ["selected_skill_id", "subagent_result"],
        [
            "task_completion_verification_result",
            "task_completion_verification_context",
            "verification_evidence",
            "selected_skill_version",
            "repair_history",
            "repair_plan",
            "last_repair_fingerprint",
            "repair_no_progress_count",
            "graph_path",
        ],
        optional_inputs=["repair_round", "repair_history", "last_repair_fingerprint", "repair_no_progress_count"],
        routes=[
            str(TaskCompletionRoute.PASSED),
            str(TaskCompletionRoute.CONTINUE),
            str(TaskCompletionRoute.NEED_USER),
            str(TaskCompletionRoute.HANDOFF),
            str(TaskCompletionRoute.FAILED),
        ],
    ),
    str(GraphNode.BUILD_REPAIR_TASK): _contract(
        GraphNode.BUILD_REPAIR_TASK,
        ["task_completion_verification_result", "repair_plan", "selected_skill_id"],
        ["execution_mode", "repair_round", "graph_path"],
    ),
    str(GraphNode.DISPATCH_REPAIR_AGENT): _contract(
        GraphNode.DISPATCH_REPAIR_AGENT,
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
    str(GraphNode.BUILD_VERIFICATION_CLARIFICATION): _contract(
        GraphNode.BUILD_VERIFICATION_CLARIFICATION,
        ["task_completion_verification_result"],
        ["answer", "need_clarification", "clarification_source", "clarification_question", "graph_path"],
    ),
    str(GraphNode.BUILD_HANDOFF_ANSWER): _contract(
        GraphNode.BUILD_HANDOFF_ANSWER,
        ["task_completion_verification_result"],
        ["answer", "need_clarification", "manual_intervention_required", "error", "graph_path"],
    ),
    str(GraphNode.CREATE_APPROVAL_REQUEST): _contract(
        GraphNode.CREATE_APPROVAL_REQUEST,
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
        routes=[str(AfterApprovalCreateRoute.SUBMIT), str(AfterApprovalCreateRoute.MANUAL)],
    ),
    str(GraphNode.SUBMIT_APPROVAL_REQUEST): _contract(GraphNode.SUBMIT_APPROVAL_REQUEST, ["approval_id"], ["approval_status", "approval_submit_result", "graph_path"]),
    str(GraphNode.PAUSE_FOR_APPROVAL): _contract(GraphNode.PAUSE_FOR_APPROVAL, ["approval_id"], ["answer", "approval_status", "graph_path"]),
    str(GraphNode.PRE_ANSWER_VERIFY): _contract(
        GraphNode.PRE_ANSWER_VERIFY,
        ["answer"],
        ["pre_answer_verification_result", "answer", "graph_path"],
        routes=[str(VerificationRoute.PASSED), str(VerificationRoute.RETRY), str(VerificationRoute.FALLBACK)],
    ),
    str(GraphNode.REGENERATE_COMPLIANT_ANSWER): _contract(GraphNode.REGENERATE_COMPLIANT_ANSWER, ["answer"], ["answer", "retry_count", "graph_path"]),
    str(GraphNode.FALLBACK_ANSWER): _contract(GraphNode.FALLBACK_ANSWER, [], ["answer", "graph_path"]),
    str(GraphNode.SAVE_ASSISTANT_MESSAGE): _contract(GraphNode.SAVE_ASSISTANT_MESSAGE, ["session_key", "answer"], ["graph_path"]),
    str(GraphNode.COMPRESS_SHORT_MEMORY): _contract(GraphNode.COMPRESS_SHORT_MEMORY, ["session_key"], ["short_summary", "graph_path"], optional_inputs=["answer", "intent"]),
    str(GraphNode.FINALIZE_RESPONSE): _contract(GraphNode.FINALIZE_RESPONSE, ["answer"], ["graph_path"]),
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
