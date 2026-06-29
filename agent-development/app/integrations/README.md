# Integrations

`app/integrations/` 放外部系统的领域 Client 和共享 HTTP 传输层。这里的文件不会因为位于本目录就自动进入主流程，只有被 `bootstrap`、`factory`、`ToolRegistry` 或具体运行时显式注入后，才算主链路能力。

当前项目的 MCP runtime 不在这里，而在 `app/mcp/`：

```text
app/mcp/client.py::HTTPMCPClient
app/mcp/client_manager.py::MCPClientManager
```



## 当前状态

| 文件 | 当前状态 | 作用 | 入口或使用方 |
| --- | --- | --- | --- |
| `base_http_client.py` | 已使用 | 共享 HTTP 传输层，负责连接池复用、请求级 headers、JSON 请求、基础脱敏和关闭生命周期。 | `PosAPIClient`、`TroubleshootingAPIClient`、`KnowledgeAPIClient` 以及示例 Client |
| `clients.py` | 已使用 | `IntegrationClients` 只读依赖集合，把真实领域 Client 注入工具注册层。 | `app/bootstrap/container.py`、`app/tools/agent_tools.py` |
| `pos_api_client.py` | 条件使用 | POS 领域 Client，封装保全实时查询、试算、批文、提交校验等 POS HTTP 调用边界。 | `POS_TOOL_MODE=real` 时由 `AppContainer` 构建，再被 POS tool handlers 使用 |
| `troubleshooting_api_client.py` | 条件使用 | 排障领域 Client，封装工作流状态、节点状态、内部日志、保全任务记录和通知类接口。 | `TROUBLESHOOTING_TOOL_MODE=real` 时由 `AppContainer` 构建，再被 troubleshooting real tool handlers 使用 |
| `knowledge_api_client.py` | 条件使用 | 外部知识库 Client，实现 `KnowledgeService` 查询接口，并把外部结果归一化为 `KnowledgeChunk`。 | `ENABLE_KNOWLEDGE_API=true` 时由 `app/knowledge/factory.py` 构建 |
| `log_api_client.py` | 未接主流程 | 未来真实日志平台 Client 示例，可替换或补强排障中的内部日志查询。 | 目前只在测试中检查接口形态 |
| `llm_api_client_example.py` | 未接主流程 | 未来 LLM Provider 底层 HTTP Client 示例。 | 当前真实 LLM 接入在 `app/llm/`，这里不参与运行 |
| `long_term_memory_api_client.py` | 未接主流程 | 未来长期记忆服务 Client 示例。 | 当前会话记忆仍走项目内 memory/session 体系 |
| `vector_search_api_client.py` | 未接主流程 | 未来向量检索 / 关键词检索 Client 示例。 | 当前知识检索不直接使用它 |
| `insurance_core_api_client.py` | 未接主流程 | 未来保险核心系统只读查询和校验 Client 示例。 | 当前工具未注入它 |
| `observability_api_client.py` | 未接主流程 | 未来可观测平台 Client 示例，可用于事件、trace span 外发。 | 当前结构化日志仍走 `app/observability/logger.py` |
| `checkpoint_backend_examples.py` | 未接主流程 | PostgreSQL / Redis checkpoint backend 示例。 | 当前 checkpoint 使用 SQLite 实现 |

## 已接入链路

### POS API

```text
Settings
→ AppContainer._build_integration_clients()
→ IntegrationClients(pos=PosAPIClient(...))
→ register_agent_private_tools(...)
→ POS tool handler
→ PosAPIClient.post(...)
→ BaseIntegrationHTTPClient
```

只有 `POS_TOOL_MODE=real` 时才构建 `PosAPIClient`。如果是 `mock`，工具注册层会使用 in-process mock client，不访问真实 POS。

### Troubleshooting API

```text
Settings
→ AppContainer._build_integration_clients()
→ IntegrationClients(troubleshooting=TroubleshootingAPIClient(...))
→ register_agent_private_tools(...)
→ troubleshooting real tool handler
→ TroubleshootingAPIClient
→ BaseIntegrationHTTPClient
```

只有 `TROUBLESHOOTING_TOOL_MODE=real` 时才构建 `TroubleshootingAPIClient`。如果是 `mock`，工具注册层会使用本地 mock handlers。

### Knowledge API

```text
Settings
→ app/knowledge/factory.py
→ KnowledgeAPIClient
→ KnowledgeService interface
→ ContextBuilder / KnowledgeHintBuilder / public knowledge tools
```

知识库不放进 `IntegrationClients`，因为它不是某个 Agent 私有工具的领域 Client，而是项目级 `KnowledgeService` 实现。只有 `ENABLE_KNOWLEDGE_API=true` 且配置了 `KNOWLEDGE_API_URL` 时启用。

## 未接主流程的示例 Client

以下文件是未来接真实外部平台时的参考适配器，当前不应被当作已上线能力：

```text
log_api_client.py
llm_api_client_example.py
long_term_memory_api_client.py
vector_search_api_client.py
insurance_core_api_client.py
observability_api_client.py
checkpoint_backend_examples.py
```

保留它们的价值是统一未来接入风格：

- 使用 `BaseIntegrationHTTPClient` 复用连接池；
- 所有外部请求保留 `request_id` / `trace_id`；
- 不修改共享 HTTP client 的全局 headers、cookies 或认证状态；
- 用户级身份、租户、权限应通过单次请求参数或受信 auth header 传递；
- 写操作、敏感数据、长期记忆更新、核心系统校验必须补充权限、审批、脱敏、审计和测试后才能接入主流程。

## 未来如何扩展

### 新增一个给 Tool 使用的真实领域 Client

适合场景：某个 Agent 的工具需要调用外部业务系统。

步骤：

1. 在 `app/integrations/` 新增领域 Client，内部依赖 `BaseIntegrationHTTPClient`。
2. 在 `app/config/settings.py` 增加 base_url、timeout、mode 或 enable 开关。
3. 在 `AppContainer._build_integration_clients()` 中按配置构建 Client。
4. 在 `IntegrationClients` 增加只读字段。
5. 在 `app/tools/handlers/` 新增 tool handler，把工具入参映射成外部 API payload。
6. 在 `app/tools/agent_tools.py` 注册工具，并配置参数 schema、operation、risk_level、required_scopes。
7. 如有写操作或高风险操作，同步配置 tool contract、审批和幂等策略。
8. 补充单元测试和至少一条 tool executor / subagent 回归测试。

### 新增项目级服务 Client

适合场景：知识库、记忆、观测、checkpoint 这类不是某个 Agent 私有工具的基础服务。

步骤：

1. 在 `app/integrations/` 新增 Client。
2. 新增或修改对应 service factory，例如 `app/knowledge/factory.py` 这种模式。
3. 在 `AppContainer` 中把 service 注入需要的 runtime 组件。
4. 明确关闭责任：如果 Client 持有 HTTP 连接池，应由 `AppContainer.shutdown()` 统一关闭。
5. 补充 factory、生命周期和主链路回归测试。

### 新增 MCP 集成

不要在 `app/integrations/` 新增 MCP runtime client。当前 MCP 主链路是：

```text
Settings.mcp_servers_json
→ MCPClientManager.initialize()
→ HTTPMCPClient.initialize/list_tools()
→ MCPCapabilityRegistry
→ ToolRegistry.register_mcp_tools()
→ ToolExecutor
→ MCPClientManager.call_tool()
→ HTTPMCPClient.call_tool()
```

如果要扩展 MCP transport，应实现 `app/mcp/client.py::MCPClient` 协议，例如新增 SSE client 或 SDK client，然后让 `MCPClientManager` 的 factory 选择它。

## 判断一个 integration 是否真的被使用

不要只看文件是否存在。应检查：

- 是否被 `AppContainer` 构建；
- 是否进入 `IntegrationClients` 或某个 service factory；
- 是否被 `ToolRegistry` 注册为工具 callable；
- 是否被 Graph、ContextBuilder、KnowledgeService、ToolExecutor 等主链路组件调用；
- 是否有覆盖真实主链路的测试，而不仅是方法签名测试。

如果以上都没有，它就是示例或未来扩展，不是当前运行能力。
