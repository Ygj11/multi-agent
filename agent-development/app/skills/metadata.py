from __future__ import annotations

"""SKILL.md frontmatter 解析工具。"""

from pathlib import Path
from typing import Any

from app.schemas.skill import SkillMetadata


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """解析简化 YAML frontmatter，返回 metadata dict 和正文。"""
    normalized = text.replace("\r\n", "\n")
    if not normalized.startswith("---\n"):
        return {}, normalized
    end = normalized.find("\n---", 4)
    if end == -1:
        return {}, normalized
    frontmatter = normalized[4:end].strip("\n")
    body = normalized[end + len("\n---") :].lstrip("\n")
    return _parse_simple_yaml(frontmatter), body


def metadata_from_skill_file(path: Path, skills_root: Path) -> SkillMetadata | None:
    """只读取 SKILL.md frontmatter 并构造 SkillMetadata；正文不会进入 metadata。"""
    text = path.read_text(encoding="utf-8")
    data, _body = split_frontmatter(text)
    if not data.get("skill_id"):
        return None
    source_path = str(path.resolve())
    root = skills_root.resolve()
    if not Path(source_path).is_relative_to(root):
        raise ValueError(f"skill path is outside skills root: {source_path}")
    return SkillMetadata(
        skill_id=str(data["skill_id"]),
        name=str(data.get("name") or data["skill_id"]),
        description=str(data.get("description") or ""),
        agent=str(data.get("agent") or path.parent.parent.name),
        intent_tags=[str(item) for item in data.get("intent_tags", [])],
        business_domain=[str(item) for item in data.get("business_domain", [])],
        required_context=[str(item) for item in data.get("required_context", [])],
        enabled=_as_bool(data.get("enabled"), True),
        is_default=_as_bool(data.get("is_default"), False),
        source_path=source_path,
    )


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """解析本项目 SKILL.md 使用的 YAML 子集，避免额外依赖 PyYAML。"""
    result: dict[str, Any] = {}
    current_key: str | None = None
    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- ") and current_key:
            result.setdefault(current_key, []).append(_parse_scalar(stripped[2:].strip()))
            continue
        if ":" in stripped:
            key, value = stripped.split(":", 1)
            current_key = key.strip()
            value = value.strip()
            if value:
                result[current_key] = _parse_scalar(value)
            else:
                result[current_key] = []
    return result


def _parse_scalar(value: str) -> Any:
    """解析 bool、引号字符串和普通字符串。"""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _as_bool(value: Any, default: bool) -> bool:
    """将 frontmatter 值解析为 bool。"""
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
