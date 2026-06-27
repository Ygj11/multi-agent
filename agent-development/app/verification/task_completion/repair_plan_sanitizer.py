from __future__ import annotations

"""RepairPlan 的确定性安全收口。"""

import hashlib
import json

from app.verification.task_completion.schemas import RepairPlan, TaskCompletionVerificationResult


class RepairPlanSanitizer:
    """校验 Verifier 产出的修复计划不越过架构边界。"""

    def __init__(self, *, min_confidence: float = 0.55) -> None:
        self.min_confidence = min_confidence

    def sanitize(
        self,
        *,
        result: TaskCompletionVerificationResult,
        expected_agent: str,
        expected_skill_id: str,
    ) -> TaskCompletionVerificationResult:
        if result.confidence < self.min_confidence:
            return self._handoff(
                reason="task_completion_verifier_low_confidence",
                evidence_ids=result.evidence_ids,
            )
        if result.status != "CONTINUE":
            return result
        plan = result.repair_plan
        if plan is None:
            return self._handoff(reason="repair_plan_missing", evidence_ids=result.evidence_ids)
        if plan.target_agent != expected_agent:
            return self._handoff(reason="repair_plan_target_agent_mismatch", evidence_ids=result.evidence_ids)
        if plan.selected_skill_id != expected_skill_id:
            return self._handoff(reason="repair_plan_selected_skill_mismatch", evidence_ids=result.evidence_ids)
        fingerprint = plan.fingerprint or self.fingerprint(plan)
        return result.model_copy(update={"repair_plan": plan.model_copy(update={"fingerprint": fingerprint})})

    @staticmethod
    def fingerprint(plan: RepairPlan) -> str:
        payload = {
            "missing_items": plan.missing_items,
            "next_steps": plan.next_steps,
            "do_not_repeat": plan.do_not_repeat,
            "expected_new_evidence": plan.expected_new_evidence,
        }
        raw = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    @staticmethod
    def _handoff(*, reason: str, evidence_ids: list[str] | None = None) -> TaskCompletionVerificationResult:
        return TaskCompletionVerificationResult(
            status="HUMAN_HANDOFF",
            completed=False,
            summary="任务完成度验收无法安全生成修复计划，建议人工接管。",
            completed_items=[],
            missing_items=[reason],
            repair_plan=None,
            confidence=0.0,
            reasoning_summary=reason,
            evidence_ids=evidence_ids or [],
            verifier_name="task_completion_guard",
            fallback_reason=reason,
        )
