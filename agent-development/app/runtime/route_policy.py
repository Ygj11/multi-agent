from __future__ import annotations

"""Centralized route policy for LangGraph conditional edges."""

from typing import Any

from pydantic import ValidationError

from app.observability.logger import log_event
from app.schemas.enums.graph import (
    AfterApprovalCreateRoute,
    ApprovalRequiredRoute,
    ClarificationRoute,
    EntryRoute,
    TaskCompletionRoute,
    VerificationRoute,
)
from app.schemas.enums.observability import RuntimeEvent
from app.schemas.enums.task_completion import TaskCompletionStatus
from app.schemas.enums.verification import VerificationAction
from app.verification.task_completion.schemas import TaskCompletionVerificationResult
from app.verification.schemas import VerificationResult


class RoutePolicy:
    """Pure routing decisions for graph conditional edges."""

    @staticmethod
    def route_entry(state: dict[str, Any]) -> EntryRoute:
        return EntryRoute.RESUME if state.get("approval_resume") else EntryRoute.NORMAL

    @staticmethod
    def route_clarification(state: dict[str, Any]) -> ClarificationRoute:
        return ClarificationRoute.CLARIFY if state.get("need_clarification") else ClarificationRoute.CONTINUE

    @staticmethod
    def route_approval_required(state: dict[str, Any]) -> ApprovalRequiredRoute:
        return ApprovalRequiredRoute.REQUIRED if state.get("approval_required") else ApprovalRequiredRoute.NOT_REQUIRED

    @staticmethod
    def route_task_completion(state: dict[str, Any]) -> TaskCompletionRoute:
        raw_result = state.get("task_completion_verification_result")
        if not raw_result:
            return TaskCompletionRoute.FAILED
        try:
            result = TaskCompletionVerificationResult.model_validate(raw_result)
        except ValidationError as exc:
            log_event(
                RuntimeEvent.INVALID_TASK_COMPLETION_RESULT,
                level="WARNING",
                request_id=state.get("request_id"),
                trace_id=state.get("trace_id"),
                session_key=state.get("session_key"),
                node="verify_task_completion",
                message="Task completion result is invalid; route to failed.",
                data={"errors": exc.errors()},
            )
            return TaskCompletionRoute.FAILED

        route_mapping = {
            TaskCompletionStatus.PASS: TaskCompletionRoute.PASSED,
            TaskCompletionStatus.CONTINUE: TaskCompletionRoute.CONTINUE,
            TaskCompletionStatus.NEED_USER: TaskCompletionRoute.NEED_USER,
            TaskCompletionStatus.HUMAN_HANDOFF: TaskCompletionRoute.HANDOFF,
            TaskCompletionStatus.FAILED: TaskCompletionRoute.FAILED,
        }
        return route_mapping[result.status]

    @staticmethod
    def route_after_create_approval(state: dict[str, Any]) -> AfterApprovalCreateRoute:
        return AfterApprovalCreateRoute.MANUAL if state.get("manual_intervention_required") else AfterApprovalCreateRoute.SUBMIT

    @staticmethod
    def route_verification(state: dict[str, Any]) -> VerificationRoute:
        try:
            result = VerificationResult.model_validate(state["pre_answer_verification_result"])
        except (KeyError, ValidationError) as exc:
            log_event(
                RuntimeEvent.INVALID_PRE_ANSWER_VERIFICATION_RESULT,
                level="WARNING",
                request_id=state.get("request_id"),
                trace_id=state.get("trace_id"),
                session_key=state.get("session_key"),
                node="pre_answer_verify",
                message="Pre-answer verification result is invalid; route to fallback.",
                data={"error": str(exc)},
            )
            return VerificationRoute.FALLBACK
        if result.action in {VerificationAction.ALLOW, VerificationAction.PATCH} and result.passed:
            return VerificationRoute.PASSED
        if result.action is VerificationAction.RETRY and state.get("retry_count", 0) < 1:
            return VerificationRoute.RETRY
        return VerificationRoute.FALLBACK
