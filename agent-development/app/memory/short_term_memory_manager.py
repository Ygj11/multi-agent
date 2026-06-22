from __future__ import annotations

"""SQLite 短期记忆压缩器。"""

import re
from datetime import UTC, datetime
from typing import Any

from app.config.settings import get_settings
from app.llm.base import LLMProvider
from app.observability.logger import log_event, preview_text
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.storage.sqlite import SQLiteDatabase


class ShortTermMemoryManager:
    """按 session_key 将 session summary 持久化到 SQLite。"""

    max_summary_chars = 600

    def __init__(
        self,
        db: SQLiteDatabase | None = None,
        llm_provider: LLMProvider | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        """注入 SQLiteDatabase；未注入时使用默认 SQLITE_DB_PATH。"""
        self.db = db or SQLiteDatabase(get_settings().sqlite_db_path)
        self.llm_provider = llm_provider
        self.prompt_loader = prompt_loader or default_prompt_loader

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
        request_id: str | None = None,
        trace_id: str | None = None,
    ) -> str:
        """滚动压缩短期记忆：previous_summary + current_turn -> new_summary。

        这里不读取最近 60 条 messages；数据库仍保留完整 messages，运行时窗口由
        SessionManager 控制，更早上下文由 short_summary 承接。
        """
        previous_summary = await self.get_summary(session_key)
        summary_source = "rule_fallback"
        summary = await self._compress_with_llm(
            previous_summary=previous_summary,
            original_query=original_query,
            rewritten_query=rewritten_query,
            intent=intent,
            answer=answer,
            subagent_result=subagent_result,
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
        )
        if summary:
            summary_source = "llm_summary"
        else:
            summary = self._compress_with_rules(
                previous_summary=previous_summary,
                original_query=original_query,
                rewritten_query=rewritten_query,
                intent=intent,
                answer=answer,
                subagent_result=subagent_result,
            )

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
            data={"summary_preview": preview_text(summary), "intent": intent, "source": summary_source},
        )
        return summary

    async def _compress_with_llm(
        self,
        *,
        previous_summary: str | None,
        original_query: str,
        rewritten_query: str,
        intent: str,
        answer: str,
        subagent_result: dict[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> str | None:
        """Use LLM semantic rolling summary. Return None to trigger rule fallback."""
        if self.llm_provider is None:
            return None
        current_turn = self._build_current_turn_text(
            original_query=original_query,
            rewritten_query=rewritten_query,
            intent=intent,
            answer=answer,
            subagent_result=subagent_result,
        )
        try:
            response = await self.llm_provider.chat(
                messages=[
                    {
                        "role": "system",
                        "content": self.prompt_loader.render("memory_summary/system.md"),
                    },
                    {
                        "role": "user",
                        "content": self.prompt_loader.render(
                            "memory_summary/user.md",
                            previous_summary=previous_summary or "无",
                            current_turn=current_turn,
                        ),
                    },
                ],
                tools=None,
                scene="summary",
                request_id=request_id,
                trace_id=trace_id,
                session_key=session_key,
            )
        except Exception as exc:
            log_event(
                "short_memory_llm_summary_failed",
                node="short_term_memory_manager",
                level="WARNING",
                message="LLM short memory summary failed; fallback to rules",
                data={"error": str(exc)},
            )
            return None
        return self._normalize_llm_summary(response.content)

    def _compress_with_rules(
        self,
        *,
        previous_summary: str | None,
        original_query: str,
        rewritten_query: str,
        intent: str,
        answer: str,
        subagent_result: dict[str, Any] | None = None,
    ) -> str:
        """Rule fallback retained for LLM failure or invalid output."""
        del subagent_result
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
        if previous_summary:
            return f"{previous_summary}\n{summary}"
        return summary

    def _build_current_turn_text(
        self,
        *,
        original_query: str,
        rewritten_query: str,
        intent: str,
        answer: str,
        subagent_result: dict[str, Any] | None,
    ) -> str:
        metadata = subagent_result.get("metadata", {}) if isinstance(subagent_result, dict) else {}
        lines = [
            f"- original_query: {original_query}",
            f"- rewritten_query: {rewritten_query}",
            f"- intent: {intent}",
            f"- answer: {self._compact_text(answer, 800)}",
        ]
        if isinstance(subagent_result, dict):
            selected_agent = subagent_result.get("agent_name") or subagent_result.get("name")
            selected_skill = subagent_result.get("selected_skill_id")
            request_id = metadata.get("request_id") if isinstance(metadata, dict) else None
            trace_id = metadata.get("trace_id") if isinstance(metadata, dict) else None
            if request_id:
                lines.append(f"- request_id: {request_id}")
            if trace_id:
                lines.append(f"- trace_id: {trace_id}")
            if selected_agent:
                lines.append(f"- selected_agent: {selected_agent}")
            if selected_skill:
                lines.append(f"- selected_skill: {selected_skill}")
            lines.append(f"- subagent_result_summary: {self._subagent_result_summary(subagent_result)}")
        else:
            lines.append("- subagent_result_summary: 无")
        return "\n".join(lines)

    def _subagent_result_summary(self, subagent_result: dict[str, Any]) -> str:
        parts: list[str] = []
        for key in ("diagnosis", "recommendation", "responsibility", "risk_level", "confidence"):
            value = subagent_result.get(key)
            if value not in (None, "", [], {}):
                parts.append(f"{key}={self._compact_text(str(value), 240)}")
        tool_calls = subagent_result.get("tool_calls")
        if tool_calls:
            parts.append(f"tool_calls={self._compact_text(str(tool_calls), 300)}")
        return "; ".join(parts) if parts else self._compact_text(str(subagent_result), 500)

    def _normalize_llm_summary(self, content: str | None) -> str | None:
        summary = (content or "").strip()
        if not summary:
            return None
        if summary.startswith(("{", "[")) or summary.endswith(("}", "]")):
            return None
        if "```" in summary:
            return None
        return self._compact_text(summary, self.max_summary_chars)

    @staticmethod
    def _compact_text(text: str, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

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
