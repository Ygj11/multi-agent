from __future__ import annotations

"""Subagent bootstrap helpers."""

from app.runtime.context_builder import ContextBuilder
from app.skills.catalog import SkillCatalog
from app.subagents.claim_agent import ClaimAgent
from app.subagents.change_impact_analysis_agent import ChangeImpactAnalysisAgent
from app.subagents.compliance_security_agent import ComplianceSecurityAgent
from app.subagents.document_parse_agent import DocumentParseAgent
from app.subagents.manager import SubAgentManager
from app.subagents.policy_query_agent import PolicyQueryAgent
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.subagents.troubleshooting_agent import TroubleshootingAgent
from app.tools.executor import ToolExecutor


def build_subagent_manager(
    *,
    skill_catalog: SkillCatalog,
    context_builder: ContextBuilder,
    tool_executor: ToolExecutor,
    tool_calling_runner: ToolCallingRunner,
) -> SubAgentManager:
    manager = SubAgentManager(skill_catalog=skill_catalog)
    manager.register(
        "troubleshooting_agent",
        TroubleshootingAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    manager.register(
        "compliance_agent",
        ComplianceSecurityAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    manager.register(
        "document_parse_agent",
        DocumentParseAgent(context_builder=context_builder, tool_executor=tool_executor),
    )
    manager.register(
        "change_impact_analysis_agent",
        ChangeImpactAnalysisAgent(context_builder=context_builder, tool_executor=tool_executor),
    )
    manager.register(
        "policy_query_agent",
        PolicyQueryAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    manager.register(
        "claim_agent",
        ClaimAgent(
            context_builder=context_builder,
            tool_executor=tool_executor,
            tool_calling_runner=tool_calling_runner,
        ),
    )
    return manager
