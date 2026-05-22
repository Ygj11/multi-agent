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


async def test_skill_selector_selects_signature_error_for_e102():
    """E102 请求应选择签名失败 skill。"""
    result = await _select_for_troubleshooting("REQ_001 为什么返回 E102？", error_code="E102")

    assert result.selected_skill_id == "troubleshooting_agent.signature_error"
    assert result.score > 0


async def test_skill_selector_selects_missing_field():
    """字段缺失问题应选择 missing_field skill。"""
    result = await _select_for_troubleshooting("submitProposal 报文字段缺失，提示 appId 不能为空")

    assert result.selected_skill_id == "troubleshooting_agent.missing_field"


async def test_skill_selector_selects_callback_failure():
    """回调失败问题应选择 callback_failure skill。"""
    result = await _select_for_troubleshooting("REQ_001 回调失败，渠道未收到回调，帮我排查")

    assert result.selected_skill_id == "troubleshooting_agent.callback_failure"


async def test_skill_selector_falls_back_to_default_for_unclear_query():
    """无明显匹配时回退到 default skill。"""
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

    assert result.selected_skill_id == "troubleshooting_agent.signature_error"
    assert result.fallback is True
