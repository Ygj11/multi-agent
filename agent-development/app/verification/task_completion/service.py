from __future__ import annotations

"""Skill-aware 任务完成度 Verifier。

这个 Verifier 是 Runtime Verify Loop 的判定者：它不执行工具、不改参数、不重新
选择 Agent/Skill，只根据完整 Skill SOP、子 Agent 执行结果和证据判断任务是否
完成；未完成时只能输出 RepairPlan，让原子 Agent 继续执行。
"""

import json
from typing import Any

from app.llm.base import LLMProvider
from app.llm.output_schemas import TaskCompletionLLMOutput, parse_llm_json_schema
from app.observability.logger import log_event, preview_text
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.schemas.enums.llm import LLMScene
from app.schemas.enums.observability import RuntimeEvent
from app.schemas.enums.task_completion import TaskCompletionStatus
from app.schemas.enums.tool import ToolStoppedReason
from app.skills.catalog import SkillCatalog
from app.verification.task_completion.repair_plan_sanitizer import RepairPlanSanitizer
from app.verification.task_completion.schemas import (
    TaskCompletionVerificationContext,
    TaskCompletionVerificationResult,
)


class TaskCompletionVerifierService:
    """根据完整 Skill SOP、执行结果和证据判断任务是否完成。

    返回值不是最终外发合规结果，而是任务完成度状态：
    PASS 进入 pre_answer_verify，CONTINUE 进入 repair，NEED_USER/HUMAN_HANDOFF/FAILED
    分别进入澄清、人工接管或降级路径。
    """

    def __init__(
        self,
        *,
        skill_catalog: SkillCatalog,
        llm_provider: LLMProvider | None = None,
        prompt_loader: PromptLoader | None = None,
        enable_llm: bool = False,
        min_confidence: float = 0.55,
        fail_closed: bool = True,
    ) -> None:
        self.skill_catalog = skill_catalog
        self.llm_provider = llm_provider
        self.prompt_loader = prompt_loader or default_prompt_loader
        self.enable_llm = enable_llm
        self.fail_closed = fail_closed
        self.sanitizer = RepairPlanSanitizer(min_confidence=min_confidence)

    async def verify(self, context: TaskCompletionVerificationContext) -> TaskCompletionVerificationResult:
        """执行一次任务完成度验收。

        第一优先使用 LLM 读取完整 Skill 和证据做语义验收；LLM 不可用时使用保守
        heuristic。无论来自 LLM 还是 heuristic，最后都必须经过 sanitizer，确保
        RepairPlan 不会更换原 selected_agent 或 selected_skill_id。
        """
        if not context.selected_skill_id:
            return self._handoff("selected_skill_id_missing", context=context)
        if self.enable_llm and self._should_call_llm():
            result = await self._verify_with_llm(context)
        else:
            result = self._heuristic_result(context, reason="task_completion_llm_disabled")
        return self.sanitizer.sanitize(
            result=result,
            expected_agent=context.selected_agent,
            expected_skill_id=context.selected_skill_id,
        )

    async def _verify_with_llm(self, context: TaskCompletionVerificationContext) -> TaskCompletionVerificationResult:
        """调用 task_completion_verifier scene，并强校验结构化输出。

        LLM 只负责“判断完成度和规划修复”，不会拿到 tools，也不能直接执行原任务。
        如果首次输出不是 TaskCompletionLLMOutput，会给同一输入追加格式修复提示再试
        一次；连续非法时 fail closed 到 HUMAN_HANDOFF，避免错误 repair 无限循环。
        """
        messages = self._messages(context)
        response = await self.llm_provider.chat(
            messages=messages,
            tools=None,
            scene=LLMScene.TASK_COMPLETION_VERIFIER,
            request_id=context.request_id,
            trace_id=context.trace_id,
            session_key=context.session_key,
        )
        parsed = parse_llm_json_schema(response.content, TaskCompletionLLMOutput)
        if not parsed.success:
            repair_messages = [
                *messages,
                {
                    "role": "user",
                    "content": (
                        "上一轮输出无法解析为 TaskCompletionLLMOutput。"
                        f"错误：{parsed.error_code}。请只返回严格 JSON。"
                    ),
                },
            ]
            repaired = await self.llm_provider.chat(
                messages=repair_messages,
                tools=None,
                scene=LLMScene.TASK_COMPLETION_VERIFIER,
                request_id=context.request_id,
                trace_id=context.trace_id,
                session_key=context.session_key,
            )
            parsed = parse_llm_json_schema(repaired.content, TaskCompletionLLMOutput)
            if not parsed.success:
                reason = parsed.error_code or "task_completion_verifier_invalid_json"
                return self._handoff(reason, context=context, llm_status=parsed.parse_status)

        data = parsed.data
        if not isinstance(data, TaskCompletionLLMOutput):
            return self._handoff("task_completion_verifier_schema_mismatch", context=context)
        try:
            return TaskCompletionVerificationResult(
                status=data.status,
                completed=data.completed,
                summary=data.summary,
                completed_items=data.completed_items,
                missing_items=data.missing_items,
                repair_plan=data.repair_plan,
                confidence=data.confidence,
                reasoning_summary=data.reasoning_summary,
                evidence_ids=data.evidence_ids,
                verifier_name="task_completion_llm",
                llm_status="success",
            )
        except Exception as exc:
            if self.fail_closed:
                return self._handoff("task_completion_verifier_result_invalid", context=context, llm_status=str(exc))
            return self._heuristic_result(context, reason="task_completion_verifier_result_invalid")

    def _messages(self, context: TaskCompletionVerificationContext) -> list[dict[str, Any]]:
        """把验收上下文渲染成 Verifier prompt。

        prompt 中包含完整 Skill body、工具调用摘要和 evidence 摘要，因此 Verifier
        能对照 SOP 判断“做没做完”；但这里不会暴露工具执行能力，避免 Verifier 变成
        第二个业务 Agent。
        """
        variables = {
            "original_query": context.original_query,
            "rewritten_query": context.rewritten_query,
            "entities": self._json(context.entities),
            "selected_agent": context.selected_agent,
            "selected_skill_id": context.selected_skill_id,
            "selected_skill_version": context.selected_skill_version or "",
            "skill_content": context.skill_content,
            "answer": context.answer,
            "tool_calls": self._json(self._summarize_tool_calls(context.tool_calls)),
            "evidence": self._json([item.model_dump() for item in context.evidence]),
            "stopped_reason": context.stopped_reason or "",
            "repair_round": context.repair_round,
            "repair_history": self._json(context.repair_history),
        }
        return [
            {"role": "system", "content": self.prompt_loader.render_scene_system(str(LLMScene.TASK_COMPLETION_VERIFIER), **variables)},
            {"role": "user", "content": self.prompt_loader.render_scene_user(str(LLMScene.TASK_COMPLETION_VERIFIER), **variables)},
        ]

    def _heuristic_result(self, context: TaskCompletionVerificationContext, *, reason: str) -> TaskCompletionVerificationResult:
        """LLM 不可用时的保守兜底验收。

        只有存在成功工具结果/证据且 Tool Loop 正常结束时才允许 PASS；没有工具证据、
        仍在审批 pending 或证据不足时走 handoff，避免把自由文本回答误判成完成。
        """
        if self._has_pending_approval(context):
            return self._handoff("approval_pending_skip_completion_expected", context=context)
        if self._has_success_evidence(context) and (context.stopped_reason in {None, "", ToolStoppedReason.FINAL}):
            return TaskCompletionVerificationResult(
                status=TaskCompletionStatus.PASS,
                completed=True,
                summary="已基于成功工具结果和证据摘要完成任务验收。",
                completed_items=["tool_evidence_available"],
                missing_items=[],
                repair_plan=None,
                confidence=0.65,
                reasoning_summary=reason,
                evidence_ids=self._evidence_ids(context),
                verifier_name="task_completion_heuristic",
                llm_status="skipped",
                fallback_reason=reason,
            )
        if context.stopped_reason == ToolStoppedReason.FINAL and not context.tool_calls:
            return self._handoff("no_tool_evidence_for_skill_task", context=context)
        return self._handoff(reason, context=context)

    @staticmethod
    def _has_success_evidence(context: TaskCompletionVerificationContext) -> bool:
        if any(item.get("success") is True for item in context.tool_calls if isinstance(item, dict)):
            return True
        return any(item.status in {"success", "available"} for item in context.evidence)

    @staticmethod
    def _has_pending_approval(context: TaskCompletionVerificationContext) -> bool:
        return context.stopped_reason == ToolStoppedReason.HUMAN_APPROVAL_REQUIRED or any(
            item.get("needs_human_approval") for item in context.tool_calls if isinstance(item, dict)
        )

    @staticmethod
    def _evidence_ids(context: TaskCompletionVerificationContext) -> list[str]:
        ids: list[str] = []
        for item in context.evidence:
            if item.evidence_id:
                ids.append(item.evidence_id)
        return ids

    @staticmethod
    def _summarize_tool_calls(tool_calls: list[dict[str, Any]]) -> list[dict[str, Any]]:
        summarized: list[dict[str, Any]] = []
        for item in tool_calls:
            if not isinstance(item, dict):
                continue
            result = item.get("result")
            summarized.append(
                {
                    "name": item.get("name") or item.get("tool_name"),
                    "success": item.get("success"),
                    "error": item.get("error"),
                    "arguments": item.get("arguments"),
                    "result_preview": preview_text(str(result)) if result is not None else None,
                    "approval_id": item.get("approval_id"),
                }
            )
        return summarized

    @staticmethod
    def _json(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False, default=str)

    def _should_call_llm(self) -> bool:
        if self.llm_provider is None:
            return False
        if self.llm_provider.__class__.__name__ == "InternalLLMProvider" and not getattr(self.llm_provider, "base_url", None):
            return False
        return True

    @staticmethod
    def _handoff(
        reason: str,
        *,
        context: TaskCompletionVerificationContext,
        llm_status: str | None = None,
    ) -> TaskCompletionVerificationResult:
        """构造安全人工接管结果。

        这是 fail-closed 出口：Verifier 输出非法、证据不足、pending approval 或超过
        自动修复边界时，都不继续让 Agent 自由发挥，而是显式转人工接管。
        """
        log_event(
            RuntimeEvent.TASK_COMPLETION_HANDOFF,
            request_id=context.request_id,
            trace_id=context.trace_id,
            session_key=context.session_key,
            node="task_completion_verifier",
            message="Task completion verification requires handoff",
            data={"reason": reason, "selected_skill_id": context.selected_skill_id},
        )
        return TaskCompletionVerificationResult(
            status=TaskCompletionStatus.HUMAN_HANDOFF,
            completed=False,
            summary="当前证据不足以安全确认任务已完成，建议人工接管。",
            completed_items=[],
            missing_items=[reason],
            repair_plan=None,
            confidence=0.0,
            reasoning_summary=reason,
            evidence_ids=TaskCompletionVerifierService._evidence_ids(context),
            verifier_name="task_completion_guard",
            llm_status=llm_status,
            fallback_reason=reason,
        )
