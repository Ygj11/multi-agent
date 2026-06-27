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
from typing import Literal

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
class ConfigIssue:
    """配置组合校验结果。

    单个环境变量是否合法由解析函数负责；这里描述“多个配置组合后是否安全、
    是否完整”。例如 ENABLE_OPENSDK_LLM=true 只是选择 OpenSDK Provider，
    还必须配合 OPENAI_API_KEY 才能真正工作。
    """

    level: Literal["error", "warning"]
    code: str
    variables: tuple[str, ...]
    message: str


@dataclass(frozen=True)
class ConfigSwitch:
    """运行时开关的有效语义。

    这个对象不是新的配置来源，只是把多个底层 env 组合成一个可读的“业务开关”，
    方便测试、启动日志或后续配置页面展示。
    """

    name: str
    enabled: bool
    variables: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class Settings:
    """Runtime settings with safe local defaults."""
    # 配置优先级：系统环境变量 > 项目 .env > Settings 默认值。
    # 生产建议组合：APP_ENV=prod、AUTH_MODE=required、
    # ALLOW_REQUEST_BODY_IDENTITY_FALLBACK=false，避免请求体自证身份。
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
    task_completion_model: str | None = None
    final_compliance_model: str | None = None
    summary_model: str | None = None

    # Knowledge and MCP
    enable_mcp_client: bool = True
    mcp_servers_json: str | None = None
    unknown_mcp_tool_policy: str = "allow"
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

    # Session concurrency
    enable_session_execution_lock: bool = True
    session_lock_timeout_seconds: float = 60.0

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

    # Task completion verify-repair loop
    enable_task_completion_verify: bool = True
    task_completion_max_repair_rounds: int = 2
    task_completion_min_verifier_confidence: float = 0.55
    task_completion_enable_llm: bool = False
    task_completion_enable_state_probes: bool = True
    task_completion_fail_closed: bool = True

    # Runtime observability
    log_graph_node_events: bool = False
    log_disabled_service_events: bool = False
    log_decision_trace_in_messages: bool = False

    @property
    def is_prod(self) -> bool:
        """是否生产环境；生产环境会启用更严格的组合校验。"""
        return self.app_env == "prod"

    @property
    def llm_provider_mode(self) -> str:
        """当前选择的 LLM Provider。

        ENABLE_OPENSDK_LLM=true 时使用 OpenAI-compatible Provider；否则使用
        InternalLLMProvider。ENABLE_REAL_LLM 不是 Provider 选择器，它表示“必须
        有真实 LLM 上游”，用于组合校验和部分默认值。
        """
        return "opensdk" if self.enable_opensdk_llm else "internal"

    @property
    def internal_llm_configured(self) -> bool:
        """InternalLLMProvider 是否配置了真实 HTTP base_url。"""
        return bool(self.internal_llm_api_url)

    @property
    def opensdk_llm_configured(self) -> bool:
        """OpenSDK Provider 是否具备最小真实调用配置。"""
        return bool(self.enable_opensdk_llm and self.openai_api_key)

    @property
    def real_llm_configured(self) -> bool:
        """是否存在可真实调用的 LLM 上游。"""
        return self.opensdk_llm_configured or self.internal_llm_configured

    @property
    def task_completion_llm_active(self) -> bool:
        """任务完成度验收是否会尝试走 LLM。

        必须同时满足 ENABLE_TASK_COMPLETION_VERIFY 和 TASK_COMPLETION_ENABLE_LLM。
        如果没有真实 LLM 上游，TaskCompletionVerifierService 仍会拒绝真实调用。
        """
        return self.enable_task_completion_verify and self.task_completion_enable_llm

    @property
    def mcp_discovery_active(self) -> bool:
        """是否会启动 MCP 能力发现。

        ENABLE_MCP_CLIENT=true 只是允许 MCP；MCP_SERVERS_JSON/MCP_SERVERS 配置
        了 server 后才会真正发现外部工具。
        """
        return self.enable_mcp_client and bool(self.mcp_servers_json)

    @property
    def body_identity_fallback_active(self) -> bool:
        """是否允许请求体 tenant/user 作为身份兜底。仅建议本地开发开启。"""
        return self.allow_request_body_identity_fallback


def describe_effective_switches(settings: Settings) -> tuple[ConfigSwitch, ...]:
    """返回组合后的有效开关视图，避免只看单个 env 造成误判。"""
    return (
        ConfigSwitch(
            name="trusted_auth_required",
            enabled=settings.auth_mode in {"required", "jwt"} and not settings.allow_request_body_identity_fallback,
            variables=("AUTH_MODE", "ALLOW_REQUEST_BODY_IDENTITY_FALLBACK"),
            description="是否必须使用可信 Header/JWT 身份，禁止请求体自证身份。",
        ),
        ConfigSwitch(
            name="real_llm",
            enabled=settings.real_llm_configured,
            variables=("ENABLE_REAL_LLM", "ENABLE_OPENSDK_LLM", "INTERNAL_LLM_API_URL", "OPENAI_API_KEY"),
            description="是否存在真实 LLM 上游；OpenSDK 或 Internal base_url 任一配置完整即可。",
        ),
        ConfigSwitch(
            name="task_completion_llm_verify",
            enabled=settings.task_completion_llm_active and settings.real_llm_configured,
            variables=("ENABLE_TASK_COMPLETION_VERIFY", "TASK_COMPLETION_ENABLE_LLM", "LLM provider config"),
            description="任务完成度验收是否会实际调用 LLM。",
        ),
        ConfigSwitch(
            name="mcp_dynamic_tools",
            enabled=settings.mcp_discovery_active,
            variables=("ENABLE_MCP_CLIENT", "MCP_SERVERS_JSON"),
            description="是否从 MCP server 动态发现并注册工具。",
        ),
        ConfigSwitch(
            name="session_execution_lock",
            enabled=settings.enable_session_execution_lock,
            variables=("ENABLE_SESSION_EXECUTION_LOCK", "SESSION_LOCK_TIMEOUT_SECONDS"),
            description="是否保证同一 session_key 的 Graph run 串行执行。",
        ),
        ConfigSwitch(
            name="knowledge_api",
            enabled=settings.enable_knowledge_api and bool(settings.knowledge_api_url),
            variables=("ENABLE_KNOWLEDGE_API", "KNOWLEDGE_API_URL"),
            description="是否使用外部知识库 API；只打开 enabled 但没有 URL 不算可用。",
        ),
        ConfigSwitch(
            name="http_admin_tools",
            enabled=settings.enable_http_tools and bool(settings.allowed_http_tool_hosts),
            variables=("ENABLE_HTTP_TOOLS", "ALLOWED_HTTP_TOOL_HOSTS"),
            description="是否允许受限 HTTP 管理工具执行外部请求。",
        ),
    )


def validate_settings(settings: Settings) -> tuple[ConfigIssue, ...]:
    """校验配置组合关系。

    原则：
    - 单值枚举和类型错误尽量在 get_settings() 解析阶段失败；
    - 跨字段依赖在这里集中校验；
    - 只对会导致运行错误或明显安全风险的组合返回 error。
    """
    issues: list[ConfigIssue] = []

    def error(code: str, variables: tuple[str, ...], message: str) -> None:
        issues.append(ConfigIssue(level="error", code=code, variables=variables, message=message))

    def warning(code: str, variables: tuple[str, ...], message: str) -> None:
        issues.append(ConfigIssue(level="warning", code=code, variables=variables, message=message))

    if settings.is_prod:
        if settings.auth_mode not in {"required", "jwt"}:
            error(
                "prod_auth_mode_not_required",
                ("APP_ENV", "AUTH_MODE"),
                "APP_ENV=prod 时 AUTH_MODE 必须为 required 或 jwt。",
            )
        if settings.allow_request_body_identity_fallback:
            error(
                "prod_body_identity_fallback_enabled",
                ("APP_ENV", "ALLOW_REQUEST_BODY_IDENTITY_FALLBACK"),
                "APP_ENV=prod 时必须关闭请求体身份兜底。",
            )
        if settings.enable_shell_exec:
            error(
                "prod_shell_exec_enabled",
                ("APP_ENV", "ENABLE_SHELL_EXEC"),
                "APP_ENV=prod 时不得启用 shell_exec 管理工具。",
            )
        if not settings.tool_write_idempotency_enabled:
            error(
                "prod_write_idempotency_disabled",
                ("APP_ENV", "TOOL_WRITE_IDEMPOTENCY_ENABLED"),
                "APP_ENV=prod 时写工具必须启用幂等保护。",
            )
        if not settings.enable_session_execution_lock:
            error(
                "prod_session_execution_lock_disabled",
                ("APP_ENV", "ENABLE_SESSION_EXECUTION_LOCK"),
                "APP_ENV=prod 时必须启用同会话串行执行锁。",
            )
        if settings.log_decision_trace_in_messages:
            warning(
                "prod_decision_trace_persisted",
                ("APP_ENV", "LOG_DECISION_TRACE_IN_MESSAGES"),
                "生产环境将 decision trace 写入消息 metadata 可能增加审计和敏感信息治理压力。",
            )

    if settings.enable_opensdk_llm:
        if not settings.openai_api_key:
            error(
                "opensdk_api_key_missing",
                ("ENABLE_OPENSDK_LLM", "OPENAI_API_KEY"),
                "ENABLE_OPENSDK_LLM=true 时必须配置 OPENAI_API_KEY。",
            )
        if not settings.openai_model:
            error(
                "opensdk_model_missing",
                ("ENABLE_OPENSDK_LLM", "OPENAI_MODEL"),
                "ENABLE_OPENSDK_LLM=true 时必须配置 OPENAI_MODEL。",
            )

    if settings.enable_real_llm and not settings.enable_opensdk_llm and not settings.internal_llm_api_url:
        error(
            "real_llm_without_provider",
            ("ENABLE_REAL_LLM", "ENABLE_OPENSDK_LLM", "INTERNAL_LLM_API_URL"),
            "ENABLE_REAL_LLM=true 但未启用 OpenSDK 且未配置 INTERNAL_LLM_API_URL。",
        )

    if settings.task_completion_llm_active and not settings.real_llm_configured:
        error(
            "task_completion_llm_without_provider",
            ("ENABLE_TASK_COMPLETION_VERIFY", "TASK_COMPLETION_ENABLE_LLM", "LLM provider config"),
            "任务完成度验收启用 LLM 时，必须配置可真实调用的 LLM 上游。",
        )

    if settings.enable_knowledge_api and not settings.knowledge_api_url:
        error(
            "knowledge_api_url_missing",
            ("ENABLE_KNOWLEDGE_API", "KNOWLEDGE_API_URL"),
            "ENABLE_KNOWLEDGE_API=true 时必须配置 KNOWLEDGE_API_URL。",
        )

    if settings.pos_tool_mode == "real" and not settings.pos_api_base_url:
        error(
            "pos_api_base_url_missing",
            ("POS_TOOL_MODE", "POS_API_BASE_URL"),
            "POS_TOOL_MODE=real 时必须配置 POS_API_BASE_URL。",
        )
    if settings.troubleshooting_tool_mode == "real" and not settings.troubleshooting_api_base_url:
        error(
            "troubleshooting_api_base_url_missing",
            ("TROUBLESHOOTING_TOOL_MODE", "TROUBLESHOOTING_API_BASE_URL"),
            "TROUBLESHOOTING_TOOL_MODE=real 时必须配置 TROUBLESHOOTING_API_BASE_URL。",
        )

    if settings.enable_http_tools and not settings.allowed_http_tool_hosts:
        error(
            "http_tools_without_allowlist",
            ("ENABLE_HTTP_TOOLS", "ALLOWED_HTTP_TOOL_HOSTS"),
            "ENABLE_HTTP_TOOLS=true 时必须配置 ALLOWED_HTTP_TOOL_HOSTS 白名单。",
        )

    if settings.no_skill_policy == "generic_dev_only" and settings.app_env != "local":
        error(
            "generic_no_skill_policy_outside_local",
            ("NO_SKILL_POLICY", "APP_ENV"),
            "NO_SKILL_POLICY=generic_dev_only 只能在 APP_ENV=local 使用。",
        )

    if settings.task_completion_max_repair_rounds < 0:
        error(
            "task_completion_repair_rounds_negative",
            ("TASK_COMPLETION_MAX_REPAIR_ROUNDS",),
            "TASK_COMPLETION_MAX_REPAIR_ROUNDS 不能小于 0。",
        )
    if not 0 <= settings.task_completion_min_verifier_confidence <= 1:
        error(
            "task_completion_confidence_out_of_range",
            ("TASK_COMPLETION_MIN_VERIFIER_CONFIDENCE",),
            "TASK_COMPLETION_MIN_VERIFIER_CONFIDENCE 必须在 0 到 1 之间。",
        )

    for name, value in (
        ("TOOL_LOOP_MAX_ITERATIONS", settings.tool_loop_max_iterations),
        ("TOOL_LOOP_MAX_CONSECUTIVE_FAILURES", settings.tool_loop_max_consecutive_failures),
        ("TOOL_LOOP_MAX_SAME_TOOL_FAILURES", settings.tool_loop_max_same_tool_failures),
        ("TOOL_LOOP_MAX_DUPLICATE_CALLS", settings.tool_loop_max_duplicate_calls),
        ("MAX_APPROVAL_CHAIN_DEPTH", settings.max_approval_chain_depth),
    ):
        if value < 1:
            error(f"{name.lower()}_must_be_positive", (name,), f"{name} 必须大于等于 1。")

    if settings.max_write_tools_per_request < 0:
        error(
            "max_write_tools_per_request_negative",
            ("MAX_WRITE_TOOLS_PER_REQUEST",),
            "MAX_WRITE_TOOLS_PER_REQUEST 不能小于 0。",
        )

    for name, value in (
        ("INTERNAL_LLM_TIMEOUT", settings.internal_llm_timeout),
        ("OPENAI_TIMEOUT", settings.openai_timeout),
        ("KNOWLEDGE_API_TIMEOUT", settings.knowledge_api_timeout),
        ("POS_API_TIMEOUT", settings.pos_api_timeout),
        ("TROUBLESHOOTING_API_TIMEOUT", settings.troubleshooting_api_timeout),
        ("APPROVAL_SYSTEM_TIMEOUT", settings.approval_system_timeout),
        ("HTTP_TOOL_TIMEOUT", settings.http_tool_timeout),
        ("SESSION_LOCK_TIMEOUT_SECONDS", settings.session_lock_timeout_seconds),
    ):
        if value <= 0:
            error(f"{name.lower()}_must_be_positive", (name,), f"{name} 必须大于 0。")

    return tuple(issues)


def assert_settings_valid(settings: Settings) -> Settings:
    """配置存在 error 时直接失败；warning 留给启动日志或后续配置页面展示。"""
    errors = [issue for issue in validate_settings(settings) if issue.level == "error"]
    if errors:
        detail = "; ".join(f"{issue.code}: {issue.message}" for issue in errors)
        raise ValueError(f"invalid runtime configuration: {detail}")
    return settings


def get_settings(dotenv_path: Path | None = None) -> Settings:
    """Create Settings from the current environment and optional .env file."""
    load_project_dotenv(dotenv_path)
    app_env = _choice("APP_ENV", os.getenv("APP_ENV"), {"local", "test", "staging", "prod"}, "local")
    real_llm_enabled = _as_bool(os.getenv("ENABLE_REAL_LLM"), False)
    opensdk_llm_enabled = _as_bool(os.getenv("ENABLE_OPENSDK_LLM"), False)
    task_completion_enabled_default = app_env in {"local", "test"}
    task_completion_llm_default = real_llm_enabled or opensdk_llm_enabled
    settings = Settings(
        project_root=PROJECT_ROOT,
        app_env=app_env,
        enable_shell_exec=_as_bool(os.getenv("ENABLE_SHELL_EXEC"), False),
        auth_mode=_choice("AUTH_MODE", os.getenv("AUTH_MODE"), {"dev_header", "required", "jwt"}, "dev_header"),
        allow_request_body_identity_fallback=_as_bool(os.getenv("ALLOW_REQUEST_BODY_IDENTITY_FALLBACK"), True),
        enable_real_llm=real_llm_enabled,
        enable_opensdk_llm=opensdk_llm_enabled,
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
        task_completion_model=os.getenv("TASK_COMPLETION_MODEL") or None,
        final_compliance_model=os.getenv("FINAL_COMPLIANCE_MODEL") or None,
        summary_model=os.getenv("SUMMARY_MODEL") or None,
        enable_mcp_client=_as_bool(os.getenv("ENABLE_MCP_CLIENT"), True),
        mcp_servers_json=os.getenv("MCP_SERVERS_JSON") or os.getenv("MCP_SERVERS") or None,
        unknown_mcp_tool_policy=_choice(
            "UNKNOWN_MCP_TOOL_POLICY",
            os.getenv("UNKNOWN_MCP_TOOL_POLICY"),
            {"allow", "approval", "deny"},
            "allow",
        ),
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
        checkpoint_backend=_choice("CHECKPOINT_BACKEND", os.getenv("CHECKPOINT_BACKEND"), {"memory", "sqlite"}, "memory"),
        checkpoint_db_path=os.getenv("CHECKPOINT_DB_PATH") or None,
        enable_session_execution_lock=_as_bool(os.getenv("ENABLE_SESSION_EXECUTION_LOCK"), True),
        session_lock_timeout_seconds=float(os.getenv("SESSION_LOCK_TIMEOUT_SECONDS", "60")),
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
        enable_task_completion_verify=_as_bool(os.getenv("ENABLE_TASK_COMPLETION_VERIFY"), task_completion_enabled_default),
        task_completion_max_repair_rounds=int(os.getenv("TASK_COMPLETION_MAX_REPAIR_ROUNDS", "2")),
        task_completion_min_verifier_confidence=float(os.getenv("TASK_COMPLETION_MIN_VERIFIER_CONFIDENCE", "0.55")),
        task_completion_enable_llm=_as_bool(os.getenv("TASK_COMPLETION_ENABLE_LLM"), task_completion_llm_default),
        task_completion_enable_state_probes=_as_bool(os.getenv("TASK_COMPLETION_ENABLE_STATE_PROBES"), True),
        task_completion_fail_closed=_as_bool(os.getenv("TASK_COMPLETION_FAIL_CLOSED"), True),
        log_graph_node_events=_as_bool(
            os.getenv("LOG_GRAPH_NODE_EVENTS"),
            app_env == "local",
        ),
        log_disabled_service_events=_as_bool(os.getenv("LOG_DISABLED_SERVICE_EVENTS"), False),
        log_decision_trace_in_messages=_as_bool(os.getenv("LOG_DECISION_TRACE_IN_MESSAGES"), False),
    )
    return assert_settings_valid(settings)
