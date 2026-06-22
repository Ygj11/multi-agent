from __future__ import annotations

"""Short-term memory commit handler for graph nodes."""

from typing import Any

from app.memory.short_term_memory_manager import ShortTermMemoryManager


class MemoryCommitHandler:
    """Roll short memory after the assistant answer has been produced."""

    def __init__(self, *, short_memory: ShortTermMemoryManager) -> None:
        self.short_memory = short_memory

    async def compress_short_memory(self, state: dict[str, Any]) -> dict[str, Any]:
        summary = await self.short_memory.compress_after_turn(
            session_key=state["session_key"],
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            answer=state.get("answer", ""),
            subagent_result=state.get("subagent_result"),
            request_id=state.get("request_id"),
            trace_id=state.get("trace_id"),
        )
        return {"short_summary": summary}
