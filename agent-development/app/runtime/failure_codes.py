from __future__ import annotations

"""Stable runtime failure and fallback codes."""


LLM_DISABLED = "llm_disabled"
LLM_PROVIDER_ERROR = "llm_provider_error"
LLM_JSON_PARSE_FAILED = "llm_json_parse_failed"
LLM_INVALID_OUTPUT = "llm_invalid_output"
LLM_SCHEMA_VALIDATION_FAILED = "llm_schema_validation_failed"
TAXONOMY_MISMATCH = "taxonomy_mismatch"
INVALID_INTENT = "invalid_intent"
INVALID_SUB_INTENT = "invalid_sub_intent"
AGENT_ROUTER_UNUSABLE = "agent_router_unusable"
SKILL_RERANK_UNUSABLE = "skill_rerank_unusable"
NO_CONFIDENT_SKILL = "no_confident_skill"
NO_ENABLED_SKILLS = "no_enabled_skills"
NO_SKILL_POLICY_BLOCKED = "no_skill_policy_blocked"


LLM_STATUS_DISABLED = "disabled"
LLM_STATUS_SUCCESS = "success"
LLM_STATUS_PROVIDER_ERROR = "provider_error"
LLM_STATUS_PARSE_FAILED = "parse_failed"
LLM_STATUS_INVALID_OUTPUT = "invalid_output"
