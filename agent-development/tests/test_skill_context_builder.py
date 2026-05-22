from pathlib import Path

from app.runtime.context_builder import ContextBuilder
from app.schemas.runtime import OrchestratorContext
from app.schemas.subagent import SubAgentTask
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector


async def test_context_builder_injects_only_selected_skill_content():
    """SubAgentContext 只注入选中 skill 的完整正文，不注入其他 skill 正文。"""
    catalog = SkillCatalog(Path("app/skills"))
    builder = ContextBuilder(
        skills_root=Path("app/skills"),
        skill_catalog=catalog,
        skill_selector=SkillSelector(),
    )
    parent_context = OrchestratorContext(
        original_query="REQ_001 为什么返回 E102？",
        rewritten_query="REQ_001 为什么返回 E102？",
        intent="troubleshooting",
        session_key="s",
    )
    task = SubAgentTask(
        name="troubleshooting_agent",
        query="REQ_001 为什么返回 E102？",
        intent="troubleshooting",
        session_key="s",
        original_query="REQ_001 为什么返回 E102？",
        metadata={"request_id": "req-test", "trace_id": "trace-test"},
    )

    context = await builder.build_for_subagent(
        task=task,
        parent_context=parent_context,
        allowed_tools=["query_internal_log", "get_knowledge"],
    )

    assert context.selected_skill_id == "troubleshooting_agent.signature_error"
    assert "签名失败排查 Skill" in context.skill_content
    assert "字段缺失排查 Skill" not in context.skill_content
    assert "回调失败排查 Skill" not in context.skill_content
    assert task.metadata["selected_skill_id"] == "troubleshooting_agent.signature_error"
