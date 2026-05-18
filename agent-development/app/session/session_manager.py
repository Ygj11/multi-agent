from __future__ import annotations

"""SessionManager 聚合会话消息和短期记忆。"""

from typing import Any

from app.memory.short_term_memory_manager import ShortTermMemoryManager
from app.observability.logger import log_event
from app.session.message_store import MessageStore


class SessionManager:
    """运行时会话入口，从 SQLite 恢复消息和短期摘要。"""

    def __init__(self, message_store: MessageStore, short_memory: ShortTermMemoryManager) -> None:
        """注入消息存储和短期记忆组件。"""
        self.message_store = message_store
        self.short_memory = short_memory

    async def load_session(self, session_key: str, recent_limit: int = 60) -> dict[str, Any]:
        """加载主干流程需要的最近 30 轮上下文。

        一轮通常包含 user + assistant 两条消息，所以默认读取最近 60 条。
        """
        recent_messages = await self.message_store.list_by_session(session_key, limit=recent_limit)
        short_summary = await self.short_memory.get_summary(session_key)
        log_event(
            "memory_context_loaded",
            session_key=session_key,
            node="session_manager",
            message="Memory context loaded",
            data={"recent_message_count": len(recent_messages), "has_short_summary": bool(short_summary)},
        )
        return {
            "session_key": session_key,
            "recent_messages": recent_messages,
            "short_summary": short_summary,
        }
