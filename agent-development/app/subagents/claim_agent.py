from __future__ import annotations

"""Claim query sub agent."""

from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.subagents.base import BaseSubAgent


class ClaimAgent(BaseSubAgent):
    """Queries mock claim case and progress."""

    name = "claim_agent"

    async def do_run(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        sub_context: SubAgentContext,
        agent_card: AgentCard | None,
    ) -> SubAgentResult:
        claim_no = task.entities.get("claim_no")
        case = await self.call_tool(
            task=task,
            agent_card=agent_card,
            name="query_claim_case",
            arguments={"claim_no": claim_no},
        )
        progress = await self.call_tool(
            task=task,
            agent_card=agent_card,
            name="query_claim_progress",
            arguments={"claim_no": claim_no},
        )
        answer = f"理赔查询完成：赔案号 {claim_no or '未提供'}，当前状态 {((case.result or {}).get('status') if case.success else 'unknown')}。"
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer=answer,
            evidence=[
                {"type": "claim_case", "tool_name": "query_claim_case", "result_preview": case.result, "confidence": 0.75},
                {"type": "claim_progress", "tool_name": "query_claim_progress", "result_preview": progress.result, "confidence": 0.75},
            ],
            tool_calls=[case.model_dump(), progress.model_dump()],
            confidence=0.78,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )
