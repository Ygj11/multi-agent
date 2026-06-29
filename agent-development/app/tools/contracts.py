from __future__ import annotations

"""工具静态契约加载和校验。

ToolContract 不注册工具，也不执行工具；它为已注册 ToolDefinition 补充
timeout、结果 schema、数据分级、操作类型、风险等级和审批策略等治理信息。
未配置某项可选约束时，不对该项施加额外校验。
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field, model_validator

from app.schemas.enums.tool import DataClassification, RiskLevel, ToolOperation


DEFAULT_TOOL_CONTRACTS_PATH = Path(__file__).with_name("tool_contracts.yaml")


class RetryPolicy(BaseModel):
    """Minimal retry declaration.

    P4.4A deliberately keeps retry as a declaration only. Runtime retry
    execution is a later task.
    """

    max_attempts: int = 1

    @model_validator(mode="after")
    def validate_retry(self) -> "RetryPolicy":
        if self.max_attempts < 1:
            raise ValueError("retry.max_attempts must be >= 1")
        return self


class ToolContract(BaseModel):
    """Minimal execution contract attached to a ToolDefinition.

    ``result_schema`` 和 ``approval_policy_id`` 均为可选附加约束：未配置
    结果 Schema 时跳过结果结构校验；未配置审批策略时，不会覆盖写操作或
    风险等级已有的审批判断。超时和数据分级属于有默认值的策略参数。

    它不是权限策略本身。工具权限主要来自 ToolDefinition.required_scopes、
    resource_type 和 resource_id_arg；Contract 只能补充 operation/risk_level/
    approval_policy_id 等执行治理信号。例如一个工具注册时 operation=read，
    但 tool_contracts.yaml 为它声明 operation=notify、risk_level=high，则
    ToolRegistry 会生成带新治理字段的 ToolDefinition，ToolExecutor 后续按更新后
    的字段判断审批和审计。
    """

    tool_name: str
    timeout_ms: int = 10000
    retry: RetryPolicy = Field(default_factory=RetryPolicy)
    result_schema: str | None = None
    approval_policy_id: str | None = None
    idempotency_key_fields: list[str] = Field(default_factory=list)
    data_classification: DataClassification = DataClassification.INTERNAL
    operation: ToolOperation | None = None
    risk_level: RiskLevel | None = None

    @model_validator(mode="after")
    def validate_contract(self) -> "ToolContract":
        if not self.tool_name.strip():
            raise ValueError("tool_name is required")
        if self.timeout_ms <= 0:
            raise ValueError(f"{self.tool_name}.timeout_ms must be > 0")
        return self


class ToolContractCatalog(BaseModel):
    """已加载的工具契约目录，包含显式工具契约和 MCP 默认契约。"""

    version: str
    defaults: dict = Field(default_factory=dict)
    tools: dict[str, ToolContract] = Field(default_factory=dict)
    mcp_default: ToolContract | None = None

    @classmethod
    def load(cls, path: Path | str = DEFAULT_TOOL_CONTRACTS_PATH) -> "ToolContractCatalog":
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ValueError("tool contract root must be a mapping")
        defaults = raw.get("defaults") or {}
        if not isinstance(defaults, dict):
            raise ValueError("tool contract defaults must be a mapping")
        raw_tools = raw.get("tools") or {}
        if not isinstance(raw_tools, dict):
            raise ValueError("tool contract tools must be a mapping")
        tools = {
            str(tool_name): ToolContract(**{**defaults, **(definition or {}), "tool_name": str(tool_name)})
            for tool_name, definition in raw_tools.items()
        }
        raw_mcp_default = raw.get("mcp_default")
        mcp_default = None
        if isinstance(raw_mcp_default, dict):
            mcp_default = ToolContract(**{**defaults, **raw_mcp_default, "tool_name": "mcp.*"})
        return cls(
            version=str(raw.get("version") or "unknown"),
            defaults=defaults,
            tools=tools,
            mcp_default=mcp_default,
        )

    def contract_for(self, tool_name: str, *, source: str | None = None) -> ToolContract | None:
        """返回显式契约；MCP 工具没有显式契约时使用 mcp_default。"""
        if tool_name in self.tools:
            return self.tools[tool_name]
        if source == "mcp" or tool_name.startswith("mcp."):
            return self._mcp_contract(tool_name)
        return None

    def explicit_tool_names(self) -> set[str]:
        return set(self.tools)

    def _mcp_contract(self, tool_name: str) -> ToolContract | None:
        if self.mcp_default is None:
            return None
        return self.mcp_default.model_copy(update={"tool_name": tool_name})
