from __future__ import annotations

"""组装修复轮次的子 Agent 任务。

Repair 不是“重新规划一个新任务”，而是让第一次执行的原子 Agent 按原 Skill 继续
完成缺失步骤。因此这里不会重新做 Intent/Agent/Skill 选择，只把 Verifier 给出的
RepairPlan、安全摘要和上一轮结果注入到新的 SubAgentTask。
"""

from typing import Any
from uuid import uuid4

from app.schemas.agent_card import AgentCard
from app.schemas.enums.execution import ExecutionMode
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask


class RepairTaskBuilder:
    """把 Completion Verifier 的 RepairPlan 转成原子 Agent 可继续执行的任务。

    该 builder 只负责组装协议，不执行工具、不判断权限、不修改 RepairPlan。
    后续 dispatch_repair_agent 仍会走 BaseSubAgent、ToolCallingRunner 和
    ToolExecutor，因此权限、审批、幂等和工具参数校验都不会被绕过。
    """

    def build(
        self,
        *,
        selected_card: AgentCard,
        orchestrator_context: OrchestratorContext,
        state: dict[str, Any],
    ) -> SubAgentTask:
        """构造 repair 模式的 SubAgentTask。

        关键约束：
        - agent_name 固定为原 selected_agent；
        - pinned_skill_id 固定为第一次选中的 selected_skill_id；
        - previous_evidence / previous_tool_calls 告诉原子 Agent 哪些证据已经有了；
        - do_not_repeat 防止重复执行已经成功的步骤；
        - repair_round 供 Runtime Verify Loop 做最大修复次数和无进展保护。
        """
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
