from __future__ import annotations

"""工具可见性、执行来源、操作类型和停止原因。"""

from app.schemas.enums.base import DescribedStrEnum


class ToolScope(DescribedStrEnum):
    PUBLIC = ("public", "公共工具，可被允许公共工具的 Agent 使用。")
    PRIVATE = ("private", "Agent 私有工具，只对绑定 Agent 可见。")
    MCP = ("mcp", "MCP 动态发现工具。")


class ToolSource(DescribedStrEnum):
    LOCAL = ("local", "本地 Python callable 工具。")
    MCP = ("mcp", "通过 MCP server 执行的工具。")


class ToolOperation(DescribedStrEnum):
    READ = ("read", "只读查询。")
    WRITE = ("write", "写操作。")
    NOTIFY = ("notify", "通知或触发外部状态刷新。")
    EXECUTE = ("execute", "执行类操作。")
    SEARCH = ("search", "检索类操作。")
    DELETE = ("delete", "删除类操作。")
    DDL = ("ddl", "数据定义类高风险操作。")


class DataClassification(DescribedStrEnum):
    PUBLIC = ("public", "公开数据。")
    INTERNAL = ("internal", "内部数据。")
    CONFIDENTIAL = ("confidential", "机密数据。")
    SENSITIVE = ("sensitive", "敏感数据。")


class RiskLevel(DescribedStrEnum):
    LOW = ("low", "低风险操作。")
    MEDIUM = ("medium", "中风险操作。")
    HIGH = ("high", "高风险操作，通常需要审批。")


class UnknownMCPToolPolicy(DescribedStrEnum):
    ALLOW = ("allow", "未知 MCP 工具默认允许执行。")
    APPROVAL = ("approval", "未知 MCP 工具执行前必须先审批。")
    DENY = ("deny", "未知 MCP 工具直接拒绝执行。")


class ToolStoppedReason(DescribedStrEnum):
    FINAL = ("final", "LLM 已生成最终答案。")
    ERROR = ("error", "LLM 或工具循环出现错误。")
    MAX_ITERATIONS = ("max_iterations", "达到工具循环最大轮次。")
    HUMAN_APPROVAL_REQUIRED = ("human_approval_required", "工具调用需要人工审批，循环暂停。")
    MAX_CONSECUTIVE_TOOL_FAILURES = ("max_consecutive_tool_failures", "连续工具失败次数达到上限。")
    MAX_SAME_TOOL_FAILURES = ("max_same_tool_failures", "同一工具失败次数达到上限。")
    MAX_DUPLICATE_TOOL_CALLS = ("max_duplicate_tool_calls", "重复工具调用次数达到上限。")


class ToolErrorCode(DescribedStrEnum):
    TOOL_NOT_FOUND = ("tool_not_found", "工具不存在。")
    TOOL_NOT_AVAILABLE_FOR_AGENT = ("tool_not_available_for_agent", "工具对当前 Agent 不可见。")
    MISSING_REQUIRED_ARGUMENT = ("missing_required_argument", "工具缺少必填参数。")
    PERMISSION_DENIED = ("permission_denied", "工具或资源权限不足。")
    VERIFICATION_FAILED = ("verification_failed", "工具执行前验证失败。")
    HUMAN_APPROVAL_REQUIRED = ("human_approval_required", "工具需要人工审批。")
    TOOL_TIMEOUT = ("tool_timeout", "本地工具执行超时。")
    TOOL_EXECUTION_EXCEPTION = ("tool_execution_exception", "本地工具执行异常。")
    TOOL_RESULT_SCHEMA_INVALID = ("tool_result_schema_invalid", "工具返回结果不满足静态结果契约。")
    MCP_SERVER_UNAVAILABLE = ("mcp_server_unavailable", "MCP server 不可用。")
    MCP_TOOL_TIMEOUT = ("mcp_tool_timeout", "MCP 工具调用超时。")
    MCP_TOOL_ERROR = ("mcp_tool_error", "MCP 工具调用失败。")
    MCP_TOOL_POLICY_DENIED = ("mcp_tool_policy_denied", "未知 MCP 工具策略拒绝执行。")
