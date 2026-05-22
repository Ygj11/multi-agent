from __future__ import annotations

"""本地 SkillCatalog。"""

from pathlib import Path

from app.observability.logger import log_event
from app.schemas.skill import SkillContent, SkillMetadata
from app.skills.metadata import metadata_from_skill_file


class SkillCatalog:
    """扫描和缓存 skill metadata，并按需加载完整 SKILL.md。"""

    def __init__(self, skills_root: Path) -> None:
        """保存 skill 根目录。"""
        self.skills_root = skills_root
        self._metadata_by_id: dict[str, SkillMetadata] = {}
        self._scanned = False

    def scan(self, force_reload: bool = False) -> list[SkillMetadata]:
        """扫描所有 SKILL.md，只解析 frontmatter metadata。"""
        if self._scanned and not force_reload:
            return list(self._metadata_by_id.values())

        metadata_by_id: dict[str, SkillMetadata] = {}
        if self.skills_root.exists():
            for path in sorted(self.skills_root.rglob("SKILL.md")):
                relative = path.relative_to(self.skills_root)
                if len(relative.parts) != 3 or relative.parts[0] == "deprecated":
                    continue
                metadata = metadata_from_skill_file(path, self.skills_root)
                if metadata is not None:
                    metadata_by_id[metadata.skill_id] = metadata

        self._metadata_by_id = metadata_by_id
        self._scanned = True
        log_event(
            "skill_metadata_loaded",
            node="skill_catalog",
            message="Skill metadata loaded",
            data={"skill_count": len(metadata_by_id), "skill_ids": sorted(metadata_by_id)},
        )
        return list(metadata_by_id.values())

    def list_skills(self, agent_name: str, include_disabled: bool = False) -> list[SkillMetadata]:
        """列出指定子 Agent 的候选 skill metadata。"""
        skills = [
            item
            for item in self.scan()
            if item.agent == agent_name and (include_disabled or item.enabled)
        ]
        log_event(
            "skill_candidates_built",
            node="skill_catalog",
            message="Skill candidates built",
            data={"agent_name": agent_name, "candidate_count": len(skills), "skill_ids": [item.skill_id for item in skills]},
        )
        return skills

    def get_skill_metadata(self, skill_id: str) -> SkillMetadata | None:
        """按 skill_id 获取 metadata。"""
        return self._metadata_by_id.get(skill_id) or {item.skill_id: item for item in self.scan()}.get(skill_id)

    def load_skill_content(self, skill_id: str) -> SkillContent:
        """按需加载完整 SKILL.md 内容。"""
        metadata = self.get_skill_metadata(skill_id)
        if metadata is None:
            raise ValueError(f"skill not found: {skill_id}")
        path = Path(metadata.source_path).resolve()
        if not path.is_relative_to(self.skills_root.resolve()):
            raise ValueError(f"skill path is outside skills root: {path}")
        content = path.read_text(encoding="utf-8")
        log_event(
            "skill_content_loaded",
            node="skill_catalog",
            message="Skill content loaded",
            data={"selected_skill_id": skill_id, "agent_name": metadata.agent},
        )
        return SkillContent(metadata=metadata, content=content)
