# MCP Server 与动态工具接入

适用场景：新增 MCP server、调整发现到的工具命名、让 Agent 使用 MCP、定义 MCP 风险处理，或排查 MCP 工具为何不可见/不可执行。

## 当前真实链路

```text
MCP_SERVERS_JSON
  -> Settings.mcp_servers_json
  -> MCPClientManager
  -> initialize() / list_tools()
  -> MCPCapabilityRegistry
  -> AppContainer.startup(): ToolRegistry.register_mcp_tools()
  -> AgentCard.mcp_policy.enabled
  -> ToolExecutor source=mcp -> MCPClientManager.call_tool()
```

MCP 的网络发现发生在 `AppContainer.startup()`，不是 `build_app_container()`。因此 `create_app()` 返回后可以看到 container，但只有 FastAPI lifespan 或显式 `await container.startup()` 后才会有已发现的 MCP tools。

## 1. 新增 MCP server：先改配置，不改 AgentCard 工具列表

在 `.env` 配置：

```dotenv
ENABLE_MCP_CLIENT=true
MCP_SERVERS_JSON=[
  {
    "server_name": "workflow",
    "transport": "http",
    "url": "https://mcp.example/api",
    "timeout": 30,
    "enabled": true
  }
]
```

配置 schema 位于 `app/mcp/schemas.py:MCPServerConfig`；JSON 解析位于 `app/mcp/client_manager.py:parse_mcp_server_configs()`。

注意：

- 当前默认 client 只支持 `http` 或 `sse` transport。
- `tool_name_prefix` 可选；省略时本地注册名为 `mcp.<server_name>.<original_tool_name>`，转换逻辑在 `app/mcp/tool_adapter.py`。
- 不要在 AgentCard 中维护 `mcp_tools` 或 `mcp_tool_scopes` 白名单；当前设计只使用 `mcp_policy.enabled`。

## 2. 让一个 Agent 看见 MCP 工具

修改对应 `app/agents/cards/<agent>.yaml`：

```yaml
mcp_policy:
  enabled: true
```

`ToolRegistry.list_available_tools_for_agent()` 会把该 Agent 的 private tools、允许的 public tools 和所有已发现、enabled 的 MCP tools 合并，再由授权服务过滤。`enabled: false` 的 AgentCard 或 MCP capability 不会暴露。

这意味着：MCP server 新增工具后，只要 server discovery 成功且 card 已启用 MCP，该 Agent 自动可看到新工具，无需同步改 Card 工具列表。Skill 正文仍应仅指导该业务真正需要的 MCP 工具，避免模型在宽泛 MCP 空间里盲目调用。

## 3. MCP 工具风险、Contract 与未知策略

发现的 MCP capability 会由 `ToolRegistry.register_mcp_tools()` 转成 `ToolDefinition(source="mcp")`。风险信息来源优先级是：

1. MCP `raw_schema.metadata.operation/risk_level` 或顶层同名字段；
2. `app/tools/tool_contracts.yaml` 的显式同名 contract；
3. `mcp_default` contract；
4. `UNKNOWN_MCP_TOOL_POLICY`。

`UNKNOWN_MCP_TOOL_POLICY` 在 `.env` / `app/config/settings.py` 中取值：

| 值 | 工具未声明 operation/risk 时的行为 |
| --- | --- |
| `allow` | 允许执行。 |
| `approval` | 转入人工审批。 |
| `deny` | 返回 MCP policy denied，不执行。 |

对于明确是 write/delete/ddl 的工具，应该让 MCP server 在 schema 中声明风险，或在 `tool_contracts.yaml` 写显式 contract；不要长期依赖 unknown 默认策略。

## 4. 刷新与生命周期边界

| 需求 | 真实位置 |
| --- | --- |
| 首次发现 | `AppContainer.startup()` 调 `MCPClientManager.initialize()`，再将 capability 注册进 ToolRegistry。 |
| 手动刷新 capability cache | `MCPClientManager.refresh_capabilities()`；当前不会自动同步清理/重注册 ToolRegistry 中已消失工具。 |
| 调用 MCP 工具 | `ToolExecutor._invoke_definition()` 按 `source == "mcp"` 转给 manager。 |
| server 可用状态 | `MCPCapabilityRegistry` / `MCPServerStatus`。 |
| shutdown | `MCPClient` 定义 `close()`；`MCPClientManager.shutdown()` 逐个关闭已创建的 client，`AppContainer.shutdown()` 负责调用。HTTP client 用 `AsyncClientLifecycle` 管理惰性创建、并发借用和关闭；外部注入的 client 默认不转移关闭权。新增 transport 也必须实现同一关闭协议。 |

如果要实现定时刷新或断线重连，需要单独设计“registry 删除旧工具、ToolRegistry 同步、运行中 Agent 的可见性一致性”，不要只在后台调用 `refresh_capabilities()`。

## 测试

```bash
uv run pytest tests/test_mcp_capability_registry.py tests/test_mcp_client_manager.py -q
uv run pytest tests/test_tool_registry_mcp_visibility.py tests/test_tool_executor_mcp.py -q
uv run pytest tests/test_agent_mcp_tool_loop.py tests/test_troubleshooting_with_mcp.py -q
uv run pytest tests/test_app_container.py -q
```
