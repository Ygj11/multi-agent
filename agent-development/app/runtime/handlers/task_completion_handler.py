from __future__ import annotations

"""MainGraph 任务完成度验收与修复节点处理器。

Completion Verify 关注“子 Agent 是否真的按选中的 Skill SOP 完成了用户任务”，
它和 pre_answer verification 不同：后者只关心最终答案能不能安全外发。
"""

from typing import Any

from app.verification.task_completion.evidence_collector import VerificationEvidenceCollector
from app.verification.task_completion.service import TaskCompletionVerifierService
from app.verification.task_completion.schemas import TaskCompletionVerificationContext, TaskCompletionVerificationResult
from app.schemas.enums.execution import ExecutionMode
from app.schemas.enums.task_completion import TaskCompletionStatus


class TaskCompletionGraphHandler:
    """封装 Runtime Verify Loop 的节点内部逻辑。

    Graph 只负责节点编排；这里负责把 state 转成验收上下文、调用 Verifier、
    记录 repair 历史，并把 Verifier 的结果投影回 Graph State。
    """

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
        """生成本轮验收的 canonical context/evidence。

        这个节点先于 verify_task_completion 执行，目的是把“验收需要看的东西”
        固化到 state 中：完整 Skill 文本不长期放入 checkpoint，但会在这里被加载
        并进入本次 Verifier prompt；工具大结果则通过 evidence/tool_log_id 摘要引用。
        """
        context, selected_skill_version = await self.evidence_collector.collect(state)
        return {
            "task_completion_verification_context": context.model_dump(mode="json"),
            "verification_evidence": [item.model_dump() for item in context.evidence],
            "selected_skill_version": selected_skill_version,
        }

    async def verify_task_completion(self, state: dict[str, Any]) -> dict[str, Any]:
        """执行任务完成度验收，并产出后续路由所需的结构化结果。

        Verifier 返回 PASS 时只代表“任务完成度通过”，还要继续走 pre_answer_verify；
        返回 CONTINUE 时必须带 RepairPlan，后续 build_repair_task 会让原子 Agent
        固定原 selected_skill_id 继续执行；NEED_USER/HUMAN_HANDOFF/FAILED 则进入
        对应的澄清、人工接管或降级答案路径。
        """
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
        """读取 collect 节点生成的验收上下文，必要时才重新收集。

        默认复用 state 中的 context/evidence，避免 collect_verification_evidence 和
        verify_task_completion 各自重新探测造成上下文漂移。只有显式开启
        refresh_evidence_before_verify 时，才在验收前刷新状态探针证据。
        """
        if self.refresh_evidence_before_verify:
            return await self.evidence_collector.collect(state)
        raw_context = state.get("task_completion_verification_context")
        if isinstance(raw_context, dict):
            context = TaskCompletionVerificationContext.model_validate(raw_context)
            return context, state.get("selected_skill_version") or context.selected_skill_version
        return await self.evidence_collector.collect(state)

    def build_repair_task(self, state: dict[str, Any]) -> dict[str, Any]:
        """标记下一轮进入 repair 模式。

        真正的 SubAgentTask 在 RepairTaskBuilder 中构造；这里仅更新 Graph State 中
        的 execution_mode/repair_round，让后续 dispatch_repair_agent 能知道这是续跑。
        """
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
        """对 Verifier 输出的 CONTINUE 做运行时保护。

        Verifier 只能提出 RepairPlan，不能无限要求系统修复。这里集中处理最大修复
        轮次和“连续相同计划”两类无进展保护，避免 Runtime Verify Loop 变成无限环。
        """
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
