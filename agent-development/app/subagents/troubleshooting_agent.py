from __future__ import annotations

"""Troubleshooting sub agent."""

from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext, SubAgentContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.subagents.base import BaseSubAgent


class TroubleshootingAgent(BaseSubAgent):
    """Diagnoses policy, refund, callback, and integration failures."""

    name = "troubleshooting_agent"

    async def do_run(
        self,
        *,
        task: SubAgentTask,
        parent_context: OrchestratorContext,
        sub_context: SubAgentContext,
        agent_card: AgentCard | None,
    ) -> SubAgentResult:
        """Fallback path for tests that instantiate the agent without ToolCallingRunner."""
        answer = "当前排查 Agent 未配置工具调用运行器，无法基于证据完成诊断。请配置对应 Skill 和工具运行器后重试。"
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer=answer,
            diagnosis=None,
            evidence=[],
            tool_calls=[],
            recommendation=None,
            responsibility=None,
            confidence=0.2,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )
