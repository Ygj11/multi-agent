from __future__ import annotations

"""Intent and entity recognition node.

This node intentionally does not choose a sub agent.  It only understands the
task enough for later AgentCard-based selection.
"""

import re
from typing import Any

from app.llm.base import LLMProvider
from app.query.query_rewrite_node import FOLLOW_UP_MARKERS
from app.schemas.intent import IntentResult


class IntentRecognitionNode:
    """Lightweight rule-based intent and entity extraction for the MVP."""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def recognize(
        self,
        original_query: str,
        rewritten_query: str,
        recent_messages: list[dict[str, Any]] | None = None,
        short_summary: str | None = None,
    ) -> IntentResult:
        query = f"{original_query} {rewritten_query}"
        context_text = " ".join(
            [short_summary or ""]
            + [str(message.get("content", "")) for message in (recent_messages or [])]
        )
        entities = self.extract_entities(query)

        if self._is_follow_up(original_query) and self._has_troubleshooting_context(context_text):
            return IntentResult(intent="troubleshooting", confidence=0.9, entities=entities)

        if self._looks_compliance_review(query):
            return IntentResult(intent="compliance_review", confidence=0.86, entities=entities)
        if self._looks_document_parse(query):
            return IntentResult(intent="document_parse", confidence=0.84, entities=entities)
        if self._looks_change_impact(query):
            return IntentResult(intent="change_impact_analysis", confidence=0.86, entities=entities)
        if self._looks_claim_query(query):
            return IntentResult(intent="claim_query", confidence=0.84, entities=entities)
        if self._looks_troubleshooting(query, entities):
            return IntentResult(intent="troubleshooting", confidence=0.9, entities=entities)
        if self._looks_policy_query(query, entities):
            return IntentResult(intent="policy_query", confidence=0.84, entities=entities)
        if self._looks_product_rule_qa(query):
            return IntentResult(intent="product_rule_qa", confidence=0.78, entities=entities)
        return IntentResult(intent="unknown", confidence=0.5, entities=entities)

    @classmethod
    def extract_entities(cls, text: str) -> dict[str, str]:
        """Extract policy_no, request_id, error_code, interface_name, and similar keys."""
        entities: dict[str, str] = {}
        patterns = {
            "request_id": r"\bREQ[_-]?[A-Za-z0-9]+\b",
            "error_code": r"\bE\d{3,}\b",
            "policy_no": r"(?:保单(?:号)?[:：]?\s*|policy[_-]?no[:：]?\s*|\bP|\bPOL)[A-Za-z0-9]{6,}\b",
            "claim_no": r"\b(?:CLM|CLAIM)[_-]?[A-Za-z0-9]{3,}\b",
        }
        for key, pattern in patterns.items():
            match = re.search(pattern, text, flags=re.IGNORECASE)
            if match:
                value = match.group(0)
                if key == "policy_no" and ":" in value:
                    value = value.split(":", 1)[1].strip()
                if key == "policy_no":
                    value = re.sub(r"^(保单号?|policy[_-]?no)\s*[:：]?\s*", "", value, flags=re.IGNORECASE)
                entities[key] = value

        if "policy_no" not in entities:
            policy_match = re.search(r"保单(?:号)?[:：]?\s*([A-Za-z0-9]{6,})", text)
            if policy_match:
                entities["policy_no"] = policy_match.group(1)

        interface = cls._extract_interface_name(text)
        if interface:
            entities["interface_name"] = interface
        return entities

    @staticmethod
    def _extract_interface_name(text: str) -> str | None:
        match = re.search(r"\b[a-zA-Z][a-zA-Z0-9_]*(?:Proposal|Policy|Claim|Trace|Sign)\b", text)
        if match:
            return match.group(0)
        return None

    @staticmethod
    def _looks_troubleshooting(query: str, entities: dict[str, str]) -> bool:
        keywords = (
            "E102",
            "failed",
            "failure",
            "error",
            "exception",
            "timeout",
            "troubleshoot",
            "diagnose",
            "requestId",
            "REQ_",
            "报错",
            "失败",
            "排查",
                "退保失败",
                "退保没有成功",
                "没有成功",
            "回调失败",
            "签名",
        )
        return bool(entities.get("request_id") or entities.get("error_code")) or any(k in query for k in keywords)

    @staticmethod
    def _looks_compliance_review(query: str) -> bool:
        return any(
            keyword in query.lower()
            for keyword in (
                "compliance",
                "privacy",
                "redact",
                "sensitive",
                "token",
                "secret",
                "password",
                "合规",
                "隐私",
                "敏感信息",
                "脱敏",
                "外发",
                "身份证",
                "手机号",
            )
        )

    @staticmethod
    def _looks_claim_query(query: str) -> bool:
        return any(keyword in query.lower() for keyword in ("claim", "clm_", "理赔", "赔案"))

    @staticmethod
    def _looks_policy_query(query: str, entities: dict[str, str]) -> bool:
        if entities.get("policy_no"):
            return True
        return any(keyword in query.lower() for keyword in ("policy", "保单", "保单号", "保单状态"))

    @staticmethod
    def _looks_document_parse(query: str) -> bool:
        return any(keyword in query.lower() for keyword in ("parse", "markdown", "json", "yaml", "解析文档", "提取字段"))

    @staticmethod
    def _looks_change_impact(query: str) -> bool:
        return any(keyword in query for keyword in ("变更影响", "影响分析", "字段变更", "接口变更", "签名规则变更", "change impact"))

    @staticmethod
    def _looks_product_rule_qa(query: str) -> bool:
        return any(keyword in query for keyword in ("等待期", "责任", "条款", "product rule"))

    @staticmethod
    def _is_follow_up(query: str) -> bool:
        return any(marker in query for marker in FOLLOW_UP_MARKERS)

    @staticmethod
    def _has_troubleshooting_context(text: str) -> bool:
        return any(keyword in text for keyword in ("E102", "requestId", "REQ_"))
