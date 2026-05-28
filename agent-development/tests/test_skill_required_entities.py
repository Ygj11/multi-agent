from app.schemas.entities import EntityBag, EntityMention
from app.skills.required_entities import RequiredEntityChecker
from app.skills.catalog import SkillCatalog


def _skill(skill_id: str):
    return SkillCatalog(__import__("pathlib").Path("app/skills")).get_skill_metadata(skill_id)


def test_skill_required_entities_satisfied():
    result = RequiredEntityChecker().check(
        skill=_skill("troubleshooting_agent.signature_error"),
        entities={"error_code": "E102"},
        entity_bag=EntityBag(),
    )

    assert result.need_clarification is False


def test_skill_required_entities_missing_clarifies():
    result = RequiredEntityChecker().check(
        skill=_skill("claim_agent.default"),
        entities={},
        entity_bag=EntityBag(),
    )

    assert result.need_clarification is True
    assert result.missing_required_entities == ["claim_no"]


def test_optional_entities_do_not_block():
    result = RequiredEntityChecker().check(
        skill=_skill("policy_query_agent.default"),
        entities={"policy_no": "P2021344266"},
        entity_bag=EntityBag(),
    )

    assert result.need_clarification is False


def test_required_entity_inherited_from_bag():
    bag = EntityBag()
    bag.add(EntityMention(type="claim_no", value="CLM_001", confidence=0.95, source="summary"))
    result = RequiredEntityChecker().check(skill=_skill("claim_agent.default"), entities={}, entity_bag=bag)

    assert result.entities["claim_no"] == "CLM_001"
    assert result.need_clarification is False


def test_multiple_candidates_clarify():
    bag = EntityBag()
    bag.add(EntityMention(type="claim_no", value="CLM_001", confidence=0.95, source="summary"))
    bag.add(EntityMention(type="claim_no", value="CLM_002", confidence=0.95, source="summary"))
    result = RequiredEntityChecker().check(skill=_skill("claim_agent.default"), entities={}, entity_bag=bag)

    assert result.need_clarification is True
    assert result.missing_required_entities == ["claim_no"]


def test_endo_completion_aftercare_requires_apply_seq_policy_no_and_endorse_type():
    result = RequiredEntityChecker().check(
        skill=_skill("troubleshooting_agent.endo_completion_aftercare"),
        entities={"apply_seq": "APPLY_POLICY_UPDATE_FAIL"},
        entity_bag=EntityBag(),
    )

    assert result.need_clarification is True
    assert result.missing_required_entities == ["policy_no", "endorseType"]
    assert "保单号 policy_no" in result.clarification_question
    assert "保全项 endorseType" in result.clarification_question
