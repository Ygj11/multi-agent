from __future__ import annotations

"""SQLite 短期记忆压缩器。"""

import re
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings
from app.observability.logger import log_event, preview_text
from app.storage.sqlite import SQLiteDatabase


class ShortTermMemoryManager:
    """按 session_key 将 session summary 持久化到 SQLite。"""

    def __init__(self, db: SQLiteDatabase | None = None) -> None:
        """注入 SQLiteDatabase；未注入时使用默认 SQLITE_DB_PATH。"""
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)

    async def get_summary(self, session_key: str) -> str | None:
        """从 short_term_memory 表读取指定 session 的摘要。"""

        def read(conn):
            row = conn.execute(
                "SELECT summary FROM short_term_memory WHERE session_key = ?",
                (session_key,),
            ).fetchone()
            return row["summary"] if row else None

        return await self.db.run(read)

    async def compress_after_turn(
        self,
        session_key: str,
        original_query: str,
        rewritten_query: str,
        intent: str,
        answer: str,
        subagent_result: dict[str, Any] | None = None,
    ) -> str:
        """在每轮回答后生成规则摘要，并 upsert 到 SQLite。"""
        request_id = self._find_request_id(" ".join([original_query, rewritten_query, answer]))
        error_code = "E102" if "E102" in " ".join([original_query, rewritten_query, answer]) else None
        interface_name = "submitProposal" if "submitProposal" in answer else "健康险个险接口"

        if request_id and error_code:
            summary = (
                f"上一轮讨论 requestId={request_id} 的 {interface_name} {error_code} 问题，"
                "初步结论为签名校验失败，需要检查 timestamp 是否参与签名、密钥版本和字段排序。"
            )
        elif intent == "troubleshooting":
            summary = "上一轮是健康险个险接口问题排查，重点关注错误码、requestId 和签名校验失败原因。"
        else:
            summary = f"上一轮意图为 {intent}，用户问题是：{original_query}"

        updated_at = datetime.now(UTC).isoformat()

        def write(conn):
            conn.execute(
                """
                INSERT INTO short_term_memory(session_key, summary, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_key) DO UPDATE SET
                    summary = excluded.summary,
                    updated_at = excluded.updated_at
                """,
                (session_key, summary, updated_at),
            )

        await self.db.run(write)
        log_event(
            "short_memory_compressed",
            session_key=session_key,
            node="short_term_memory_manager",
            message="Short memory compressed and persisted",
            data={"summary_preview": preview_text(summary), "intent": intent},
        )
        return summary

    async def clear(self) -> None:
        """清空 short_term_memory 表，主要供测试使用。"""

        def delete(conn):
            conn.execute("DELETE FROM short_term_memory")

        await self.db.run(delete)

    @staticmethod
    def _find_request_id(text: str) -> str | None:
        """从文本中提取 REQ_xxx 格式的 requestId。"""
        match = re.search(r"\bREQ_\d+\b", text)
        return match.group(0) if match else None
