from __future__ import annotations

"""把标准任务分发给已注册的子 Agent。"""

from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.subagents.manager import SubAgentManager


class DispatchAgentNode:
    """按 selected_agent 调用 SubAgentManager。

    select_agent 决定“交给谁”；dispatch_agent 只负责“按任务协议调用它”。
    这里不再重新打分，也不直接执行工具。
    """

    def __init__(self, subagent_manager: SubAgentManager) -> None:
        self.subagent_manager = subagent_manager

    async def dispatch(self, task: SubAgentTask, parent_context: OrchestratorContext) -> SubAgentResult:
        result = await self.subagent_manager.call_subagent(task.agent_name, task, parent_context)
        result.agent_name = result.agent_name or task.agent_name
        result.name = result.name or task.agent_name
        result.task_id = result.task_id or task.task_id
        return result
