from __future__ import annotations

"""Dispatch canonical tasks to registered sub agents."""

from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.subagents.manager import SubAgentManager


class DispatchAgentNode:
    """Calls the selected sub agent using the canonical task protocol."""

    def __init__(self, subagent_manager: SubAgentManager) -> None:
        self.subagent_manager = subagent_manager

    async def dispatch(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        result = await self.subagent_manager.call_subagent(task.agent_name, task, parent_context)
        result.agent_name = result.agent_name or task.agent_name
        result.name = result.name or task.agent_name
        result.task_id = result.task_id or task.task_id
        return result
