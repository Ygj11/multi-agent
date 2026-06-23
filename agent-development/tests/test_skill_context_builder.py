from pathlib import Path

import pytest

from app.agents.card_loader import AgentCardLoader
from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector


def _troubleshooting_card():
    card = AgentCardLoader(Path("app/agents/cards")).get_agent_card("troubleshooting_agent")
    assert card is not None
    return card


async def test_context_builder_injects_only_selected_endo_skill_content():
    """SubAgentContext 只注入选中 skill 的完整正文，不注入其他 skill 正文。"""
    catalog = SkillCatalog(Path("app/skills"))
    builder = ContextBuilder(
        skills_root=Path("app/skills"),
        skill_catalog=catalog,
        skill_selector=SkillSelector(),
    )
    parent_context = OrchestratorContext(
        original_query="保全任务完成了，但是保单信息没有更新",
        rewritten_query="保全任务完成了，但是保单信息没有更新",
        intent="troubleshooting",
        sub_intent="endo_completion_aftercare",
        session_key="s",
    )
    task = SubAgentTask(
        agent_name="troubleshooting_agent",
        agent_card_version="1.0.0",
        query="保全任务完成了，但是保单信息没有更新",
        intent="troubleshooting",
        session_key="s",
        original_query="保全任务完成了，但是保单信息没有更新",
        request_id="req-test",
        trace_id="trace-test",
    )

    context = await builder.build_for_subagent(
        task=task,
        parent_context=parent_context,
        agent_card=_troubleshooting_card(),
        allowed_tools=["query_internal_log", "rag_search_tool"],
    )

    assert context.selected_skill_id == "troubleshooting_agent.endo_completion_aftercare"
    assert "保全任务完成后异常处理 Skill" in context.skill_content
    assert "退保失败排查 Skill" not in context.skill_content
    assert task.metadata["selected_skill_id"] == "troubleshooting_agent.endo_completion_aftercare"


async def test_context_builder_clarifies_when_no_confident_skill_match_by_default():
    """默认没有置信匹配的 Skill 时，不进入通用 tool loop。"""
    catalog = SkillCatalog(Path("app/skills"))
    builder = ContextBuilder(
        skills_root=Path("app/skills"),
        skill_catalog=catalog,
        skill_selector=SkillSelector(),
    )
    parent_context = OrchestratorContext(
        original_query="帮我看看这个问题怎么处理",
        rewritten_query="帮我看看这个问题怎么处理",
        intent="troubleshooting",
        session_key="s",
    )
    task = SubAgentTask(
        agent_name="troubleshooting_agent",
        agent_card_version="1.0.0",
        query="帮我看看这个问题怎么处理",
        intent="troubleshooting",
        session_key="s",
        original_query="帮我看看这个问题怎么处理",
        request_id="req-test",
        trace_id="trace-test",
    )

    context = await builder.build_for_subagent(
        task=task,
        parent_context=parent_context,
        agent_card=_troubleshooting_card(),
        allowed_tools=["query_internal_log", "rag_search_tool"],
    )

    assert context.selected_skill_id is None
    assert context.need_clarification is True
    assert context.no_skill_blocked is True
    assert context.no_skill_policy == "clarify"
    assert "没有匹配到可执行的业务技能" in context.clarification_question
    assert task.metadata["selected_skill_id"] is None
    assert task.metadata["skill_selection_fallback"] is True
    assert context.skill_content == ""


async def test_context_builder_generic_execution_requires_local_dev_policy():
    """只有显式本地开发策略才允许无 Skill 泛化执行。"""
    catalog = SkillCatalog(Path("app/skills"))
    builder = ContextBuilder(
        skills_root=Path("app/skills"),
        skill_catalog=catalog,
        skill_selector=SkillSelector(),
        no_skill_policy="generic_dev_only",
        app_env="local",
    )
    parent_context = OrchestratorContext(
        original_query="帮我看看这个问题怎么处理",
        rewritten_query="帮我看看这个问题怎么处理",
        intent="troubleshooting",
        session_key="s",
    )
    task = SubAgentTask(
        agent_name="troubleshooting_agent",
        agent_card_version="1.0.0",
        query="帮我看看这个问题怎么处理",
        intent="troubleshooting",
        session_key="s",
        original_query="帮我看看这个问题怎么处理",
        request_id="req-test",
        trace_id="trace-test",
    )

    context = await builder.build_for_subagent(
        task=task,
        parent_context=parent_context,
        agent_card=_troubleshooting_card(),
        allowed_tools=["query_internal_log", "rag_search_tool"],
    )

    assert context.selected_skill_id is None
    assert context.need_clarification is False
    assert context.no_skill_blocked is False
    assert context.no_skill_policy == "generic_dev_only"
    assert "No specific Skill matched confidently" in context.skill_content


def test_generic_dev_only_policy_rejected_outside_local_env():
    with pytest.raises(ValueError, match="generic_dev_only"):
        ContextBuilder(
            skills_root=Path("app/skills"),
            skill_catalog=SkillCatalog(Path("app/skills")),
            skill_selector=SkillSelector(),
            no_skill_policy="generic_dev_only",
            app_env="prod",
        )


async def test_context_builder_loads_only_selected_skill_body(monkeypatch):
    catalog = SkillCatalog(Path("app/skills"))
    builder = ContextBuilder(
        skills_root=Path("app/skills"),
        skill_catalog=catalog,
        skill_selector=SkillSelector(),
    )
    loaded_skill_ids = []
    original_load = builder.skill_loader.load

    def spy_load(skill_id: str):
        loaded_skill_ids.append(skill_id)
        return original_load(skill_id)

    monkeypatch.setattr(builder.skill_loader, "load", spy_load)
    parent_context = OrchestratorContext(
        original_query="保全任务完成了，但是保单信息没有更新，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001，保全项退保",
        rewritten_query="保全任务完成了，但是保单信息没有更新，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001，保全项退保",
        intent="troubleshooting",
        session_key="s",
        entities={"apply_seq": "APPLY_POLICY_UPDATE_FAIL", "policy_no": "P001", "endorseType": "退保"},
    )
    task = SubAgentTask(
        agent_name="troubleshooting_agent",
        agent_card_version="1.0.0",
        query=parent_context.rewritten_query,
        intent="troubleshooting",
        session_key="s",
        original_query=parent_context.original_query,
        entities={"apply_seq": "APPLY_POLICY_UPDATE_FAIL", "policy_no": "P001", "endorseType": "退保"},
        request_id="req-test",
        trace_id="trace-test",
    )

    context = await builder.build_for_subagent(
        task=task,
        parent_context=parent_context,
        agent_card=_troubleshooting_card(),
        allowed_tools=["query_endo_task_record"],
    )

    assert context.selected_skill_id == "troubleshooting_agent.endo_completion_aftercare"
    assert loaded_skill_ids == ["troubleshooting_agent.endo_completion_aftercare"]
    assert "保全任务完成后异常处理 Skill" in context.skill_content
