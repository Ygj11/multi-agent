from __future__ import annotations

"""规则版 query 改写节点。"""

import re
from typing import Any

from app.llm.base import LLMProvider
from app.schemas.query_rewrite import QueryRewriteResult


FOLLOW_UP_MARKERS = ("这个", "那个", "一般是谁", "谁的问题", "继续", "刚才")


class QueryRewriteNode:
    """把用户原始输入改写为更适合识别意图和调用工具的标准查询。"""

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def rewrite(
        self,
        original_query: str,
        recent_messages: list[dict[str, Any]] | None = None,
        short_summary: str | None = None,
    ) -> QueryRewriteResult:
        """执行 TASK1.md 指定的规则改写。"""
        request_id = self._find_request_id(original_query)
        if request_id and "E102" in original_query:
            return QueryRewriteResult(
                original_query=original_query,
                rewritten_query=f"排查 requestId={request_id} 的健康险个险接口 E102 错误原因",
            )

        context_text = self._context_text(recent_messages or [], short_summary)
        if self._is_follow_up(original_query) and self._has_e102_context(context_text):
            return QueryRewriteResult(
                original_query=original_query,
                rewritten_query="继续排查上一轮 requestId 的 E102 签名校验失败问题，并判断问题归属",
            )

        return QueryRewriteResult(original_query=original_query, rewritten_query=original_query)

    @staticmethod
    def _find_request_id(text: str) -> str | None:
        """提取 REQ_xxx 格式的 requestId。"""
        match = re.search(r"\bREQ_\d+\b", text)
        return match.group(0) if match else None

    @staticmethod
    def _is_follow_up(text: str) -> bool:
        """判断用户输入是否像多轮追问。"""
        return any(marker in text for marker in FOLLOW_UP_MARKERS)

    @staticmethod
    def _has_e102_context(text: str) -> bool:
        """判断上下文中是否存在 E102 或 requestId 线索。"""
        return "E102" in text or "requestId" in text or "REQ_" in text

    @staticmethod
    def _context_text(recent_messages: list[dict[str, Any]], short_summary: str | None) -> str:
        """把 recent messages 和 short summary 合并成规则判断文本。"""
        message_text = " ".join(str(message.get("content", "")) for message in recent_messages)
        return " ".join([message_text, short_summary or ""])
