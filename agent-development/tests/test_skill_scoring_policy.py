from pathlib import Path

from app.schemas.skill import SkillMetadata, SkillSelectionContext
from app.skills.scorer import SkillRuleScorer
from app.skills.scoring_policy import SkillScoringPolicy


def _skill(**overrides):
    data = {
        "skill_id": "demo_agent.aftercare",
        "name": "aftercare",
        "description": "Demo skill",
        "agent": "demo_agent",
        "intent_tags": ["troubleshooting"],
        "required_entities": [],
        "optional_entities": [],
        "private_tools": [],
        "enabled": True,
        "is_default": False,
        "business_domain": [],
        "required_context": [],
        "routing_keywords": ["保全任务完成"],
        "routing_negative_keywords": ["回调失败"],
        "source_path": str(Path("app/skills/demo_agent/aftercare/SKILL.md").resolve()),
    }
    data.update(overrides)
    return SkillMetadata(**data)


def test_skill_scoring_policy_loads_configured_weights(tmp_path):
    policy_path = tmp_path / "scoring_policy.yaml"
    policy_path.write_text(
        """weights:
  routing_keyword_match: 8.5
  routing_negative_keyword_match: -6.0
""",
        encoding="utf-8",
    )

    policy = SkillScoringPolicy.load(policy_path)

    assert policy.weight("routing_keyword_match") == 8.5
    assert policy.weight("routing_negative_keyword_match") == -6.0
    assert policy.weight("intent_tag_match") == 3.0


def test_skill_rule_scorer_uses_routing_keywords_from_metadata():
    scorer = SkillRuleScorer(policy=SkillScoringPolicy.default())
    context = SkillSelectionContext(
        agent_name="demo_agent",
        intent="unknown",
        original_query="保全任务完成了，但是保单信息没有更新",
        rewritten_query="保全任务完成了，但是保单信息没有更新",
        session_key="s",
    )

    result = scorer.score(context, _skill())

    assert result.score >= 4
    assert "routing keyword matched: 保全任务完成" in result.reason


def test_skill_rule_scorer_applies_negative_routing_keywords():
    scorer = SkillRuleScorer(policy=SkillScoringPolicy.default())
    context = SkillSelectionContext(
        agent_name="demo_agent",
        intent="unknown",
        original_query="保全任务完成了，同时用户说回调失败",
        rewritten_query="保全任务完成了，同时用户说回调失败",
        session_key="s",
    )

    result = scorer.score(context, _skill())

    assert result.score == 0
    assert "routing keyword matched: 保全任务完成" in result.reason
    assert "routing negative keyword matched: 回调失败" in result.reason


def test_required_entity_skill_needs_strong_signal_for_confident_score():
    scorer = SkillRuleScorer(policy=SkillScoringPolicy.default())
    context = SkillSelectionContext(
        agent_name="troubleshooting_agent",
        intent="troubleshooting",
        original_query="继续排查 requestId=REQ_001 的 E102 错误",
        rewritten_query="继续排查 requestId=REQ_001 的 E102 错误",
        session_key="s",
        entities={"request_id": "REQ_001"},
        extracted_request_id="REQ_001",
        extracted_error_code="E102",
    )
    skill = _skill(
        skill_id="troubleshooting_agent.refund_failure",
        name="退保失败排查",
        description="用于排查保单退保没有成功、退保任务卡住、退保回调异常等问题",
        agent="troubleshooting_agent",
        intent="troubleshooting",
        sub_intents=["refund_failure"],
        intent_tags=["troubleshooting", "refund_failure", "退保失败"],
        required_entities=["policy_no"],
        optional_entities=["request_id"],
        business_domain=["health_insurance_onboarding"],
        routing_keywords=["退保", "退款", "refund", "退费", "退保失败"],
    )

    result = scorer.score(context, skill)

    assert result.score < 7.0
