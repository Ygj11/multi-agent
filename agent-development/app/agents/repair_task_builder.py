from __future__ import annotations

"""组装修复轮次的子 Agent 任务。"""

from typing import Any
from uuid import uuid4

from app.schemas.agent_card import AgentCard
from app.schemas.enums.execution import ExecutionMode
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask


class RepairTaskBuilder:
    """把 Completion Verifier 的 RepairPlan 转成原子 Agent 可继续执行的任务。"""

    def build(
        self,
        *,
        selected_card: AgentCard,
        orchestrator_context: OrchestratorContext,
        state: dict[str, Any],
    ) -> SubAgentTask:
        plan = state.get("repair_plan") if isinstance(state.get("repair_plan"), dict) else {}
        subagent_result = state.get("subagent_result") if isinstance(state.get("subagent_result"), dict) else {}
        return SubAgentTask(
            task_id=f"repair_{uuid4().hex}",
            agent_name=selected_card.agent_name,
            agent_card_version=selected_card.version,
            query=orchestrator_context.rewritten_query,
            original_query=orchestrator_context.original_query,
            intent=orchestrator_context.intent,
            entities=state.get("entities") if isinstance(state.get("entities"), dict) else {},
            session_key=orchestrator_context.session_key,
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
            auth_context=orchestrator_context.auth_context,
            execution_mode=ExecutionMode.REPAIR,
            pinned_skill_id=state.get("selected_skill_id"),
            repair_plan=plan,
            previous_answer=str(subagent_result.get("answer") or state.get("answer") or ""),
            previous_evidence=list(state.get("verification_evidence") or []),
            previous_tool_calls=list(subagent_result.get("tool_calls") or []),
            repair_round=int(state.get("repair_round") or 0),
            do_not_repeat=list(plan.get("do_not_repeat") or []),
            metadata={
                "execution_mode": str(ExecutionMode.REPAIR),
                "pinned_skill_id": state.get("selected_skill_id"),
                "repair_round": int(state.get("repair_round") or 0),
            },
        )
