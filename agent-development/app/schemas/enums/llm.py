from __future__ import annotations

"""LLM 调用场景和结构化输出解析状态。"""

from app.schemas.enums.base import DescribedStrEnum


class LLMScene(DescribedStrEnum):
    QUERY_REWRITE = ("query_rewrite", "问题改写。")
    INTENT_RECOGNITION = ("intent_recognition", "意图识别。")
    AGENT_SELECTION = ("agent_selection", "子 Agent 语义路由。")
    SKILL_SELECTION = ("skill_selection", "Skill 语义重排。")
    SUBAGENT_REASONING = ("subagent_reasoning", "子 Agent 工具循环推理。")
    TASK_COMPLETION_VERIFIER = ("task_completion_verifier", "任务完成度验收。")
    FINAL_COMPLIANCE = ("final_compliance", "最终答案合规验证。")
    SUMMARY = ("summary", "短期记忆摘要。")


class LLMStructuredParseStatus(DescribedStrEnum):
    SUCCESS = ("success", "LLM 输出成功解析并通过 schema 校验。")
    JSON_PARSE_FAILED = ("json_parse_failed", "LLM 输出不是合法 JSON 对象。")
    SCHEMA_VALIDATION_FAILED = ("schema_validation_failed", "LLM 输出 JSON 不满足目标 schema。")


class LLMStructuredErrorCode(DescribedStrEnum):
    JSON_PARSE_FAILED = ("llm_json_parse_failed", "LLM 输出 JSON 解析失败。")
    SCHEMA_VALIDATION_FAILED = ("llm_schema_validation_failed", "LLM 输出 schema 校验失败。")
