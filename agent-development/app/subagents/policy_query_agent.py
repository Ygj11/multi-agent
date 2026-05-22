from __future__ import annotations

"""Policy query sub agent."""

from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.subagents.base import BaseSubAgent


class PolicyQueryAgent(BaseSubAgent):
    """Queries mock policy information through private tools."""

    name = "policy_query_agent"

    async def do_run(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        sub_context: SubAgentContext,
        agent_card: AgentCard | None,
    ) -> SubAgentResult:
        policy_no = task.entities.get("policy_no")
        info = await self.call_tool(
            task=task,
            agent_card=agent_card,
            name="query_policy_info",
            arguments={"policy_no": policy_no},
        )
        status = await self.call_tool(
            task=task,
            agent_card=agent_card,
            name="query_policy_status",
            arguments={"policy_no": policy_no},
        )
        answer = f"保单查询完成：保单号 {policy_no or '未提供'}，状态 {((status.result or {}).get('status') if status.success else 'unknown')}。"
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer=answer,
            evidence=[
                {"type": "policy_info", "tool_name": "query_policy_info", "result_preview": info.result, "confidence": 0.75},
                {"type": "policy_status", "tool_name": "query_policy_status", "result_preview": status.result, "confidence": 0.75},
            ],
            tool_calls=[info.model_dump(), status.model_dump()],
            confidence=0.78,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )
