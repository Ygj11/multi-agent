from __future__ import annotations

"""Built-in local tools."""

import re
from typing import Any

from app.knowledge.service import KnowledgeService


def build_get_knowledge_tool(knowledge_service: KnowledgeService):
    """Build the get_knowledge tool from a KnowledgeService implementation."""

    async def get_knowledge_tool(query: str, top_k: int = 3, **kwargs: Any) -> str:
        chunks = await knowledge_service.search(query=query, top_k=top_k)
        if not chunks:
            disabled_reason = getattr(knowledge_service, "disabled_reason", None)
            if disabled_reason:
                return str(disabled_reason)
            return "No matching knowledge chunks found."
        return "\n".join(chunk.content for chunk in chunks)

    return get_knowledge_tool


async def query_internal_log(request_id: str | None = None, query: str | None = None, **kwargs: Any) -> dict[str, Any]:
    """Mock internal log query used by the troubleshooting MVP tool."""
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
    return {"found": False, "message": "No mock internal log found for this requestId."}


def _extract_request_id(text: str) -> str | None:
    match = re.search(r"\bREQ_\d+\b", text)
    return match.group(0) if match else None
