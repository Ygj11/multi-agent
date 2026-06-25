from __future__ import annotations

"""Subagent bootstrap helpers."""

from app.runtime.context_builder import ContextBuilder
from app.agents.card_loader import AgentCardLoader
from app.skills.catalog import SkillCatalog
from app.subagents.manager import SubAgentManager
from app.subagents.pos_query_agent import PosQueryAgent
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.subagents.troubleshooting_agent import TroubleshootingAgent
from app.tools.executor import ToolExecutor


def build_subagent_manager(
    *,
    skill_catalog: SkillCatalog,
    context_builder: ContextBuilder,
    agent_card_loader: AgentCardLoader,
    tool_executor: ToolExecutor,
    tool_calling_runner: ToolCallingRunner,
) -> SubAgentManager:
    """注册子agent入口"""
    manager = SubAgentManager(skill_catalog=skill_catalog)
    manager.register(
        "troubleshooting_agent",
        TroubleshootingAgent(
            context_builder=context_builder,
            agent_card_loader=agent_card_loader,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    manager.register(
        "pos_query_agent",
        PosQueryAgent(
            context_builder=context_builder,
            agent_card_loader=agent_card_loader,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    return manager
# todo
"""
如果未来大部分 Agent 都只是同一种通用执行模板，还可以进一步注册一个 CardDrivenSubAgent，
让 AgentCard 决定业务差异；只有确实有特殊执行流程的 Agent 才保留独立 Python 类。当前项目两个 Agent 数量不多，暂时保留显式注册是更清晰的选择。
"""
