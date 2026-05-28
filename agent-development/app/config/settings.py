from __future__ import annotations

"""应用配置。

本模块只读取环境变量并提供不可变 Settings 对象，避免业务代码散落读取
OPENAI、shell_exec 等开关。
"""

import os
from dataclasses import dataclass
from pathlib import Path


def _as_bool(value: str | None, default: bool = False) -> bool:
    """将常见字符串环境变量解析为 bool。"""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_tuple(value: str | None) -> tuple[str, ...]:
    """将逗号分隔环境变量解析成 tuple。"""
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


@dataclass(frozen=True)
class Settings:
    """运行时配置。

    第一阶段默认关闭真实 LLM 和 shell_exec，保证本地测试稳定且安全。
    """

    project_root: Path = Path(__file__).resolve().parents[2]
    enable_shell_exec: bool = _as_bool(os.getenv("ENABLE_SHELL_EXEC"), False)
    enable_real_llm: bool = _as_bool(os.getenv("ENABLE_REAL_LLM"), False)
    enable_opensdk_llm: bool = _as_bool(os.getenv("ENABLE_OPENSDK_LLM"), False)
    enable_mcp_client: bool = _as_bool(os.getenv("ENABLE_MCP_CLIENT"), True)
    enable_knowledge_api: bool = _as_bool(os.getenv("ENABLE_KNOWLEDGE_API"), False)
    knowledge_api_url: str | None = os.getenv("KNOWLEDGE_API_URL")
    knowledge_api_timeout: float = float(os.getenv("KNOWLEDGE_API_TIMEOUT", "10"))
    mcp_servers_json: str | None = os.getenv("MCP_SERVERS_JSON") or os.getenv("MCP_SERVERS")
    internal_llm_api_url: str | None = os.getenv("INTERNAL_LLM_API_URL")
    internal_llm_model: str = os.getenv("INTERNAL_LLM_MODEL", "1501")
    internal_llm_timeout: float = float(os.getenv("INTERNAL_LLM_TIMEOUT", "60"))
    internal_llm_max_tokens: int = int(os.getenv("INTERNAL_LLM_MAX_TOKENS", "8192"))
    internal_llm_temperature: float = float(os.getenv("INTERNAL_LLM_TEMPERATURE", "0.1"))
    query_rewrite_model: str | None = os.getenv("QUERY_REWRITE_MODEL")
    intent_recognition_model: str | None = os.getenv("INTENT_RECOGNITION_MODEL")
    agent_selection_model: str | None = os.getenv("AGENT_SELECTION_MODEL")
    subagent_reasoning_model: str | None = os.getenv("SUBAGENT_REASONING_MODEL")
    final_compliance_model: str | None = os.getenv("FINAL_COMPLIANCE_MODEL")
    summary_model: str | None = os.getenv("SUMMARY_MODEL")
    enable_skill_llm_rerank: bool = _as_bool(os.getenv("ENABLE_SKILL_LLM_RERANK"), True)
    skill_llm_rerank_top_k: int = int(os.getenv("SKILL_LLM_RERANK_TOP_K", "3"))
    skill_llm_rerank_min_margin: float = float(os.getenv("SKILL_LLM_RERANK_MIN_MARGIN", "3"))
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    openai_base_url: str | None = os.getenv("OPENAI_BASE_URL")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
    openai_timeout: float = float(os.getenv("OPENAI_TIMEOUT", "30"))
    sqlite_db_path: str = os.getenv("SQLITE_DB_PATH", ".data/agent_mvp.sqlite3")
    enable_http_tools: bool = _as_bool(os.getenv("ENABLE_HTTP_TOOLS"), False)
    allowed_http_tool_hosts: tuple[str, ...] = _as_tuple(os.getenv("ALLOWED_HTTP_TOOL_HOSTS"))
    http_tool_timeout: float = float(os.getenv("HTTP_TOOL_TIMEOUT", "5"))
    approval_system_url: str = os.getenv(
        "APPROVAL_SYSTEM_URL",
        "http://mock-approval-system.local/api/approval/requests",
    )
    approval_callback_url: str = os.getenv(
        "APPROVAL_CALLBACK_URL",
        "http://localhost:8000/api/approval/callback",
    )
    approval_system_timeout: float = float(os.getenv("APPROVAL_SYSTEM_TIMEOUT", "30"))
    enable_external_approval: bool = _as_bool(os.getenv("ENABLE_EXTERNAL_APPROVAL"), True)


def get_settings() -> Settings:
    """创建 Settings 实例。

    保持为函数而不是全局单例，便于测试中构造不同环境配置。
    """
    return Settings()
