from __future__ import annotations

from app.runtime.route_policy import RoutePolicy
from app.schemas.enums.approval import ApprovalCallbackStatus, ApprovalEventType, ApprovalStatus
from app.schemas.enums.execution import ExecutionMode
from app.schemas.enums.graph import (
    AfterApprovalCreateRoute,
    ApprovalRequiredRoute,
    ClarificationRoute,
    EntryRoute,
    GraphNode,
    TaskCompletionRoute,
    VerificationRoute,
)
from app.schemas.enums.llm import LLMScene, LLMStructuredErrorCode, LLMStructuredParseStatus
from app.schemas.enums.observability import RuntimeEvent
from app.schemas.enums.query import RewriteType
from app.schemas.enums.task_completion import TaskCompletionStatus
from app.schemas.enums.tool import (
    DataClassification,
    RiskLevel,
    ToolErrorCode,
    ToolOperation,
    ToolScope,
    ToolSource,
    ToolStoppedReason,
    UnknownMCPToolPolicy,
)
from app.schemas.enums.verification import VerificationAction, VerificationSeverity, VerificationStage


def test_graph_node_machine_values_match_existing_graph_protocol():
    assert GraphNode.ROUTE_ENTRY.value == "route_entry"
    assert GraphNode.LOAD_SESSION.value == "load_session"
    assert GraphNode.QUERY_REWRITE.value == "query_rewrite"
    assert GraphNode.VERIFY_TASK_COMPLETION.value == "verify_task_completion"
    assert GraphNode.FINALIZE_RESPONSE.value == "finalize_response"


def test_route_machine_values_match_existing_graph_protocol():
    assert EntryRoute.RESUME.value == "resume"
    assert EntryRoute.NORMAL.value == "normal"
    assert ClarificationRoute.CLARIFY.value == "clarify"
    assert ClarificationRoute.CONTINUE.value == "continue"
    assert ApprovalRequiredRoute.REQUIRED.value == "required"
    assert ApprovalRequiredRoute.NOT_REQUIRED.value == "not_required"
    assert ApprovalRequiredRoute.SKIP_COMPLETION.value == "skip_completion"
    assert TaskCompletionRoute.PASSED.value == "passed"
    assert TaskCompletionRoute.CONTINUE.value == "continue"
    assert TaskCompletionRoute.NEED_USER.value == "need_user"
    assert TaskCompletionRoute.HANDOFF.value == "handoff"
    assert TaskCompletionRoute.FAILED.value == "failed"
    assert AfterApprovalCreateRoute.SUBMIT.value == "submit"
    assert AfterApprovalCreateRoute.MANUAL.value == "manual"
    assert VerificationRoute.PASSED.value == "passed"
    assert VerificationRoute.RETRY.value == "retry"
    assert VerificationRoute.FALLBACK.value == "fallback"


def test_route_policy_enum_values_remain_string_compatible():
    assert RoutePolicy.route_entry({"approval_resume": True}) == "resume"
    assert RoutePolicy.route_clarification({"need_clarification": True}) == "clarify"
    assert RoutePolicy.route_approval_required({"approval_required": False}) == "not_required"
    assert RoutePolicy.route_after_create_approval({"manual_intervention_required": True}) == "manual"


def test_runtime_state_machine_values_match_existing_protocols():
    assert TaskCompletionStatus.PASS.value == "PASS"
    assert TaskCompletionStatus.CONTINUE.value == "CONTINUE"
    assert TaskCompletionStatus.NEED_USER.value == "NEED_USER"
    assert TaskCompletionStatus.HUMAN_HANDOFF.value == "HUMAN_HANDOFF"
    assert TaskCompletionStatus.FAILED.value == "FAILED"

    assert ExecutionMode.INITIAL.value == "initial"
    assert ExecutionMode.REPAIR.value == "repair"

    assert ToolStoppedReason.FINAL.value == "final"
    assert ToolStoppedReason.HUMAN_APPROVAL_REQUIRED.value == "human_approval_required"
    assert ToolStoppedReason.MAX_DUPLICATE_TOOL_CALLS.value == "max_duplicate_tool_calls"


def test_approval_and_verification_machine_values_match_existing_protocols():
    assert ApprovalStatus.CREATED.value == "created"
    assert ApprovalStatus.PENDING.value == "pending"
    assert ApprovalStatus.APPROVED.value == "approved"
    assert ApprovalStatus.MANUAL_INTERVENTION_REQUIRED.value == "manual_intervention_required"
    assert ApprovalCallbackStatus.REJECTED.value == "rejected"
    assert ApprovalEventType.RESULT_CALLBACK_FAILED.value == "result_callback_failed"

    assert VerificationStage.PRE_TOOL.value == "pre_tool"
    assert VerificationStage.PRE_ANSWER.value == "pre_answer"
    assert VerificationAction.ALLOW.value == "allow"
    assert VerificationAction.PATCH.value == "patch"
    assert VerificationAction.RETRY.value == "retry"
    assert VerificationSeverity.BLOCKING.value == "blocking"


def test_tool_machine_values_match_existing_protocols():
    assert ToolScope.PUBLIC.value == "public"
    assert ToolScope.PRIVATE.value == "private"
    assert ToolScope.MCP.value == "mcp"
    assert ToolSource.LOCAL.value == "local"
    assert ToolSource.MCP.value == "mcp"
    assert ToolOperation.READ.value == "read"
    assert ToolOperation.DDL.value == "ddl"
    assert RiskLevel.HIGH.value == "high"
    assert DataClassification.SENSITIVE.value == "sensitive"
    assert UnknownMCPToolPolicy.APPROVAL.value == "approval"
    assert ToolErrorCode.HUMAN_APPROVAL_REQUIRED.value == "human_approval_required"


def test_llm_machine_values_match_existing_protocols():
    assert LLMScene.QUERY_REWRITE.value == "query_rewrite"
    assert LLMScene.INTENT_RECOGNITION.value == "intent_recognition"
    assert LLMScene.AGENT_SELECTION.value == "agent_selection"
    assert LLMScene.SKILL_SELECTION.value == "skill_selection"
    assert LLMScene.SUBAGENT_REASONING.value == "subagent_reasoning"
    assert LLMScene.TASK_COMPLETION_VERIFIER.value == "task_completion_verifier"
    assert LLMScene.FINAL_COMPLIANCE.value == "final_compliance"
    assert LLMStructuredParseStatus.SCHEMA_VALIDATION_FAILED.value == "schema_validation_failed"
    assert LLMStructuredErrorCode.JSON_PARSE_FAILED.value == "llm_json_parse_failed"


def test_query_rewrite_type_values_match_existing_protocols():
    assert RewriteType.DIRECT.value == "direct"
    assert RewriteType.CONTEXTUAL_FOLLOW_UP.value == "contextual_follow_up"
    assert RewriteType.CLARIFICATION_REPLY.value == "clarification_reply"
    assert RewriteType.NEW_REQUEST.value == "new_request"
    assert RewriteType.CLARIFICATION_REQUIRED.value == "clarification_required"


def test_observability_event_values_match_existing_protocols():
    assert RuntimeEvent.REQUEST_RECEIVED.value == "request_received"
    assert RuntimeEvent.LANGGRAPH_NODE_ENTER.value == "langgraph_node_enter"
    assert RuntimeEvent.TOOL_EXECUTION_FINISHED.value == "tool_execution_finished"
