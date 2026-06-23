# 新增或修改本地 Tool、Contract 与执行流水线

适用场景：新增 public/private 工具、将 mock 切到 real、变更工具参数/返回值、配置读写风险、权限、审批、超时或结果 schema。

## 当前真实执行链

```text
Skill / AgentCard 可见工具
  -> ToolRegistry 生成 LLM function schema
  -> ToolCallingRunner 解析 tool call
  -> ToolExecutionPipeline
     exists -> Agent visibility -> required args -> authorization
     -> pre-tool verification -> MCP policy -> approval -> execute
  -> ToolExecutor timeout + result schema validation + log + evidence
```

LLM 不会直接调用 Python callable。`ToolExecutor.execute()` 是正常调用的唯一服务端入口；`execute_approved_tool()` 是审批后的专用入口。

## 1. 选择工具类型与 handler 位置

| 工具类型 | handler / 注册位置 |
| --- | --- |
| Agent 私有业务工具 | handler 放在 `app/tools/handlers/`，注册集中在 `app/tools/agent_tools.py:register_agent_private_tools()`。 |
| 全体允许 public tools | `app/tools/public_tools.py:register_public_tools()`。 |
| 运维受限工具 | `app/bootstrap/tools.py:register_admin_restricted_tools()`；默认不应暴露给业务 Agent。 |
| 外部 MCP 工具 | 不在这里手工注册，见 [06-mcp-integration.md](06-mcp-integration.md)。 |

当前 troubleshooting 有 mock handler `mvp_agent_tool_handlers.py` 与 real factory `troubleshooting_real_tool_handlers.py`；POS 使用 `pos_query_mock_client.py` 与 `pos_query_tool_handlers.py`。新增业务工具时先确定它是否需要同名 mock/real 两种实现，再保持注册名稳定。

## 2. 新增 private tool 的完整步骤

1. 在 `app/tools/handlers/` 或相应 `app/integrations/*_api_client.py` 实现 async callable/factory。优先让 handler 只做外部 API 适配，不承载 Agent 路由规则。
2. 在 `app/tools/agent_tools.py` 定义 OpenAI-compatible `parameters`，然后在 `register_agent_private_tools()` 调用 `registry.register_private(...)`。
3. 设置 `description`、`operation`、`is_write`、`required_scopes`、`resource_type`、`resource_id_arg`、`risk_level`、`data_domains` 等真实元数据；不要只靠描述判断风险。
4. 在 `app/tools/tool_contracts.yaml` 新增同名 contract：timeout、result_schema、approval policy、idempotency fields、data classification、必要时 operation/risk level。
5. 在对应 AgentCard `private_tools` 增加该工具。
6. 在使用该工具的 Skill frontmatter `private_tools` 中增加；在 Skill 正文写清工具何时调用、何时禁止调用、参数映射与成功/失败解释。
7. 若属于 write/notify/delete/ddl，确认审批路径、外部 API 幂等语义和权限测试；不要在 mock 模式误标已执行。

## 3. 新增 public tool 的差异

1. 在 `app/tools/public_tools.py` 实现/注册。
2. 只有 `AgentCard.public_tools_allowed: true` 的 Agent 能看到它；不需要把工具名写入 Card `private_tools`。
3. 仍必须有 `tool_contracts.yaml` contract 与工具测试。
4. 如果 public tool 实际只适用于一个 Agent，它不应是 public，应回到 private tool。

## 4. 参数与返回值变更

### 参数

- 更改 `parameters` 的 `properties`/`required` 会影响 LLM function schema 和 `ToolArgumentGuard`。
- 当前 guard 只严格检查 required 字段存在；类型、enum、format、additionalProperties 尚未是强制 JSON Schema validator。高风险工具不要把这一事实当作已完成保护。
- 内部 canonical 实体例如 `policy_no`，外部参数可能是 `policyNo`；映射应该放在 Skill 指令或 handler adapter，不要污染 EntityResolver canonical key。

### 返回

- 统一返回 `dict`、字符串或业务对象；`ToolExecutor` 将其包装成 `ToolResult`。
- 若 contract 声明 `result_schema`，在 `app/tools/result_schemas.py` 注册/更新该 schema；否则成功结果会被标记 `tool_result_schema_invalid`。
- Tool result 会进入 LLM observation、ToolExecutionLog 和 Evidence。不要把 credentials、原始敏感字段或无界大 payload 直接返回。

## 5. 权限、审批与契约

| 需求 | 必改位置 |
| --- | --- |
| 工具 scope / 资源归属 | `register_private/register_public` 元数据；`app/auth/authorization_service.py` 支持的语义；`tests/test_tool_executor_authorization.py`。 |
| 是否触发审批 | `is_write`、`operation`、`risk_level`、`ToolContract.approval_policy_id`；审批 guard 与测试。 |
| 超时/结果 schema | `app/tools/tool_contracts.yaml`、`app/tools/result_schemas.py`。 |
| MCP 未声明风险的默认行为 | `UNKNOWN_MCP_TOOL_POLICY`；仅影响 source=mcp。 |
| 预执行验证 | 注册 verifier 或扩展 `VerificationService`，不要在 callable 内复制 authorization。 |

`ToolContract` 会覆盖 `ToolDefinition` 中声明的 operation/risk 等可覆盖属性；启动期 `ToolRegistry.validate_contracts()` 会记录 warning，prod strict 时会失败。

## 6. 必跑测试

```bash
uv run pytest tests/test_tool_schema_openai.py tests/test_tool_contracts.py -q
uv run pytest tests/test_tool_execution_pipeline.py tests/test_tool_contract_runtime.py -q
uv run pytest tests/test_tool_executor_authorization.py tests/test_subagent_tool_visibility.py -q
```

新增业务工具还应补 handler/API client 的单测；写工具必须加审批回归：

```bash
uv run pytest tests/test_approval_full_flow.py tests/test_approval_callback_approved.py tests/test_approval_callback_rejected.py -q
```
