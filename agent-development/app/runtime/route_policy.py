from __future__ import annotations

"""Centralized route policy for LangGraph conditional edges."""

from typing import Any, Literal

from app.verification.schemas import VerificationResult


class RoutePolicy:
    """Pure routing decisions for graph conditional edges."""

    @staticmethod
    def route_entry(state: dict[str, Any]) -> Literal["resume", "normal"]:
        return "resume" if state.get("approval_resume") else "normal"

    @staticmethod
    def route_clarification(state: dict[str, Any]) -> Literal["clarify", "continue"]:
        return "clarify" if state.get("need_clarification") else "continue"

    @staticmethod
    def route_approval_required(state: dict[str, Any]) -> Literal["required", "not_required"]:
        return "required" if state.get("approval_required") else "not_required"

    @staticmethod
    def route_task_completion(state: dict[str, Any]) -> Literal["passed", "continue", "need_user", "handoff", "failed"]:
        result = state.get("task_completion_verification_result") or {}
        status = str(result.get("status") or "").upper()
        if status == "PASS":
            return "passed"
        if status == "CONTINUE":
            return "continue"
        if status == "NEED_USER":
            return "need_user"
        if status == "HUMAN_HANDOFF":
            return "handoff"
        return "failed"

    @staticmethod
    def route_after_create_approval(state: dict[str, Any]) -> Literal["submit", "manual"]:
        return "manual" if state.get("manual_intervention_required") else "submit"

    @staticmethod
    def route_verification(state: dict[str, Any]) -> Literal["passed", "retry", "fallback"]:
        result = VerificationResult(**state["pre_answer_verification_result"])
        if result.action in {"allow", "patch"} and result.passed:
            return "passed"
        if result.action == "retry" and state.get("retry_count", 0) < 1:
            return "retry"
        return "fallback"
