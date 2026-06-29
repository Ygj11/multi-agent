from __future__ import annotations

"""Base tool types for the card-driven tool layer."""

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.tools.contracts import ToolContract


ToolCallable = Callable[..., Awaitable[Any]]
ToolScope = Literal["public", "private", "mcp"]
ToolSource = Literal["local", "mcp"]
ToolOperation = Literal["read", "write", "notify", "execute", "search", "delete", "ddl"]
DataClassification = Literal["public", "internal", "confidential", "sensitive"]


class ToolDefinition(BaseModel):
    """已注册工具的运行时元数据。

    ToolDefinition 是 ToolRegistry、ToolExecutor 和 LLM function calling 的共同契约：

    - LLM 看到的是 name / description / parameters 组成的 tool schema；
    - ToolRegistry 用 scope / agent_name / source 判断工具对哪个 Agent 可见；
    - ToolExecutor 用 required_scopes / resource_type / resource_id_arg 做权限和资源访问校验；
    - ToolExecutor 用 is_write / operation / risk_level / contract.approval_policy_id 判断是否需要审批；
    - ToolContract 可以在注册后覆盖 operation、risk_level、data_classification 等治理字段。

    示例：

    ```python
    ToolDefinition(
        name="notice_policy_update",
        callable=notice_policy_update,
        description="通知下游刷新保单状态",
        scope="private",
        agent_name="troubleshooting_agent",
        parameters={
            "type": "object",
            "properties": {"apply_seq": {"type": "string"}},
            "required": ["apply_seq"],
        },
        is_write=True,
        operation="notify",
        required_scopes=["troubleshooting:write"],
        resource_type="policy",
        resource_id_arg="policyNo",
        risk_level="high",
        idempotency_required=True,
    )
    ```
    """

    name: str = Field(description="工具注册名，也是 LLM function calling 中的 function.name。")
    callable: ToolCallable = Field(exclude=True, description="本地工具的 Python callable；MCP 工具不会直接使用该字段。")
    description: str = Field(default="", description="给 LLM 看的工具能力描述，影响模型是否选择该工具。")
    scope: ToolScope = Field(default="public", description="工具可见性范围：public 公共工具，private 某 Agent 私有工具，mcp 动态发现工具。")
    source: ToolSource = Field(default="local", description="执行来源：local 调本地 callable；mcp 通过 MCP client 调外部 server。")
    agent_name: str | None = Field(default=None, description="scope=private 时绑定的 Agent 名称。")
    server_name: str | None = Field(default=None, description="source=mcp 时的 MCP server 名称，用于审计和诊断。")
    original_name: str | None = Field(default=None, description="MCP 或外部系统的原始工具名；name 可能是注册后的规范名。")
    parameters: dict[str, Any] = Field(default_factory=dict, description="OpenAI function calling 风格 JSON Schema；required 字段用于缺参检查。")
    enabled: bool = Field(default=True, description="是否启用该工具；禁用后不应对 Agent 暴露或执行。")
    is_write: bool = Field(default=False, description="是否写操作；为 true 时默认需要人工审批。")
    operation: ToolOperation = Field(default="read", description="操作类型，影响审批、资源访问 action 和审计；如 read/write/notify/delete/ddl。")
    required_scopes: list[str] = Field(default_factory=list, description="执行该工具要求 principal.scopes 具备的权限标识。空列表表示不增加工具级 scope 限制。")
    resource_type: str | None = Field(default=None, description="资源类型，如 policy、claim；配置后会触发 ResourceAccessService 资源访问校验。")
    resource_id_arg: str | None = Field(default=None, description="从工具参数中取哪个字段作为资源 ID，例如 policyNo。")
    pre_answer_filter_required: bool = Field(default=True, description="工具结果进入最终答案前是否应经过外发过滤；当前主要用于治理标记。")
    data_domains: list[str] = Field(default_factory=list, description="工具涉及的数据域，如 policy、customer、finance，用于审计和后续策略。")
    data_classification: DataClassification = Field(default="internal", description="工具结果数据分级：public/internal/confidential/sensitive。")
    risk_level: Literal["low", "medium", "high"] = Field(default="low", description="工具风险等级；high 默认需要审批。")
    precondition_id: str | None = Field(default=None, description="前置条件策略 ID；预留给后续确定性 precondition 检查。")
    idempotency_required: bool = Field(default=False, description="是否要求幂等保护，常用于写操作避免审批 callback 重复执行。")
    contract: ToolContract | None = Field(default=None, description="静态工具契约，来自 tool_contracts.yaml，可补充超时、结果 schema、风险和审批策略。")
    metadata: dict[str, Any] = Field(default_factory=dict, description="注册期附加元数据；只用于审计、调试或治理标记，不应承载业务必填参数。")

    model_config = {"arbitrary_types_allowed": True}
