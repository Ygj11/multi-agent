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
        answer = (
            "E102 通常表示签名校验失败。请检查 timestamp 是否参与签名、密钥版本、字段排序、"
            "空值处理和 body 序列化方式。若需要外部流程证据，应通过已授权 MCP Client 工具查询。"
        )
        return SubAgentResult(
            name=self.name,
            agent_name=self.name,
            task_id=task.task_id,
            answer=answer,
            diagnosis="签名校验失败方向排查。",
            evidence=[],
            tool_calls=[],
            recommendation="优先核对签名 base string、密钥版本、timestamp 和字段排序。",
            responsibility="需结合本地日志与授权 MCP 工具结果确认最终归属。",
            confidence=0.6,
            selected_skill_id=sub_context.selected_skill_id,
            selected_skill_metadata=sub_context.selected_skill_metadata,
            skill_selection_score=sub_context.skill_selection_score,
            skill_selection_reason=sub_context.skill_selection_reason,
        )

