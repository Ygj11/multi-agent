from __future__ import annotations

"""Build canonical sub-agent tasks from orchestrator state."""

from typing import Any
from uuid import uuid4

from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask


class AgentTaskAssembler:
    """Assemble the compact protocol handed from the main agent to a sub agent."""

    def assemble(
        self,
        *,
        selected_card: AgentCard,
        orchestrator_context: OrchestratorContext,
        entities: dict[str, Any],
        request_id: str,
        trace_id: str,
    ) -> SubAgentTask:
        return SubAgentTask(
            task_id=f"task_{uuid4().hex}",
            agent_name=selected_card.agent_name,
            agent_card_version=selected_card.version,
            query=orchestrator_context.rewritten_query,
            original_query=orchestrator_context.original_query,
            intent=orchestrator_context.intent,
            entities=entities,
            session_key=orchestrator_context.session_key,
            request_id=request_id,
            trace_id=trace_id,
            auth_context=orchestrator_context.auth_context,
        )
