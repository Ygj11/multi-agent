from __future__ import annotations

"""从主上下文组装子 Agent 任务协议。"""

from typing import Any
from uuid import uuid4

from app.schemas.agent_card import AgentCard
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask


class AgentTaskAssembler:
    """把主 Agent 已确定的路由结果封装成 SubAgentTask。

    该类只做协议组装，不做复杂规划、不重新选择 Agent、不读取 Skill 内容。
    主/子 Agent 之间通过这个稳定任务对象解耦。
    """

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
