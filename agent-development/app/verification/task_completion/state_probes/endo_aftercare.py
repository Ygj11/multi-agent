from __future__ import annotations

"""保全完成后异常处理的第一阶段状态探针。"""

from typing import Any

from app.verification.task_completion.schemas import TaskCompletionVerificationContext, VerificationEvidence


class EndoCompletionAftercareProbe:
    """从已执行的只读查询结果中提取保全节点状态证据。

    第一阶段不新发业务查询，避免 verifier 侧绕过 ToolExecutor。后续如果接入
    专用只读验证接口，应在确定性 collector 中调用，而不是让 Verifier 调工具。
    """

    skill_id = "troubleshooting_agent.endo_completion_aftercare"

    async def supports(self, context: TaskCompletionVerificationContext) -> bool:
        return context.selected_skill_id == self.skill_id

    async def collect(self, context: TaskCompletionVerificationContext) -> list[VerificationEvidence]:
        for item in context.tool_calls:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("name") or item.get("tool_name") or "")
            if tool_name != "query_endo_task_record" or item.get("success") is not True:
                continue
            return [
                VerificationEvidence(
                    source_type="state_probe",
                    source_name="endo_completion_aftercare",
                    summary="已从 query_endo_task_record 成功结果中提取保全任务节点状态。",
                    status="success",
                    tool_name=tool_name,
                    tool_arguments_summary=self._safe_dict(item.get("arguments")),
                    result_summary=self._summarize_result(item.get("result")),
                    metadata={"probe": "endo_completion_aftercare"},
                )
            ]
        return [
            VerificationEvidence(
                source_type="state_probe",
                source_name="endo_completion_aftercare",
                summary="未发现成功的 query_endo_task_record 结果，暂无法证明保全任务最终状态。",
                status="unavailable",
                metadata={"probe": "endo_completion_aftercare", "reason": "query_result_missing"},
            )
        ]

    @staticmethod
    def _safe_dict(value: Any) -> dict[str, Any]:
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _summarize_result(value: Any) -> dict[str, Any]:
        if not isinstance(value, dict):
            return {"preview": str(value)[:300] if value is not None else None}
        keys = ("success", "error", "apply_seq", "task_records", "records", "data", "message")
        return {key: value.get(key) for key in keys if key in value}

