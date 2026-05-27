from __future__ import annotations

"""Public tools shared by sub agents."""

from datetime import UTC, datetime
from typing import Any

from app.knowledge.service import KnowledgeService
from app.tools.builtin_tools import build_get_knowledge_tool


def build_rag_search_tool(knowledge_service: KnowledgeService):
    """Build the public RAG search tool."""

    async def rag_search_tool(query: str, top_k: int = 3, namespace: str | None = None, **kwargs: Any) -> str:
        chunks = await knowledge_service.search(query=query, top_k=top_k)
        if not chunks:
            disabled_reason = getattr(knowledge_service, "disabled_reason", None)
            if disabled_reason:
                return str(disabled_reason)
            return "No matching knowledge chunks found."
        return "\n".join(chunk.content for chunk in chunks)

    return rag_search_tool


async def calculator_tool(expression: str, **kwargs: Any) -> dict[str, Any]:
    """Very small calculator for arithmetic expressions."""
    allowed = set("0123456789+-*/(). %")
    if not expression or any(ch not in allowed for ch in expression):
        return {"success": False, "error": "unsupported_expression"}
    return {"success": True, "result": eval(expression, {"__builtins__": {}}, {})}


async def current_time_tool(**kwargs: Any) -> dict[str, Any]:
    """Return current UTC time."""
    return {"utc": datetime.now(UTC).isoformat()}


def register_public_tools(registry, knowledge_service: KnowledgeService) -> None:
    """Register public tools on the provided registry."""
    registry.register_public("rag_search_tool", build_rag_search_tool(knowledge_service), "Search task knowledge.")
    registry.register_public("get_knowledge", build_get_knowledge_tool(knowledge_service), "Legacy knowledge search alias.")
    registry.register_public("calculator_tool", calculator_tool, "Calculate simple arithmetic expressions.")
    registry.register_public("current_time_tool", current_time_tool, "Return current time.")
