from pathlib import Path

from app.agents.card_loader import AgentCardLoader
from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector
from app.subagents.troubleshooting_agent import TroubleshootingAgent


class FailingRunner:
    async def run(self, **kwargs):  # pragma: no cover - should never be called
        raise AssertionError("tool loop must not run when no skill is blocked")


async def test_no_skill_clarify_policy_blocks_tool_loop():
    context_builder = ContextBuilder(
        skills_root=Path("app/skills"),
        skill_catalog=SkillCatalog(Path("app/skills")),
        skill_selector=SkillSelector(),
        no_skill_policy="clarify",
    )
    card_loader = AgentCardLoader(Path("app/agents/cards"))
    agent = TroubleshootingAgent(
        context_builder=context_builder,
        agent_card_loader=card_loader,
        tool_calling_runner=FailingRunner(),
    )
    task = SubAgentTask(
        agent_name="troubleshooting_agent",
        agent_card_version="1.0.0",
        query="帮我看看这个问题",
        intent="troubleshooting",
        session_key="s-no-skill",
        original_query="帮我看看这个问题",
        request_id="req-no-skill",
    )
    parent_context = OrchestratorContext(
        original_query=task.original_query,
        rewritten_query=task.query,
        intent=task.intent,
        session_key=task.session_key,
    )

    result = await agent.run(task, parent_context)

    assert result.metadata["clarification"] is True
    assert result.metadata["clarification_source"] == "skill_selection"
    assert result.metadata["no_skill_blocked"] is True
    assert result.selected_skill_id is None
    assert "没有匹配到可执行的业务技能" in result.answer
