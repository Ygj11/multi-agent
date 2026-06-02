from __future__ import annotations

"""Clarification response construction for graph nodes."""

from typing import Any


class ClarificationHandler:
    """Build user-facing clarification answers without dispatching subagents."""

    def build_answer(self, state: dict[str, Any]) -> dict[str, Any]:
        question = state.get("clarification_question") or "请补充必要信息后我再继续处理。"
        return {
            "answer": question,
            "approval_required": False,
        }
