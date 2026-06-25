from __future__ import annotations

"""基于 YAML 的通用实体抽取。

Extractor 只负责从文本中找出候选 EntityMention，不负责决定历史是否继承、
LLM 候选是否可信、同类型冲突如何处理。上述决策统一交给 EntityResolver。
"""

import re
import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Pattern

from app.schemas.entities import EntityBag, EntityMention


@dataclass(frozen=True)
class EntityPattern:
    """由实体 YAML 编译出的规则；regex 用于提取，value_regex 用于校验已得到的值。"""

    entity_type: str
    description: str
    regex: tuple[Pattern[str], ...]
    value_regex: tuple[Pattern[str], ...] = ()
    normalized_type: str = "string"
    sensitive: bool = False
    confidence: float = 1.0


class EntityTypeRegistry:
    """由实体 YAML 构建的实体类型注册表，校验 LLM 等外部候选的独立实体值。"""

    def __init__(self, patterns: list[EntityPattern]) -> None:
        self._value_regex_by_type = {
            pattern.entity_type: pattern.value_regex
            for pattern in patterns
            if pattern.value_regex
        }

    def accepts(self, entity_type: str, value: str) -> bool:
        """校验已提取出的单个实体值；未配置 value_regex 的动态实体只要求值非空。"""
        normalized = str(value).strip()
        if not normalized:
            return False
        validators = self._value_regex_by_type.get(entity_type)
        if not validators:
            return True
        return any(regex.fullmatch(normalized) for regex in validators)


@lru_cache(maxsize=1)
def default_entity_type_registry() -> EntityTypeRegistry:
    """进程内复用默认实体 YAML 注册表，避免每次状态投影重复读取配置文件。"""
    return EntityTypeRegistry(EntityPatternLoader().load())


class EntityPatternLoader:
    """加载并验证实体正则配置。"""

    REQUIRED_PATTERN_FIELDS = {"entity_type", "description", "regex"}

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(__file__).with_name("entity_patterns.yaml")

    def load(self) -> list[EntityPattern]:
        """
        从 YAML 配置文件加载实体模式定义，验证并编译为正则表达式。

        该方法负责整个实体模式的生命周期管理：
        1. 读取 YAML 配置文件
        2. 验证每个模式定义的完整性
        3. 编译所有正则表达式（提前发现语法错误）
        4. 返回结构化的实体模式对象列表

        Returns:
            list[EntityPattern]: 编译后的实体模式列表，每个模式包含：
                - entity_type: 实体类型标识
                - description: 实体描述
                - regex: 编译后的正则表达式元组（支持多个匹配模式）
                - value_regex: 值级校验正则，可选；用于校验 LLM、历史消息等候选值
                - normalized_type: 规范化类型
                - sensitive: 是否敏感信息
                - confidence: 匹配置信度

        Raises:
            ValueError: 在以下情况抛出异常：
                - 配置文件不存在
                - 配置文件格式错误（缺少 patterns 列表）
                - 某个模式缺少必需字段
                - 正则表达式语法错误

        YAML 格式要求:
            patterns:
              - entity_type: <string>         # 必需：实体类型
                description: <string>          # 必需：实体描述
                regex:                         # 必需：正则表达式列表（至少一个）
                  - "<pattern1>"
                  - "<pattern2>"
                value_regex:                   # 可选：完整实体值校验正则
                  - "^<value-pattern>$"
                normalized_type: <string>      # 可选：规范化类型，默认 "string"
                sensitive: <boolean>           # 可选：是否敏感，默认 false
                confidence: <float>            # 可选：置信度，默认 1.0

        Example:
            配置文件内容:
            patterns:
              - entity_type: phone_number
                description: 中国大陆手机号
                regex:
                  - "(?<!\\d)1[3-9]\\d{9}(?!\\d)"
                normalized_type: string
                sensitive: true
                confidence: 0.95
        """
        if not self.path.exists():
            raise ValueError(f"entity pattern file not found: {self.path}")
        raw = self._parse_patterns_yaml(self.path.read_text(encoding="utf-8"))
        patterns = raw.get("patterns")
        if not isinstance(patterns, list):
            raise ValueError(f"{self.path} must contain a patterns list")

        compiled: list[EntityPattern] = []
        for index, item in enumerate(patterns):
            if not isinstance(item, dict):
                raise ValueError(f"{self.path} patterns[{index}] must be a mapping")
            missing = sorted(self.REQUIRED_PATTERN_FIELDS - set(item))
            if missing:
                raise ValueError(f"{self.path} patterns[{index}] missing required fields: {missing}")
            regex_values = item["regex"]
            if not isinstance(regex_values, list) or not regex_values:
                raise ValueError(f"{self.path} patterns[{index}].regex must be a non-empty list")
            try:
                regex = tuple(re.compile(str(pattern), flags=re.IGNORECASE) for pattern in regex_values)
            except re.error as exc:
                raise ValueError(f"{self.path} patterns[{index}] invalid regex: {exc}") from exc
            value_regex_values = item.get("value_regex") or []
            if not isinstance(value_regex_values, list):
                raise ValueError(f"{self.path} patterns[{index}].value_regex must be a list when configured")
            try:
                value_regex = tuple(
                    re.compile(str(pattern), flags=re.IGNORECASE) for pattern in value_regex_values
                )
            except re.error as exc:
                raise ValueError(f"{self.path} patterns[{index}] invalid value_regex: {exc}") from exc
            # 构建实体模式对象
            compiled.append(
                EntityPattern(
                    entity_type=str(item["entity_type"]),
                    description=str(item["description"]),
                    regex=regex,
                    value_regex=value_regex,
                    normalized_type=str(item.get("normalized_type") or "string"),
                    sensitive=self._as_bool(item.get("sensitive", False)),
                    confidence=float(item.get("confidence", 1.0)),
                )
            )
        return compiled

    @staticmethod
    def _parse_patterns_yaml(text: str) -> dict[str, Any]:
        """Parse the small YAML subset used by entity_patterns.yaml."""
        result: dict[str, Any] = {}
        patterns: list[dict[str, Any]] = []
        current_pattern: dict[str, Any] | None = None
        current_list_key: str | None = None

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if stripped == "patterns:":
                result["patterns"] = patterns
                current_pattern = None
                current_list_key = None
                continue
            if stripped.startswith("- entity_type:"):
                current_pattern = {"entity_type": _parse_scalar(stripped.split(":", 1)[1].strip())}
                patterns.append(current_pattern)
                current_list_key = None
                continue
            if current_pattern is not None and stripped.startswith("- ") and current_list_key:
                current_pattern.setdefault(current_list_key, []).append(_parse_scalar(stripped[2:].strip()))
                continue
            if ":" in stripped:
                key, value = stripped.split(":", 1)
                key = key.strip()
                value = value.strip()
                if current_pattern is None:
                    result[key] = _parse_scalar(value) if value else []
                    continue
                if value:
                    current_pattern[key] = _parse_scalar(value)
                    current_list_key = None
                else:
                    current_pattern[key] = []
                    current_list_key = key
        result.setdefault("patterns", patterns)
        return result

    @staticmethod
    def _as_bool(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        return str(value).strip().lower() in {"1", "true", "yes", "y", "on"}


class EntityExtractor:
    """与具体 Agent 无关的规则实体抽取器。

    Query Rewrite、历史摘要和最近消息都复用同一套 YAML 规则，避免每个节点
    各自维护私有正则。新增可抽取实体时优先改 `entity_patterns.yaml`。
    """

    def __init__(self, patterns: list[EntityPattern] | None = None, loader: EntityPatternLoader | None = None) -> None:
        self.patterns = patterns if patterns is not None else (loader or EntityPatternLoader()).load()
        self.entity_type_registry = EntityTypeRegistry(self.patterns)

    def extract(self, text: str | None, source: str = "current_query", turn_id: str | None = None) -> EntityBag:
        """从文本中抽取实体；空文本返回空 EntityBag。"""
        bag = EntityBag()
        if not text:
            return bag
        for pattern in self.patterns:
            for regex in pattern.regex:
                for match in regex.finditer(text):
                    value = self._match_value(match)
                    if not value:
                        continue
                    normalized = self._normalize(pattern, value)
                    span_start, span_end = match.span()
                    bag.add(
                        EntityMention(
                            type=pattern.entity_type,
                            value=value,
                            normalized_value=normalized,
                            confidence=pattern.confidence,
                            source=source,
                            turn_id=turn_id,
                            sensitive=pattern.sensitive,
                            metadata={
                                "description": pattern.description,
                                "span_start": span_start,
                                "span_end": span_end,
                                **self._context_metadata(text, span_start),  # 判断修正
                            },
                        )
                    )
        return bag

    def extract_from_summary(self, summary: str | None) -> EntityBag:
        """从短期记忆摘要中抽取历史实体候选。"""
        return self.extract(summary, source="summary")

    def extract_from_recent_turns(self, turns: list[dict[str, Any]] | None) -> EntityBag:
        """从最近对话中抽取历史实体候选。"""
        bag = EntityBag()
        for index, turn in enumerate(turns or []):
            content = str(turn.get("content", ""))
            turn_id = str(turn.get("id") or turn.get("message_id") or index)
            bag.merge(self.extract(content, source="recent_turn", turn_id=turn_id))
        return bag

    @staticmethod
    def _match_value(match: re.Match[str]) -> str:
        if match.groups():
            for group in match.groups():
                if group:
                    return group.strip()
        return match.group(0).strip()

    @staticmethod
    def _normalize(pattern: EntityPattern, value: str) -> str:
        """Apply entity-specific normalization rules, e.g. for error_code we convert to uppercase to unify different casings."""
        if pattern.entity_type in {"request_id", "error_code", "product_code", "plan_code", "id_card"}:
            return value.strip().upper()
        if pattern.normalized_type == "string":
            return value.strip()
        return value.strip()

    @staticmethod
    def _context_metadata(text: str, span_start: int) -> dict[str, bool]:
        """Mark simple user correction cues near an extracted mention."""
        before = text[max(0, span_start - 16) : span_start]
        compact = "".join(before.split()).lower()
        metadata: dict[str, bool] = {}
        if compact.endswith("不是") or compact.endswith("并非") or compact.endswith("非"):
            metadata["negated"] = True
        if (
            compact.endswith("是")
            or compact.endswith("改成")
            or compact.endswith("改为")
            or compact.endswith("更正为")
            or compact.endswith("换成")
            or compact.endswith("应为")
            or compact.endswith("应该是")
        ) and not metadata.get("negated"):
            metadata["correction"] = True
        return metadata


def _parse_scalar(value: str) -> Any:
    value = value.strip()
    if value.lower() == "true":
        return True
    if value.lower() == "false":
        return False
    try:
        if "." in value:
            return float(value)
        return int(value)
    except ValueError:
        pass
    if (value.startswith('"') and value.endswith('"')) or (value.startswith("'") and value.endswith("'")):
        try:
            return json.loads(value) if value.startswith('"') else value[1:-1]
        except json.JSONDecodeError:
            return value[1:-1]
    return value
