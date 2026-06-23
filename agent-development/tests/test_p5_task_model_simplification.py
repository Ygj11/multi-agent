from pathlib import Path

import pytest

from app.agents.card_loader import AgentCardLoader
from app.agents.task_assembler import AgentTaskAssembler
from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.skill import SkillSelectionContext
from app.schemas.subagent import SubAgentTask
from app.subagents.troubleshooting_agent import TroubleshootingAgent


def _loader() -> AgentCardLoader:
    return AgentCardLoader(Path("app/agents/cards"))


def _card():
    card = _loader().get_agent_card("troubleshooting_agent")
    assert card is not None
    return card


def test_task_assembler_creates_compact_canonical_subagent_task():
    card = _card()
    context = OrchestratorContext(
        original_query="原问题",
        rewritten_query="改写后的问题",
        intent="troubleshooting",
        session_key="web:u1:s1",
        auth_context={"user_id": "u1", "roles": ["operator"]},
    )

    task = AgentTaskAssembler().assemble(
        selected_card=card,
        orchestrator_context=context,
        entities={"policy_no": "9200100000458846"},
        request_id="req-1",
        trace_id="trace-1",
    )

    assert isinstance(task, SubAgentTask)
    assert task.agent_name == card.agent_name
    assert task.agent_card_version == card.version
    assert task.request_id == "req-1"
    assert task.trace_id == "trace-1"
    assert task.auth_context == context.auth_context
    assert task.metadata == {}
    assert "agent_card" not in task.model_dump()
    assert "recent_messages" not in task.model_dump()
    assert "short_summary" not in task.model_dump()


def test_subagent_reloads_trusted_card_and_rejects_version_mismatch():
    loader = _loader()
    agent = TroubleshootingAgent(
        context_builder=ContextBuilder(skills_root=Path("app/skills")),
        agent_card_loader=loader,
    )
    task = SubAgentTask(
        agent_name="troubleshooting_agent",
        agent_card_version="stale-version",
        query="保全任务没有更新",
        original_query="保全任务没有更新",
        intent="troubleshooting",
        session_key="s1",
    )

    with pytest.raises(ValueError, match="AgentCard version mismatch"):
        agent.get_agent_card(task)


def test_removed_runtime_residue_is_not_part_of_active_context_models():
    assert "available_subagents" not in OrchestratorContext.model_fields
    assert "agent_candidate_summaries" not in OrchestratorContext.model_fields
    assert "conversation_window" not in OrchestratorContext.model_fields
    assert "extracted_interface_name" not in SkillSelectionContext.model_fields
