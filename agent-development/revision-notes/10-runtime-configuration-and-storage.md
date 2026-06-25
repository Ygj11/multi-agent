# Runtime Container、配置、持久化与可观测性

适用场景：新增环境变量、替换 LLM/外部 client、修改启动初始化、SQLite 表/Store、checkpoint、消息记忆、日志或调试入口。

## 当前启动边界

```text
app/main.py:create_app()
  -> get_settings()
  -> build_app_container(settings, sqlite_db_path)
  -> app.state.container
  -> FastAPI lifespan: await container.startup() / shutdown()
```

同步装配在 `app/bootstrap/container.py:build_app_container()`：storage、LLM、knowledge、clients、ToolRegistry、ToolExecutor、Approval、SkillCatalog、AgentCard、Graph、Orchestrator。异步 MCP discovery/registration 在 `AppContainer.startup()`。`main.py` 不应重新装配 runtime 组件。

## 1. 新增或修改环境变量

按顺序修改：

1. `app/config/settings.py`：给 frozen `Settings` 增加字段，并在 `get_settings()` 从环境解析、校验类型和可选值。
2. `.env.example`：写入无敏感默认值和用途注释；真实 `.env` 只由开发者本地配置，不提交密钥。
3. `app/bootstrap/container.py`：仅当该变量影响 runtime 装配时，把它传给对应 client/service/runner。
4. `tests/test_settings_env.py`：增加解析、默认值和非法值覆盖。
5. 如影响启动行为，增加 `tests/test_app_container.py` 或对应集成测试。

不要在业务 node 内调用 `os.getenv()`；这样会绕开 settings、难以测试，也会让同一进程配置漂移。

## 2. LLM 与外部服务

| 领域 | 真实入口 |
| --- | --- |
| LLM provider 选择 | `app/llm/factory.py`、`app/llm/model_config.py`、`Settings`。 |
| Internal provider | `app/llm/internal_provider.py`；没有 base URL 时按 provider 实现走本地 deterministic fallback。 |
| OpenSDK compatible provider | `app/llm/opensdk_provider.py`；通过 `ENABLE_OPENSDK_LLM` 与 OpenAI-compatible env 配置。 |
| Knowledge service | `app/knowledge/factory.py`；默认 disabled，可由 settings 启用外部 API。 |
| POS / troubleshooting API | `app/integrations/*_api_client.py`，由 Container 按 `*_TOOL_MODE=mock|real` 构建，并聚合为只读 `app/integrations/clients.py:IntegrationClients`。 |
| MCP | [06-mcp-integration.md](06-mcp-integration.md)。 |

新 client 需要先定义可测试接口与 failure semantics，再由 Container 注入；不要在 Tool handler 或 Graph node 内临时 new HTTP client。真实领域 client 增加字段时，同步更新 `IntegrationClients`、`_build_integration_clients()`、使用它的工具注册逻辑与测试；不要回到为 `register_agent_private_tools()` 增加单个 client 参数。长期 HTTP/SDK client 使用 `app/runtime/async_client_lifecycle.py:AsyncClientLifecycle`：组件自建的 client 由组件关闭，外部注入 client 默认仍归调用方所有，只有 `owns_client=True` 才转移关闭权。网络请求通过 `lease()` 在锁外执行，shutdown 会阻止新借用并等待进行中的借用归还。`AppContainer` 是单次生命周期对象，关闭或启动失败后应重新构建，不支持原地 restart。

## 3. SQLite、消息、记忆与 checkpoint

| 数据 | 主要文件 | 修改注意 |
| --- | --- | --- |
| SQLite 初始化与表结构 | `app/storage/sqlite.py` | 当前项目按新表结构建表；结构重构应同步 store、SQL 说明和持久化测试，不要做隐式列探测兼容。 |
| Storage bundle | `app/bootstrap/storage.py` | 统一创建 db、message/checkpoint/tool log/evidence/approval store。 |
| 会话消息 | `app/session/message_store.py`、`session_manager.py` | 保留 user/assistant 业务消息，不写 transient tool-loop 大对象。 |
| message metadata | `app/session/message_metadata_sanitizer.py` | 新 metadata 字段先判断是否应留给下一轮 Query Rewrite。 |
| short memory | `app/memory/short_term_memory_manager.py` | 变更摘要格式时补多轮对话回归。 |
| LangGraph checkpointer | `app/runtime/checkpoint.py` | 与项目级 SQLite checkpoint store 不同。 |
| 请求 snapshot | `app/runtime/state_projector.py`、checkpoint store | 只投影允许持久化的 final state。 |

`CheckpointSnapshot` 是请求级最终摘要；`AgentResumeState` 是审批恢复最小状态；messages/short memory 是对话记忆。三者不能混为一个存储设计。

## 4. app.state 与调试

FastAPI 只暴露：

```python
app.state.container
```

调试或测试应使用：

```python
app.state.container.orchestrator
app.state.container.storage.message_store
app.state.container.tool_registry
```

不要恢复 `app.state.orchestrator`、`app.state.message_store` 等平铺兼容字段；它们会让 FastAPI 重新变成隐式 Service Locator。

## 5. 日志、trace 与运行诊断

- 结构化日志：`app/observability/logger.py`，通过 `request_id`、`trace_id`、`session_key`、node name 关联。
- Graph path：每个节点追加 `graph_path`，用于解释实际路径。
- 工具日志：`app/tools/tool_execution_log_store.py`。
- 审批事件：ApprovalStore。
- Evidence：`app/evidence/*`。

新增日志字段前检查是否含敏感数据；日志预览应走 `preview_text()`，不要记录完整认证信息或未脱敏原文。

## 验证

```bash
uv run pytest tests/test_settings_env.py tests/test_app_container.py -q
uv run pytest tests/test_sqlite_persistence.py tests/test_checkpoint_factory.py tests/test_checkpoint_projection.py -q
uv run pytest tests/test_multi_turn_memory.py tests/test_message_metadata_boundary.py tests/test_runtime_logging.py -q
```
