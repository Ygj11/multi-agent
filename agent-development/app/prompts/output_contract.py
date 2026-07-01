from __future__ import annotations

"""把结构化 LLM 输出 schema 渲染成 prompt 可读契约。

Pydantic schema 仍是运行时强校验的唯一事实来源；这里生成的文本只是给 LLM
看的输出说明，避免 prompt 只写 schema 名称导致模型靠猜字段结构。
"""

import json
from typing import Any

from pydantic import BaseModel

from app.llm.output_schemas import SCHEMA_REGISTRY


NON_JSON_CONTRACT_SCHEMAS = {"text", "SubAgentResult", "VerificationResult"}


class PromptOutputContractRenderer:
    """根据 PromptManifest.output_schema 生成 LLM 友好的输出契约。

    PromptOutputContractRenderer，支持 QueryRewriteLLMOutput、IntentRecognitionLLMOutput、AgentSelectionLLMOutput、SkillSelectionLLMOutput、TaskCompletionLLMOutput

    非结构化 scene 如 memory_summary、subagent_reasoning、final_compliance 不强行注入 JSON contract
    """

    def render_for_scene(self, scene) -> str:
        """根据 scene manifest 的 output_schema 渲染契约文本。"""
        return self.render_for_schema(scene.output_schema)

    def render_for_schema(self, schema_name: str) -> str:
        """生成指定 schema 的输出契约；非结构化 schema 返回空字符串。"""
        if schema_name in NON_JSON_CONTRACT_SCHEMAS:
            return ""
        model = SCHEMA_REGISTRY.get(schema_name)
        if model is None:
            raise ValueError(f"unknown prompt output schema: {schema_name}")
        schema = model.model_json_schema()
        defs = schema.get("$defs") or {}
        required = set(schema.get("required") or [])
        lines = [
            f"Output contract: {schema_name}",
            "",
            "Return exactly one JSON object. Do not wrap it in Markdown. Do not add extra keys.",
            "",
            "Allowed fields:",
        ]
        for field_name, field_schema in (schema.get("properties") or {}).items():
            required_text = "required" if field_name in required else "optional"
            default_text = self._default_text(field_schema)
            lines.append(
                f"- {field_name}: {self._describe_schema(field_schema, defs)}, {required_text}{default_text}."
            )
        extra = self._schema_specific_rules(schema_name)
        if extra:
            lines.extend(["", *extra])
        example = self._example_for_schema(schema_name)
        if example:
            lines.extend(["", "Example:", json.dumps(example, ensure_ascii=False, indent=2)])
        return "\n".join(lines).strip()

    def _describe_schema(self, schema: dict[str, Any], defs: dict[str, Any]) -> str:
        if "$ref" in schema:
            return self._describe_ref(schema["$ref"], defs)
        if "anyOf" in schema:
            return self._describe_any_of(schema["anyOf"], defs)
        if "enum" in schema:
            return "string enum. One of: " + ", ".join(str(item) for item in schema["enum"])
        item_type = schema.get("type")
        if item_type == "array":
            return "array of " + self._describe_array_item(schema.get("items") or {}, defs)
        if item_type == "object":
            return "object"
        if item_type == "number":
            bounds = self._bounds(schema)
            return f"number{bounds}"
        if item_type in {"string", "boolean", "integer", "null"}:
            return str(item_type)
        return "value"

    def _describe_ref(self, ref: str, defs: dict[str, Any]) -> str:
        name = ref.rsplit("/", 1)[-1]
        definition = defs.get(name) or {}
        if "enum" in definition:
            return "string enum. One of: " + ", ".join(str(item) for item in definition["enum"])
        if definition.get("type") == "object":
            return f"object ({name})"
        return name

    def _describe_any_of(self, choices: list[dict[str, Any]], defs: dict[str, Any]) -> str:
        descriptions = [self._describe_schema(choice, defs) for choice in choices]
        deduped: list[str] = []
        for item in descriptions:
            if item not in deduped:
                deduped.append(item)
        return " or ".join(deduped)

    def _describe_array_item(self, schema: dict[str, Any], defs: dict[str, Any]) -> str:
        if not schema:
            return "value"
        return self._describe_schema(schema, defs)

    @staticmethod
    def _default_text(schema: dict[str, Any]) -> str:
        if "default" not in schema:
            return ""
        default = schema.get("default")
        return f", default {json.dumps(default, ensure_ascii=False)}"

    @staticmethod
    def _bounds(schema: dict[str, Any]) -> str:
        parts = []
        if "minimum" in schema:
            parts.append(f">= {schema['minimum']}")
        if "maximum" in schema:
            parts.append(f"<= {schema['maximum']}")
        return " (" + ", ".join(parts) + ")" if parts else ""

    @staticmethod
    def _schema_specific_rules(schema_name: str) -> list[str]:
        if schema_name == "TaskCompletionLLMOutput":
            return [
                "repair_plan when status is CONTINUE:",
                "- reason: string, required.",
                "- completed_items: array of string.",
                "- missing_items: array of string.",
                "- next_steps: array of string.",
                "- do_not_repeat: array of string.",
                "- reuse_evidence_ids: array of string.",
                "- expected_new_evidence: array of string.",
                "- target_agent: string, required. Must equal selected_agent from input.",
                "- selected_skill_id: string, required. Must equal selected_skill_id from input.",
                "- confidence: number, required, 0.0 <= confidence <= 1.0.",
                "- fingerprint: string or null.",
                "",
                "Validation rules:",
                "- If status is PASS, completed must be true and repair_plan must be null.",
                "- If status is CONTINUE, completed must be false and repair_plan is required.",
                "- If status is NEED_USER, HUMAN_HANDOFF, or FAILED, completed must be false.",
                "- reasoning_summary is an auditable summary only. Do not include hidden chain-of-thought.",
                "- Do not output fields outside this contract.",
            ]
        return ["Do not output fields outside this contract."]

    @staticmethod
    def _example_for_schema(schema_name: str) -> dict[str, Any] | None:
        examples: dict[str, dict[str, Any]] = {
            "QueryRewriteLLMOutput": {
                "is_follow_up": False,
                "rewritten_query": "保全任务完成后保单未更新，保单号 9200100000458846，受理号 930021042875719。",
                "rewrite_type": "new_request",
                "entities": {"policy_no": "9200100000458846", "apply_seq": "930021042875719"},
                "inherited_entities": {},
                "missing_required_entities": [],
                "need_clarification": False,
                "clarification_question": None,
                "confidence": 0.92,
                "reason": "当前消息包含完整业务锚点。",
            },
            "IntentRecognitionLLMOutput": {
                "intent": "troubleshooting",
                "sub_intent": "endo_completion_aftercare",
                "confidence": 0.91,
                "need_clarification": False,
                "clarification_question": None,
                "reason": "rewritten_query 明确描述保全完成后未更新排查。",
            },
            "AgentSelectionLLMOutput": {
                "selected_agent": "troubleshooting_agent",
                "confidence": 0.88,
                "reason": "候选 Agent 的 supported_routes 与 intent/sub_intent 匹配。",
                "need_clarification": False,
                "clarification_question": None,
            },
            "SkillSelectionLLMOutput": {
                "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
                "confidence": 0.87,
                "reason": "候选 Skill 的 sub_intents 与问题语义匹配。",
            },
            "TaskCompletionLLMOutput": {
                "status": "PASS",
                "completed": True,
                "summary": "已基于工具证据确认任务完成。",
                "completed_items": ["已查询任务状态"],
                "missing_items": [],
                "repair_plan": None,
                "confidence": 0.86,
                "reasoning_summary": "工具结果和证据摘要均支持任务已完成。",
                "evidence_ids": [],
            },
        }
        return examples.get(schema_name)


default_output_contract_renderer = PromptOutputContractRenderer()
