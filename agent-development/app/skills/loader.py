from __future__ import annotations

"""Skill 内容加载器。"""

from app.schemas.skill import SkillContent
from app.skills.catalog import SkillCatalog


class SkillLoader:
    """薄封装，统一通过 SkillCatalog 按 skill_id 加载完整内容。"""

    def __init__(self, catalog: SkillCatalog) -> None:
        """注入 SkillCatalog。"""
        self.catalog = catalog

    def load(self, skill_id: str) -> SkillContent:
        """加载完整 SKILL.md。"""
        return self.catalog.load_skill_content(skill_id)
