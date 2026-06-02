from __future__ import annotations

"""Dispatch selected tasks to registered sub agents."""

from app.schemas.agent_task import AgentTaskEnvelope
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentResult, SubAgentTask
from app.subagents.manager import SubAgentManager


class DispatchAgentNode:
    """Converts task envelopes to the current sub-agent protocol and calls them."""

    def __init__(self, subagent_manager: SubAgentManager) -> None:
        self.subagent_manager = subagent_manager

    async def dispatch(self, task_envelope: AgentTaskEnvelope, parent_context: OrchestratorContext) -> SubAgentResult:
        task = SubAgentTask(
            name=task_envelope.agent_name,
            query=task_envelope.query,
            intent=task_envelope.intent,
            session_key=task_envelope.session_key,
            original_query=task_envelope.original_query,
            entities=task_envelope.entities,
            task_id=task_envelope.task_id,
            metadata={
                **task_envelope.metadata,
                "agent_card": task_envelope.agent_card.model_dump(),
                "principal": task_envelope.principal,
                "auth_context": task_envelope.auth_context,
            },
        )
        result = await self.subagent_manager.call_subagent(task_envelope.agent_name, task, parent_context)
        result.agent_name = result.agent_name or task_envelope.agent_name
        result.name = result.name or task_envelope.agent_name
        result.task_id = result.task_id or task_envelope.task_id
        return result
