from __future__ import annotations

"""MVP 阶段内置工具。"""

import re
from typing import Any

from app.knowledge.in_memory_service import InMemoryKnowledgeService
from app.knowledge.service import KnowledgeService


def build_get_knowledge_tool(knowledge_service: KnowledgeService):
    """构造调用 KnowledgeService 的 get_knowledge tool。"""

    async def get_knowledge_tool(query: str, top_k: int = 3, **kwargs: Any) -> str:
        """通过 KnowledgeService 检索知识，并返回轻量文本。"""
        chunks = await knowledge_service.search(query=query, top_k=top_k)
        if not chunks:
            return "当前知识库未命中明确知识，建议补充错误码、接口名或 requestId。"
        return "\n".join(chunk.content for chunk in chunks)

    return get_knowledge_tool


_default_knowledge_service = InMemoryKnowledgeService()
get_knowledge = build_get_knowledge_tool(_default_knowledge_service)


async def query_internal_log(request_id: str | None = None, query: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """模拟内部日志查询，用固定数据支撑问题排查 Agent。"""
    resolved_request_id = request_id or _extract_request_id(query or "")
    mock_logs: dict[str, dict[str, Any]] = {
        "REQ_001": {
            "found": True,
            "request_id": "REQ_001",
            "channel": "XX_CHANNEL",
            "product_code": "ESHENGBAO",
            "interface_name": "submitProposal",
            "error_code": "E102",
            "error_message": "signature verification failed",
            "server_sign": "B82D****",
            "partner_sign": "A9F3****",
            "signature_rule_version": "v2",
            "suspected_reason": "partner signature does not include timestamp",
        },
        "REQ_002": {
            "found": True,
            "request_id": "REQ_002",
            "channel": "XX_CHANNEL",
            "product_code": "ESHENGBAO",
            "interface_name": "submitProposal",
            "error_code": "E102",
            "error_message": "signature verification failed",
            "server_sign": "C72E****",
            "partner_sign": "C72E****",
            "signature_rule_version": "v2",
            "suspected_reason": "timestamp expired",
        },
    }
    if resolved_request_id in mock_logs:
        return mock_logs[resolved_request_id]
    return {"found": False, "message": "未查询到该 requestId 的模拟日志"}


def _extract_request_id(text: str) -> str | None:
    """从 query 中提取 REQ_xxx 格式 requestId。"""
    match = re.search(r"\bREQ_\d+\b", text)
    return match.group(0) if match else None
