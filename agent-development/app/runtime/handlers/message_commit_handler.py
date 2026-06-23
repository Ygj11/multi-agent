from __future__ import annotations

"""Message commit handler for graph nodes."""

from typing import Any

from app.config.settings import get_settings
from app.session.message_store import MessageStore


class MessageCommitHandler:
    """Persist user and assistant messages."""

    def __init__(self, *, message_store: MessageStore | None = None) -> None:
        self.message_store = message_store

    async def save_user_message(self, state: dict[str, Any]) -> dict[str, Any]:
        if self.message_store is None:
            raise RuntimeError("message_store_not_configured")
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
        if self.message_store is None:
            raise RuntimeError("message_store_not_configured")
        subagent_result = state.get("subagent_result") if isinstance(state.get("subagent_result"), dict) else {}
        subagent_metadata = subagent_result.get("metadata") if isinstance(subagent_result.get("metadata"), dict) else {}
        metadata = {
            "request_id": state["request_id"],
            "trace_id": state["trace_id"],
            "original_query": state["original_query"],
            "rewritten_query": state.get("rewritten_query"),
            "intent": state.get("intent"),
            "sub_intent": state.get("sub_intent"),
            "entities": state.get("entities", {}),
            "need_clarification": state.get("need_clarification", False),
            "clarification_source": state.get("clarification_source"),
            "clarification_question": state.get("clarification_question") or subagent_metadata.get("clarification_question"),
            "missing_required_entities": state.get("missing_required_entities") or subagent_metadata.get("missing_required_entities") or [],
            "missing_tool_arguments": subagent_metadata.get("missing_tool_arguments") or [],
            "selected_agent": state.get("selected_agent"),
            "selected_skill_id": subagent_result.get("selected_skill_id"),
            "fallback_summary": {
                "query_rewrite": state.get("query_rewrite_fallback_reason"),
                "intent_recognition": state.get("intent_fallback_reason"),
                "agent_selection": state.get("agent_selection_fallback_reason"),
                "skill_selection": subagent_metadata.get("skill_selection_fallback_reason"),
            },
            "session_key": state["session_key"],
        }
        if get_settings().log_decision_trace_in_messages:
            metadata["decision_traces"] = {
                "query_rewrite": state.get("query_rewrite_decision_trace"),
                "intent_recognition": state.get("intent_decision_trace"),
                "agent_selection": state.get("agent_selection_decision_trace"),
                "skill_selection": subagent_metadata.get("skill_selection_decision_trace"),
            }
        await self.message_store.append(
            session_key=state["session_key"],
            role="assistant",
            content=state.get("answer", ""),
            metadata=metadata,
        )
        return {}
