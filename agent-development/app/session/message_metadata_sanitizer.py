from __future__ import annotations

"""Sanitize persisted message metadata before it enters runtime LLM context."""

from typing import Any


RUNTIME_METADATA_ALLOWLIST = {
    "original_query",
    "rewritten_query",
    "pending_task_query",
    "intent",
    "sub_intent",
    "entities",
    "need_clarification",
    "clarification_source",
    "clarification_question",
    "missing_required_entities",
    "missing_tool_arguments",
    "selected_agent",
    "selected_skill_id",
}


def sanitize_message_for_runtime(message: dict[str, Any]) -> dict[str, Any]:
    """Return a copy with only metadata required by runtime context recovery."""
    sanitized = dict(message)
    metadata = message.get("metadata") if isinstance(message.get("metadata"), dict) else {}
    sanitized["metadata"] = {
        key: value
        for key, value in metadata.items()
        if key in RUNTIME_METADATA_ALLOWLIST and value not in (None, "", [])
    }
    return sanitized


def sanitize_messages_for_runtime(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Sanitize a message list loaded from persistent storage for graph execution."""
    return [sanitize_message_for_runtime(message) for message in messages]
