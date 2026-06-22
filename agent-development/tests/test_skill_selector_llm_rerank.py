import json
from pathlib import Path

from app.llm.schemas import LLMResponse
from app.schemas.skill import SkillSelectionContext
from app.skills.catalog import SkillCatalog
from app.skills.selector import SkillSelector


class CapturingSkillLLM:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": messages, "tools": tools, "kwargs": kwargs})
        return LLMResponse(content=self.content)


def _context() -> SkillSelectionContext:
    query = "保全任务完成了，但是保单信息没有更新，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001，保全项退保"
    return SkillSelectionContext(
        agent_name="troubleshooting_agent",
        intent="troubleshooting",
        original_query=query,
        rewritten_query=query,
        session_key="s",
        entities={"apply_seq": "APPLY_POLICY_UPDATE_FAIL", "policy_no": "P001", "endorseType": "退保"},
        business_domain=["health_insurance_endorsement"],
    )


async def test_skill_selector_llm_rerank_selects_endo_completion_metadata_only():
    llm = CapturingSkillLLM(
        json.dumps(
            {
                "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
                "confidence": 0.86,
                "reason": "post-completion endorsement exception",
            }
        )
    )
    catalog = SkillCatalog(Path("app/skills"))
    selector = SkillSelector(llm_provider=llm)

    result = await selector.select(
        agent_name="troubleshooting_agent",
        context=_context(),
        candidates=catalog.list_skills("troubleshooting_agent"),
    )

    assert result.selected_skill_id == "troubleshooting_agent.endo_completion_aftercare"
    assert result.selection_source == "llm_rerank"
    assert result.llm_confidence == 0.86
    assert result.decision_trace["prompt_scene"] == "skill_selection"
    assert result.decision_trace["output_schema"] == "SkillSelectionLLMOutput"
    assert result.decision_trace["parse_status"] == "success"
    assert result.decision_trace["schema_status"] == "valid"
    assert llm.calls
    prompt = llm.calls[0]["messages"][1]["content"]
    assert "troubleshooting_agent.endo_completion_aftercare" in prompt
    assert "response_body" in prompt
    assert "# 保全任务完成后异常处理 Skill" not in prompt
    assert "通用步骤" not in prompt


async def test_skill_selector_invalid_llm_skill_id_falls_back_to_rule_top1():
    llm = CapturingSkillLLM(json.dumps({"selected_skill_id": "bad.skill", "confidence": 0.99, "reason": "bad"}))
    catalog = SkillCatalog(Path("app/skills"))
    selector = SkillSelector(llm_provider=llm)

    result = await selector.select(
        agent_name="troubleshooting_agent",
        context=_context(),
        candidates=catalog.list_skills("troubleshooting_agent"),
    )

    assert result.selected_skill_id == "troubleshooting_agent.endo_completion_aftercare"
    assert result.selection_source == "fallback"
    assert result.fallback is False
    assert result.fallback_reason == "skill_rerank_unusable"
    assert result.llm_status == "invalid_output"


async def test_skill_selector_invalid_json_falls_back_to_rule_top1():
    llm = CapturingSkillLLM("not json")
    catalog = SkillCatalog(Path("app/skills"))
    selector = SkillSelector(llm_provider=llm)

    result = await selector.select(
        agent_name="troubleshooting_agent",
        context=_context(),
        candidates=catalog.list_skills("troubleshooting_agent"),
    )

    assert result.selected_skill_id == "troubleshooting_agent.endo_completion_aftercare"
    assert result.selection_source == "fallback"
    assert result.fallback is False
    assert result.fallback_reason == "llm_json_parse_failed"
    assert result.llm_status == "parse_failed"
