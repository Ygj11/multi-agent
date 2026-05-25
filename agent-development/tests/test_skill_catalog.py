from pathlib import Path

import pytest

from app.agents.card_loader import AgentCardLoader
from app.skills.catalog import SkillCatalog
from app.skills.metadata import metadata_from_skill_file


CARDS_ROOT = Path("app/agents/cards")
SKILLS_ROOT = Path("app/skills")
REQUIRED_FIELDS = {
    "skill_id",
    "name",
    "description",
    "agent",
    "intent_tags",
    "required_entities",
    "private_tools",
    "enabled",
    "is_default",
}


def test_skill_catalog_scans_metadata_without_body():
    """SkillCatalog scans metadata without loading full skill bodies."""
    catalog = SkillCatalog(SKILLS_ROOT)

    skills = catalog.scan()
    signature = catalog.get_skill_metadata("troubleshooting_agent.signature_error")

    assert len(skills) >= 12
    assert signature is not None
    assert signature.agent == "troubleshooting_agent"
    assert "执行步骤" not in signature.model_dump_json()


def test_skill_catalog_loads_full_skill_content_by_id():
    """Selected skills can be loaded by skill_id."""
    catalog = SkillCatalog(SKILLS_ROOT)

    content = catalog.load_skill_content("troubleshooting_agent.signature_error")

    assert content.metadata.skill_id == "troubleshooting_agent.signature_error"
    assert "签名失败排查 Skill" in content.content
    assert "query_internal_log" in content.content


def test_all_active_skill_metadata_is_complete_and_unique():
    catalog = SkillCatalog(SKILLS_ROOT)
    skills = catalog.scan(force_reload=True)
    skill_ids = [skill.skill_id for skill in skills]

    assert len(skill_ids) == len(set(skill_ids))
    for skill in skills:
        dumped = skill.model_dump()
        assert REQUIRED_FIELDS.issubset(dumped)
        assert skill.skill_id.startswith(f"{skill.agent}.")
        assert skill.intent_tags


def test_agent_cards_and_skill_metadata_match():
    cards = {card.agent_name: card for card in AgentCardLoader(CARDS_ROOT).load_all(force_reload=True)}
    skills = {skill.skill_id: skill for skill in SkillCatalog(SKILLS_ROOT).scan(force_reload=True)}

    for card in cards.values():
        card_skills = [skills[skill_id] for skill_id in card.skills]
        assert any(skill.is_default for skill in card_skills)
        for skill_id in card.skills:
            assert skill_id in skills
            skill = skills[skill_id]
            assert skill.agent == card.agent_name
            assert set(skill.private_tools).issubset(set(card.private_tools))


def test_deprecated_skills_do_not_participate_in_scan():
    skills = SkillCatalog(SKILLS_ROOT).scan(force_reload=True)

    assert all("deprecated" not in skill.source_path for skill in skills)
    assert all("deprecated" not in skill.skill_id for skill in skills)


def test_disabled_skill_does_not_join_default_candidates(tmp_path):
    """enabled=false skills do not join the default candidate list."""
    skill_dir = tmp_path / "skills" / "demo_agent" / "disabled"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
skill_id: demo_agent.disabled
name: disabled
description: disabled skill
agent: demo_agent
intent_tags:
  - demo
required_entities: []
optional_entities: []

private_tools: []
enabled: false
is_default: false
---

# Disabled
""",
        encoding="utf-8",
    )
    catalog = SkillCatalog(tmp_path / "skills")

    assert catalog.list_skills("demo_agent") == []
    assert len(catalog.list_skills("demo_agent", include_disabled=True)) == 1


def test_legacy_name_description_only_skill_fails_validation(tmp_path):
    skill_dir = tmp_path / "skills" / "demo_agent" / "legacy"
    skill_dir.mkdir(parents=True)
    skill_path = skill_dir / "SKILL.md"
    skill_path.write_text(
        """---
name: legacy
description: old simplified metadata
---

# Legacy
""",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="missing required Skill metadata fields"):
        metadata_from_skill_file(skill_path, tmp_path / "skills")
