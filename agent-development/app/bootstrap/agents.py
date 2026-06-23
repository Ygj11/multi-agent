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
