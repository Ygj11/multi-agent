from __future__ import annotations

"""Message and short-memory commit handlers for graph nodes."""

from typing import Any

from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.session.message_store import MessageStore


class MessageCommitHandler:
    """Persist user/assistant messages and roll short memory."""

    def __init__(self, *, message_store: MessageStore, short_memory: ShortTermMemoryManager) -> None:
        self.message_store = message_store
        self.short_memory = short_memory

    async def save_user_message(self, state: dict[str, Any]) -> dict[str, Any]:
        await self.message_store.append(
            session_key=state["session_key"],
            role="user",
            content=state["original_query"],
            metadata={
                "request_id": state["request_id"],
                "trace_id": state["trace_id"],
                "original_query": state["original_query"],
                "session_key": state["session_key"],
            },
        )
        return {}

    async def save_assistant_message(self, state: dict[str, Any]) -> dict[str, Any]:
        await self.message_store.append(
            session_key=state["session_key"],
            role="assistant",
            content=state.get("answer", ""),
            metadata={
                "request_id": state["request_id"],
                "trace_id": state["trace_id"],
                "original_query": state["original_query"],
                "rewritten_query": state.get("rewritten_query"),
                "intent": state.get("intent"),
                "sub_intent": state.get("sub_intent"),
                "entities": state.get("entities", {}),
                "need_clarification": state.get("need_clarification", False),
                "clarification_source": state.get("clarification_source"),
                "selected_agent": state.get("selected_agent"),
                "session_key": state["session_key"],
            },
        )
        return {}

    async def compress_short_memory(self, state: dict[str, Any]) -> dict[str, Any]:
        summary = await self.short_memory.compress_after_turn(
            session_key=state["session_key"],
            original_query=state["original_query"],
            rewritten_query=state.get("rewritten_query", state["original_query"]),
            intent=state.get("intent", "unknown"),
            answer=state.get("answer", ""),
            subagent_result=state.get("subagent_result"),
        )
        return {"short_summary": summary}
