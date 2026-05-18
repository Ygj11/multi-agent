from __future__ import annotations

"""规则版意图识别节点。"""

from typing import Any

from app.query.query_rewrite_node import FOLLOW_UP_MARKERS
from app.schemas.intent import IntentResult


class IntentRecognitionNode:
    """识别固定 MVP 意图，并给出目标子 Agent 和工具需求。"""

    async def recognize(
        self,
        original_query: str,
        rewritten_query: str,
        recent_messages: list[dict[str, Any]] | None = None,
        short_summary: str | None = None,
    ) -> IntentResult:
        """根据 query 和会话上下文输出意图、置信度、目标子 Agent 和工具需求。"""
        query = f"{original_query} {rewritten_query}"
        context_text = " ".join(
            [short_summary or ""]
            + [str(message.get("content", "")) for message in (recent_messages or [])]
        )

        # 排障追问优先，避免“这个问题继续看一下”被误路由到其他 Agent。
        if self._is_follow_up(original_query) and self._has_troubleshooting_context(context_text):
            return IntentResult(
                intent="troubleshooting",
                confidence=0.92,
                target_subagent="troubleshooting_agent",
                required_tools=["query_internal_log", "get_knowledge"],
            )

        if self._looks_compliance_review(query):
            return IntentResult(
                intent="compliance_review",
                confidence=0.86,
                target_subagent="compliance_security_agent",
                required_tools=[],
            )

        if self._looks_document_parse(query):
            return IntentResult(
                intent="document_parse",
                confidence=0.86,
                target_subagent="document_parse_agent",
                required_tools=[],
            )

        if self._looks_change_impact(query):
            return IntentResult(
                intent="change_impact_analysis",
                confidence=0.88,
                target_subagent="change_impact_analysis_agent",
                required_tools=["get_knowledge"],
            )

        if self._looks_troubleshooting(query):
            return IntentResult(
                intent="troubleshooting",
                confidence=0.92,
                target_subagent="troubleshooting_agent",
                required_tools=["query_internal_log", "get_knowledge"],
            )

        if any(keyword in query for keyword in ("等待期", "责任", "条款")):
            return IntentResult(
                intent="product_rule_qa",
                confidence=0.82,
                target_subagent=None,
                required_tools=["get_knowledge"],
            )

        return IntentResult(intent="unknown", confidence=0.5, target_subagent=None, required_tools=[])

    @staticmethod
    def _looks_troubleshooting(query: str) -> bool:
        """判断文本是否包含问题排查类关键词。"""
        return any(
            keyword in query
            for keyword in (
                "E102",
                "失败",
                "报错",
                "requestId",
                "REQ_",
                "排查",
                "字段缺失",
                "不能为空",
                "必填",
                "回调失败",
                "回调超时",
                "未收到回调",
            )
        )

    @staticmethod
    def _looks_compliance_review(query: str) -> bool:
        """识别隐私、敏感信息、脱敏和外发风险检查意图。"""
        return any(
            keyword in query
            for keyword in (
                "合规",
                "隐私",
                "敏感信息",
                "脱敏",
                "外发",
                "能不能发",
                "身份证",
                "手机号",
                "健康告知",
                "医疗记录",
                "token",
                "secret",
                "password",
            )
        )

    @staticmethod
    def _looks_document_parse(query: str) -> bool:
        """识别轻量文档解析意图。"""
        return any(
            keyword in query
            for keyword in (
                "解析文档",
                "文档解析",
                "提取字段",
                "读取 markdown",
                "读取 json",
                "读取 yaml",
                "markdown",
                "json",
                "yaml",
                "接口文档",
            )
        )

    @staticmethod
    def _looks_change_impact(query: str) -> bool:
        """识别接口、字段、错误码、签名规则和知识文档变更影响分析意图。"""
        return any(
            keyword in query
            for keyword in (
                "变更影响",
                "影响分析",
                "字段变更",
                "错误码变更",
                "签名规则变更",
                "接口变更",
                "影响哪些接口",
                "影响哪些渠道",
                "知识文档变更",
            )
        )

    @staticmethod
    def _is_follow_up(query: str) -> bool:
        """判断文本是否像追问。"""
        return any(marker in query for marker in FOLLOW_UP_MARKERS)

    @staticmethod
    def _has_troubleshooting_context(text: str) -> bool:
        """判断历史上下文是否足以把追问识别为问题排查。"""
        return any(keyword in text for keyword in ("E102", "requestId", "REQ_"))
