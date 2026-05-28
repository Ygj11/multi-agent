from __future__ import annotations

"""SKILL.md frontmatter parsing and validation."""

import json
from pathlib import Path
from typing import Any

from app.schemas.skill import SkillMetadata


REQUIRED_SKILL_METADATA_FIELDS = (
    "skill_id",
    "name",
    "description",
    "agent",
    "intent_tags",
    "required_entities",
    "optional_entities",
    "private_tools",
    "enabled",
    "is_default",
)


def split_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse the simple YAML frontmatter used by project skills."""
    normalized = text.replace("\r\n", "\n").lstrip("\ufeff")
    if not normalized.startswith("---\n"):
        return {}, normalized
    end = normalized.find("\n---", 4)
    if end == -1:
        return {}, normalized
    frontmatter = normalized[4:end].strip("\n")
    body = normalized[end + len("\n---") :].lstrip("\n")
    return _parse_simple_yaml(frontmatter), body


def metadata_from_skill_file(path: Path, skills_root: Path) -> SkillMetadata:
    """Read and validate Skill metadata without loading the body into metadata."""
    text = path.read_text(encoding="utf-8")
    data, _body = split_frontmatter(text)
    validate_skill_frontmatter(data, path)
    source_path = str(path.resolve())
    root = skills_root.resolve()
    if not Path(source_path).is_relative_to(root):
        raise ValueError(f"skill path is outside skills root: {source_path}")
    return SkillMetadata(
        skill_id=str(data["skill_id"]),
        name=str(data["name"]),
        description=str(data["description"]),
        agent=str(data["agent"]),
        intent_tags=[str(item) for item in data["intent_tags"]],
        required_entities=[str(item) for item in data["required_entities"]],
        optional_entities=[str(item) for item in data["optional_entities"]],
        private_tools=[str(item) for item in data["private_tools"]],
        public_tools=[str(item) for item in data.get("public_tools", [])],
        mcp_tools=[str(item) for item in data.get("mcp_tools", [])],
        enabled=_as_bool(data["enabled"]),
        is_default=_as_bool(data["is_default"]),
        business_domain=[str(item) for item in data.get("business_domain", [])],
        required_context=[str(item) for item in data.get("required_context", [])],
        source_path=source_path,
    )


def validate_skill_frontmatter(data: dict[str, Any], path: Path) -> None:
    """Validate the enterprise Skill metadata contract."""
    if not data:
        raise ValueError(f"{path} must contain YAML frontmatter with full Skill metadata")
    missing = [field for field in REQUIRED_SKILL_METADATA_FIELDS if field not in data]
    if missing:
        raise ValueError(f"{path} missing required Skill metadata fields: {missing}")
    for field in ("intent_tags", "required_entities", "optional_entities", "private_tools"):
        if not isinstance(data[field], list):
            raise ValueError(f"{path} field {field} must be a list")
    if not data["intent_tags"]:
        raise ValueError(f"{path} field intent_tags must contain at least one item")
    skill_id = str(data["skill_id"])
    agent = str(data["agent"])
    if "." not in skill_id:
        raise ValueError(f"{path} skill_id must use '<agent_name>.<skill_name>' format")
    if not skill_id.startswith(f"{agent}."):
        raise ValueError(f"{path} skill_id must start with '{agent}.'")


def _parse_simple_yaml(text: str) -> dict[str, Any]:
    """Parse the YAML subset used in this repository."""
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
    """Parse bool, inline JSON, quoted strings, and plain strings."""
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    if value.startswith(("[", "{")):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return value
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value


def _as_bool(value: Any) -> bool:
    """Parse a frontmatter value as bool."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}
