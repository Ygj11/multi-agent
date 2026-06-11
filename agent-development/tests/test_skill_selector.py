from pathlib import Path

from app.schemas.skill import SkillSelectionContext
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector


async def _select_for_troubleshooting(query: str, error_code: str | None = None):
    catalog = SkillCatalog(Path("app/skills"))
    selector = SkillSelector()
    context = SkillSelectionContext(
        agent_name="troubleshooting_agent",
        intent="troubleshooting",
        original_query=query,
        rewritten_query=query,
        session_key="s",
        extracted_error_code=error_code,
        extracted_request_id="REQ_001" if "REQ_001" in query else None,
        extracted_interface_name="submitProposal" if "submitProposal" in query else None,
    )
    return await selector.select(
        agent_name="troubleshooting_agent",
        context=context,
        candidates=catalog.list_skills("troubleshooting_agent"),
    )


async def test_skill_selector_does_not_select_removed_signature_skill():
    """已删除签名失败 skill 后，E102 请求不应选择 skill。"""
    result = await _select_for_troubleshooting("REQ_001 为什么返回 E102？", error_code="E102")

    assert result.selected_skill_id is None
    assert result.fallback is True


async def test_skill_selector_returns_no_skill_for_unclear_query():
    """无明显匹配时不选择 skill。"""
    catalog = SkillCatalog(Path("app/skills"))
    selector = SkillSelector()
    context = SkillSelectionContext(
        agent_name="troubleshooting_agent",
        intent="troubleshooting",
        original_query="帮我看一下这个问题",
        rewritten_query="帮我看一下这个问题",
        session_key="s",
    )

    result = await selector.select(
        agent_name="troubleshooting_agent",
        context=context,
        candidates=catalog.list_skills("troubleshooting_agent"),
    )

    assert result.selected_skill_id is None
    assert result.selected_skill_metadata is None
    assert result.fallback is True
