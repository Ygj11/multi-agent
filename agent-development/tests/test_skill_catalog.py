from pathlib import Path

from app.skills.catalog import SkillCatalog


def test_skill_catalog_scans_metadata_without_body():
    """SkillCatalog 扫描 metadata 时不加载完整正文。"""
    catalog = SkillCatalog(Path("app/skills"))

    skills = catalog.scan()
    signature = catalog.get_skill_metadata("troubleshooting.signature_error")

    assert len(skills) >= 12
    assert signature is not None
    assert signature.agent == "troubleshooting_agent"
    assert "执行步骤" not in signature.model_dump_json()


def test_skill_catalog_loads_full_skill_content_by_id():
    """选中 skill 后才能按 skill_id 加载完整 SKILL.md。"""
    catalog = SkillCatalog(Path("app/skills"))

    content = catalog.load_skill_content("troubleshooting.signature_error")

    assert content.metadata.skill_id == "troubleshooting.signature_error"
    assert "签名失败排查 Skill" in content.content
    assert "query_internal_log" in content.content


def test_disabled_skill_does_not_join_default_candidates(tmp_path):
    """enabled=false 的 skill 不参与默认候选列表。"""
    skill_dir = tmp_path / "skills" / "demo_agent" / "disabled"
    skill_dir.mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        """---
skill_id: demo.disabled
name: disabled
description: disabled skill
agent: demo_agent
intent_tags:
  - demo
business_domain:
  - health_insurance_onboarding
required_context:
  - request_id
enabled: false
---

# Disabled
""",
        encoding="utf-8",
    )
    catalog = SkillCatalog(tmp_path / "skills")

    assert catalog.list_skills("demo_agent") == []
    assert len(catalog.list_skills("demo_agent", include_disabled=True)) == 1
