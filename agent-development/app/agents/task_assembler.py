from __future__ import annotations

"""Build sub-agent task envelopes from orchestrator state."""

from typing import Any
from uuid import uuid4

from app.schemas.agent_card import AgentCard
from app.schemas.agent_task import AgentTaskEnvelope
from app.schemas.runtime import OrchestratorContext


class AgentTaskAssembler:
    """Assembles the task context handed from the main agent to a sub agent."""

    def assemble(
        self,
        *,
        selected_card: AgentCard,
        orchestrator_context: OrchestratorContext,
        entities: dict[str, Any],
        request_id: str,
        trace_id: str,
    ) -> AgentTaskEnvelope:
        recent_limit = max(0, selected_card.memory_policy.recent_turns * 2)
        return AgentTaskEnvelope(
            task_id=f"task_{uuid4().hex}",
            agent_name=selected_card.agent_name,
            query=orchestrator_context.rewritten_query,
            original_query=orchestrator_context.original_query,
            intent=orchestrator_context.intent,
            entities=entities,
            session_key=orchestrator_context.session_key,
            request_id=request_id,
            trace_id=trace_id,
            agent_card=selected_card,
            short_summary=orchestrator_context.short_summary if selected_card.memory_policy.use_short_summary else None,
            recent_messages=orchestrator_context.recent_messages[-recent_limit:] if recent_limit else [],
            lightweight_knowledge_hints=orchestrator_context.lightweight_knowledge_hints,
            metadata={
                "request_id": request_id,
                "trace_id": trace_id,
            },
            auth_context=orchestrator_context.auth_context,
        )
