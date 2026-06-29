from __future__ import annotations

"""MainGraph 任务完成度验收与修复节点处理器。"""

from typing import Any

from app.verification.task_completion.evidence_collector import VerificationEvidenceCollector
from app.verification.task_completion.service import TaskCompletionVerifierService
from app.verification.task_completion.schemas import TaskCompletionVerificationContext, TaskCompletionVerificationResult
from app.schemas.enums.execution import ExecutionMode
from app.schemas.enums.task_completion import TaskCompletionStatus


class TaskCompletionGraphHandler:
    """封装 Completion Verify 节点内部逻辑，避免 graph.py 承载业务细节。"""

    def __init__(
        self,
        *,
        evidence_collector: VerificationEvidenceCollector,
        verifier_service: TaskCompletionVerifierService,
        max_repair_rounds: int = 2,
        refresh_evidence_before_verify: bool = False,
    ) -> None:
        self.evidence_collector = evidence_collector
        self.verifier_service = verifier_service
        self.max_repair_rounds = max_repair_rounds
        self.refresh_evidence_before_verify = refresh_evidence_before_verify

    async def collect_verification_evidence(self, state: dict[str, Any]) -> dict[str, Any]:
        context, selected_skill_version = await self.evidence_collector.collect(state)
        return {
            "task_completion_verification_context": context.model_dump(mode="json"),
            "verification_evidence": [item.model_dump() for item in context.evidence],
            "selected_skill_version": selected_skill_version,
        }

    async def verify_task_completion(self, state: dict[str, Any]) -> dict[str, Any]:
        context, selected_skill_version = await self._verification_context(state)
        result = await self.verifier_service.verify(context)
        result = self._apply_repair_guards(state, result)
        history = self._append_history(state, result)
        updates: dict[str, Any] = {
            "task_completion_verification_result": result.model_dump(),
            "task_completion_verification_context": context.model_dump(mode="json"),
            "verification_evidence": [item.model_dump() for item in context.evidence],
            "selected_skill_version": selected_skill_version,
            "repair_history": history,
            "repair_plan": result.repair_plan.model_dump() if result.repair_plan else None,
        }
        if result.repair_plan is not None:
            same = result.repair_plan.fingerprint == state.get("last_repair_fingerprint")
            updates["last_repair_fingerprint"] = result.repair_plan.fingerprint
            updates["repair_no_progress_count"] = int(state.get("repair_no_progress_count") or 0) + 1 if same else 0
        return updates

    async def _verification_context(self, state: dict[str, Any]) -> tuple[TaskCompletionVerificationContext, str | None]:
        if self.refresh_evidence_before_verify:
            return await self.evidence_collector.collect(state)
        raw_context = state.get("task_completion_verification_context")
        if isinstance(raw_context, dict):
            context = TaskCompletionVerificationContext.model_validate(raw_context)
            return context, state.get("selected_skill_version") or context.selected_skill_version
        return await self.evidence_collector.collect(state)

    def build_repair_task(self, state: dict[str, Any]) -> dict[str, Any]:
        return {
            "execution_mode": str(ExecutionMode.REPAIR),
            "repair_round": int(state.get("repair_round") or 0) + 1,
        }

    @staticmethod
    def build_verification_clarification(state: dict[str, Any]) -> dict[str, Any]:
        result = TaskCompletionVerificationResult(**state["task_completion_verification_result"])
        missing = "、".join(result.missing_items) if result.missing_items else "必要业务信息"
        answer = f"当前还不能继续完成该任务，请补充：{missing}。"
        return {
            "answer": answer,
            "need_clarification": True,
            "clarification_source": "task_completion_verification",
            "clarification_question": answer,
        }

    @staticmethod
    def build_handoff_answer(state: dict[str, Any]) -> dict[str, Any]:
        result = TaskCompletionVerificationResult(**state["task_completion_verification_result"])
        answer = f"{result.summary} 我已停止自动修复，建议人工接管处理。"
        return {
            "answer": answer,
            "need_clarification": False,
            "manual_intervention_required": True,
            "error": "task_completion_human_handoff",
        }

    def _apply_repair_guards(
        self,
        state: dict[str, Any],
        result: TaskCompletionVerificationResult,
    ) -> TaskCompletionVerificationResult:
        if result.status is not TaskCompletionStatus.CONTINUE:
            return result
        if int(state.get("repair_round") or 0) >= self.max_repair_rounds:
            return self._handoff("task_completion_max_repair_rounds_reached", result.evidence_ids)
        plan = result.repair_plan
        if plan is not None and plan.fingerprint and plan.fingerprint == state.get("last_repair_fingerprint"):
            return self._handoff("task_completion_repair_no_progress", result.evidence_ids)
        return result

    @staticmethod
    def _append_history(
        state: dict[str, Any],
        result: TaskCompletionVerificationResult,
    ) -> list[dict[str, Any]]:
        history = list(state.get("repair_history") or [])
        history.append(
            {
                "status": result.status,
                "summary": result.summary,
                "missing_items": result.missing_items,
                "repair_round": int(state.get("repair_round") or 0),
                "repair_fingerprint": result.repair_plan.fingerprint if result.repair_plan else None,
                "evidence_ids": result.evidence_ids,
            }
        )
        return history[-10:]

    @staticmethod
    def _handoff(reason: str, evidence_ids: list[str]) -> TaskCompletionVerificationResult:
        return TaskCompletionVerificationResult(
            status=TaskCompletionStatus.HUMAN_HANDOFF,
            completed=False,
            summary="任务完成度验收未能安全继续自动修复。",
            completed_items=[],
            missing_items=[reason],
            repair_plan=None,
            confidence=0.0,
            reasoning_summary=reason,
            evidence_ids=evidence_ids,
            verifier_name="task_completion_guard",
            fallback_reason=reason,
        )
