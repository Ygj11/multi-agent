from __future__ import annotations

"""POS real-time query sub agent."""

from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.subagents.base import BaseSubAgent


class PosQueryAgent(BaseSubAgent):
    """AgentCard-driven POS real-time query agent."""

    name = "pos_query_agent"

    async def do_run(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        sub_context: SubAgentContext,
        agent_card: AgentCard | None,
    ) -> SubAgentResult:
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer="已进入保全实时查询智能体，请补充需要查询的保全业务信息。",
            confidence=0.4,
            risk_level="low",
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )
