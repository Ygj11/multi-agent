from __future__ import annotations

"""Configurable field visibility policy for final-answer data filtering."""

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


DEFAULT_FIELD_VISIBILITY_POLICY_PATH = Path(__file__).with_name("field_visibility_policy.yaml")


@dataclass(frozen=True)
class FieldVisibilityRule:
    category: str
    allow_permissions: set[str] = field(default_factory=set)
    action: str = "redact"
    pattern: str | None = None
    mask: str | None = None
    keywords: tuple[str, ...] = ()
    preserve_if_category_allowed: str | None = None


@dataclass(frozen=True)
class FieldVisibilityPolicy:
    """未声明类别默认拒绝的字段可见性策略。

    空权限列表不会授予该类别权限；没有规则的类别不可见。这与路由提示不同，
    路由提示为空只会关闭一个可选信号。
    """

    privileged_roles: set[str] = field(default_factory=set)
    rules: dict[str, FieldVisibilityRule] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path = DEFAULT_FIELD_VISIBILITY_POLICY_PATH) -> "FieldVisibilityPolicy":
        if not path.exists():
            raise FileNotFoundError(f"field visibility policy not found: {path}")
        return cls.from_mapping(_load_policy_data(path), path=path)

    @classmethod
    def from_mapping(cls, data: dict[str, Any], *, path: Path | None = None) -> "FieldVisibilityPolicy":
        location = str(path or "field visibility policy")
        if not isinstance(data, dict):
            raise ValueError(f"{location} must be a mapping")
        categories = data.get("categories", {})
        if not isinstance(categories, dict):
            raise ValueError(f"{location} categories must be a mapping")

        privileged_roles = {str(item) for item in data.get("privileged_roles", []) or []}
        rules: dict[str, FieldVisibilityRule] = {}
        for category, raw_rule in categories.items():
            if not isinstance(raw_rule, dict):
                raise ValueError(f"{location} category {category} must be a mapping")
            rule = cls._rule_from_mapping(
                category=str(category),
                raw_rule=raw_rule,
                location=location,
            )
            rules[rule.category] = rule
        return cls(
            privileged_roles=privileged_roles,
            rules=rules,
        )

    @staticmethod
    def _rule_from_mapping(
        *,
        category: str,
        raw_rule: dict[str, Any],
        location: str,
    ) -> FieldVisibilityRule:
        allow_permissions = {str(item) for item in (raw_rule.get("allow_permissions") or [])}
        keywords = tuple(str(item) for item in (raw_rule.get("keywords") or ()))
        pattern = raw_rule.get("pattern")
        mask = raw_rule.get("mask")
        action = str(raw_rule.get("action") or ("redact" if pattern else "warn"))
        preserve_if_category_allowed = raw_rule.get("preserve_if_category_allowed")
        if pattern:
            try:
                re.compile(str(pattern))
            except re.error as exc:
                raise ValueError(f"{location} category {category} has invalid regex: {exc}") from exc
        if action == "redact" and (not pattern or not mask):
            raise ValueError(f"{location} category {category} redact rule requires pattern and mask")
        if action == "warn" and not keywords:
            raise ValueError(f"{location} category {category} warn rule requires keywords")
        return FieldVisibilityRule(
            category=category,
            allow_permissions=allow_permissions,
            action=action,
            pattern=str(pattern) if pattern else None,
            mask=str(mask) if mask else None,
            keywords=keywords,
            preserve_if_category_allowed=str(preserve_if_category_allowed) if preserve_if_category_allowed else None,
        )

    def rule(self, category: str) -> FieldVisibilityRule | None:
        return self.rules.get(category)

    def redaction_rules(self) -> list[FieldVisibilityRule]:
        return [
            rule
            for rule in self.rules.values()
            if rule.action == "redact" and rule.pattern and rule.mask
        ]

    def keyword_rules(self) -> list[FieldVisibilityRule]:
        return [rule for rule in self.rules.values() if rule.action == "warn" and rule.keywords]

    def can_view(self, *, category: str, roles: set[str], permissions: set[str]) -> bool:
        if self.privileged_roles.intersection(roles):
            return True
        rule = self.rule(category)
        if rule is None:
            return False
        return bool(rule.allow_permissions.intersection(permissions))


def _load_policy_data(path: Path) -> dict[str, Any]:
    try:
        import yaml  # type: ignore
    except ImportError:
        return _parse_simple_policy_yaml(path)
    loaded = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(loaded, dict):
        raise ValueError(f"{path} must contain a mapping")
    return loaded


def _parse_simple_policy_yaml(path: Path) -> dict[str, Any]:
    """Fallback parser for this policy file's small YAML subset."""
    result: dict[str, Any] = {"privileged_roles": [], "categories": {}}
    section: str | None = None
    current_category: str | None = None
    current_list_key: str | None = None
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if not raw_line.strip() or raw_line.lstrip().startswith("#"):
            continue
        indent = len(raw_line) - len(raw_line.lstrip(" "))
        line = raw_line.strip()
        if indent == 0 and line.endswith(":"):
            section = line[:-1]
            current_category = None
            current_list_key = None
            continue
        if section == "privileged_roles" and line.startswith("- "):
            result["privileged_roles"].append(_strip_quotes(line[2:].strip()))
            continue
        if section == "categories" and indent == 2 and line.endswith(":"):
            current_category = line[:-1]
            result["categories"][current_category] = {}
            current_list_key = None
            continue
        if section == "categories" and current_category and indent == 4 and ":" in line:
            key, value = line.split(":", 1)
            key = key.strip()
            value = value.strip()
            if value:
                result["categories"][current_category][key] = _strip_quotes(value)
                current_list_key = None
            else:
                result["categories"][current_category][key] = []
                current_list_key = key
            continue
        if section == "categories" and current_category and current_list_key and indent == 6 and line.startswith("- "):
            result["categories"][current_category][current_list_key].append(_strip_quotes(line[2:].strip()))
    return result


def _strip_quotes(value: str) -> str:
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        return value[1:-1]
    return value
