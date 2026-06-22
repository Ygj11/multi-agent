from __future__ import annotations

"""Application configuration.

Configuration priority is:

1. OS environment variables
2. project-root `.env`
3. defaults in this module

`get_settings()` reads the environment when called so tests and local startup can
change configuration without reloading this module.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = PROJECT_ROOT / ".env"


def _as_bool(value: str | None, default: bool = False) -> bool:
    """Parse common boolean environment variable strings."""
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "on"}


def _as_tuple(value: str | None) -> tuple[str, ...]:
    """Parse a comma-separated environment variable into a tuple."""
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def _tool_mode(name: str, value: str | None, default: str = "mock") -> str:
    """Parse a tool implementation mode with a deliberately small vocabulary."""
    mode = (value or default).strip().lower()
    if mode not in {"mock", "real"}:
        raise ValueError(f"{name} must be one of: mock, real")
    return mode


def _choice(name: str, value: str | None, allowed: set[str], default: str) -> str:
    """Parse a string enum environment variable."""
    item = (value or default).strip().lower()
    if item not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"{name} must be one of: {allowed_text}")
    return item


def load_project_dotenv(dotenv_path: Path | None = None) -> None:
    """Load project .env without overriding existing OS environment variables."""
    load_dotenv(dotenv_path=dotenv_path or ENV_FILE, override=False)


@dataclass(frozen=True)
class Settings:
    """Runtime settings with safe local defaults."""

    project_root: Path = PROJECT_ROOT
    app_env: str = "local"

    # Security and auth
    enable_shell_exec: bool = False
    auth_mode: str = "dev_header"
    allow_request_body_identity_fallback: bool = True

    # LLM providers
    enable_real_llm: bool = False
    enable_opensdk_llm: bool = False
    internal_llm_api_url: str | None = None
    internal_llm_model: str = "1501"
    internal_llm_timeout: float = 60.0
    internal_llm_max_tokens: int = 8192
    internal_llm_temperature: float = 0.1
    openai_api_key: str | None = None
    openai_base_url: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout: float = 30.0

    # Scene-specific model overrides
    query_rewrite_model: str | None = None
    intent_recognition_model: str | None = None
    agent_selection_model: str | None = None
    subagent_reasoning_model: str | None = None
    final_compliance_model: str | None = None
    summary_model: str | None = None

    # Knowledge and MCP
    enable_mcp_client: bool = True
    mcp_servers_json: str | None = None
    enable_knowledge_api: bool = False
    knowledge_api_url: str | None = None
    knowledge_api_timeout: float = 10.0

    # Agent tool implementation modes
    pos_tool_mode: str = "mock"
    troubleshooting_tool_mode: str = "mock"

    # POS real-time API
    pos_api_base_url: str = "http://ehis-epos-gateway.paic.com.cn"
    pos_api_timeout: float = 10.0

    # Troubleshooting real API
    troubleshooting_api_base_url: str | None = None
    troubleshooting_api_timeout: float = 10.0

    # Storage and checkpoints
    sqlite_db_path: str = ".data/agent_mvp.sqlite3"
    checkpoint_backend: str = "memory"
    checkpoint_db_path: str | None = None

    # Approval
    max_approval_chain_depth: int = 3
    max_write_tools_per_request: int = 3
    approval_system_url: str = "http://mock-approval-system.local/api/approval/requests"
    approval_callback_url: str = "http://localhost:8000/api/approval/callback"
    approval_system_timeout: float = 30.0
    enable_external_approval: bool = True

    # HTTP tools
    enable_http_tools: bool = False
    allowed_http_tool_hosts: tuple[str, ...] = ()
    http_tool_timeout: float = 5.0

    # Tool loop safety
    tool_loop_max_iterations: int = 10
    tool_loop_max_consecutive_failures: int = 3
    tool_loop_max_same_tool_failures: int = 2
    tool_loop_max_duplicate_calls: int = 2
    tool_write_idempotency_enabled: bool = True

    # Skill selection
    enable_skill_llm_rerank: bool = True
    skill_llm_rerank_top_k: int = 3
    skill_llm_rerank_min_margin: float = 3.0
    no_skill_policy: str = "clarify"

    # Intent taxonomy
    strict_taxonomy_route_coverage: bool = True

    # Runtime observability
    log_graph_node_events: bool = False
    log_disabled_service_events: bool = False
    log_decision_trace_in_messages: bool = False


def get_settings(dotenv_path: Path | None = None) -> Settings:
    """Create Settings from the current environment and optional .env file."""
    load_project_dotenv(dotenv_path)
    return Settings(
        project_root=PROJECT_ROOT,
        app_env=_choice("APP_ENV", os.getenv("APP_ENV"), {"local", "test", "staging", "prod"}, "local"),
        enable_shell_exec=_as_bool(os.getenv("ENABLE_SHELL_EXEC"), False),
        auth_mode=os.getenv("AUTH_MODE", "dev_header"),
        allow_request_body_identity_fallback=_as_bool(os.getenv("ALLOW_REQUEST_BODY_IDENTITY_FALLBACK"), True),
        enable_real_llm=_as_bool(os.getenv("ENABLE_REAL_LLM"), False),
        enable_opensdk_llm=_as_bool(os.getenv("ENABLE_OPENSDK_LLM"), False),
        internal_llm_api_url=os.getenv("INTERNAL_LLM_API_URL") or None,
        internal_llm_model=os.getenv("INTERNAL_LLM_MODEL", "1501"),
        internal_llm_timeout=float(os.getenv("INTERNAL_LLM_TIMEOUT", "60")),
        internal_llm_max_tokens=int(os.getenv("INTERNAL_LLM_MAX_TOKENS", "8192")),
        internal_llm_temperature=float(os.getenv("INTERNAL_LLM_TEMPERATURE", "0.1")),
        openai_api_key=os.getenv("OPENAI_API_KEY") or None,
        openai_base_url=os.getenv("OPENAI_BASE_URL") or None,
        openai_model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
        openai_timeout=float(os.getenv("OPENAI_TIMEOUT", "30")),
        query_rewrite_model=os.getenv("QUERY_REWRITE_MODEL") or None,
        intent_recognition_model=os.getenv("INTENT_RECOGNITION_MODEL") or None,
        agent_selection_model=os.getenv("AGENT_SELECTION_MODEL") or None,
        subagent_reasoning_model=os.getenv("SUBAGENT_REASONING_MODEL") or None,
        final_compliance_model=os.getenv("FINAL_COMPLIANCE_MODEL") or None,
        summary_model=os.getenv("SUMMARY_MODEL") or None,
        enable_mcp_client=_as_bool(os.getenv("ENABLE_MCP_CLIENT"), True),
        mcp_servers_json=os.getenv("MCP_SERVERS_JSON") or os.getenv("MCP_SERVERS") or None,
        enable_knowledge_api=_as_bool(os.getenv("ENABLE_KNOWLEDGE_API"), False),
        knowledge_api_url=os.getenv("KNOWLEDGE_API_URL") or None,
        knowledge_api_timeout=float(os.getenv("KNOWLEDGE_API_TIMEOUT", "10")),
        pos_tool_mode=_tool_mode("POS_TOOL_MODE", os.getenv("POS_TOOL_MODE"), "mock"),
        troubleshooting_tool_mode=_tool_mode(
            "TROUBLESHOOTING_TOOL_MODE",
            os.getenv("TROUBLESHOOTING_TOOL_MODE"),
            "mock",
        ),
        pos_api_base_url=os.getenv("POS_API_BASE_URL", "http://ehis-epos-gateway.paic.com.cn"),
        pos_api_timeout=float(os.getenv("POS_API_TIMEOUT", "10")),
        troubleshooting_api_base_url=os.getenv("TROUBLESHOOTING_API_BASE_URL") or None,
        troubleshooting_api_timeout=float(os.getenv("TROUBLESHOOTING_API_TIMEOUT", "10")),
        sqlite_db_path=os.getenv("SQLITE_DB_PATH", ".data/agent_mvp.sqlite3"),
        checkpoint_backend=os.getenv("CHECKPOINT_BACKEND", "memory"),
        checkpoint_db_path=os.getenv("CHECKPOINT_DB_PATH") or None,
        max_approval_chain_depth=int(os.getenv("MAX_APPROVAL_CHAIN_DEPTH", "3")),
        max_write_tools_per_request=int(os.getenv("MAX_WRITE_TOOLS_PER_REQUEST", "3")),
        approval_system_url=os.getenv(
            "APPROVAL_SYSTEM_URL",
            "http://mock-approval-system.local/api/approval/requests",
        ),
        approval_callback_url=os.getenv(
            "APPROVAL_CALLBACK_URL",
            "http://localhost:8000/api/approval/callback",
        ),
        approval_system_timeout=float(os.getenv("APPROVAL_SYSTEM_TIMEOUT", "30")),
        enable_external_approval=_as_bool(os.getenv("ENABLE_EXTERNAL_APPROVAL"), True),
        enable_http_tools=_as_bool(os.getenv("ENABLE_HTTP_TOOLS"), False),
        allowed_http_tool_hosts=_as_tuple(os.getenv("ALLOWED_HTTP_TOOL_HOSTS")),
        http_tool_timeout=float(os.getenv("HTTP_TOOL_TIMEOUT", "5")),
        tool_loop_max_iterations=int(os.getenv("TOOL_LOOP_MAX_ITERATIONS", "10")),
        tool_loop_max_consecutive_failures=int(os.getenv("TOOL_LOOP_MAX_CONSECUTIVE_FAILURES", "3")),
        tool_loop_max_same_tool_failures=int(os.getenv("TOOL_LOOP_MAX_SAME_TOOL_FAILURES", "2")),
        tool_loop_max_duplicate_calls=int(os.getenv("TOOL_LOOP_MAX_DUPLICATE_CALLS", "2")),
        tool_write_idempotency_enabled=_as_bool(os.getenv("TOOL_WRITE_IDEMPOTENCY_ENABLED"), True),
        enable_skill_llm_rerank=_as_bool(os.getenv("ENABLE_SKILL_LLM_RERANK"), True),
        skill_llm_rerank_top_k=int(os.getenv("SKILL_LLM_RERANK_TOP_K", "3")),
        skill_llm_rerank_min_margin=float(os.getenv("SKILL_LLM_RERANK_MIN_MARGIN", "3")),
        no_skill_policy=_choice(
            "NO_SKILL_POLICY",
            os.getenv("NO_SKILL_POLICY"),
            {"clarify", "answer_no_skill", "generic_dev_only"},
            "clarify",
        ),
        strict_taxonomy_route_coverage=_as_bool(os.getenv("STRICT_TAXONOMY_ROUTE_COVERAGE"), True),
        log_graph_node_events=_as_bool(
            os.getenv("LOG_GRAPH_NODE_EVENTS"),
            _choice("APP_ENV", os.getenv("APP_ENV"), {"local", "test", "staging", "prod"}, "local") == "local",
        ),
        log_disabled_service_events=_as_bool(os.getenv("LOG_DISABLED_SERVICE_EVENTS"), False),
        log_decision_trace_in_messages=_as_bool(os.getenv("LOG_DECISION_TRACE_IN_MESSAGES"), False),
    )
