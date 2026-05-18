# TASK5.md

## 阶段目标

为当前所有 mock/stub 能力补齐“未来接真实 API 的完整代码示例”，但默认不启用真实外部请求。

当前 mock/stub 包括：

1. `InMemoryKnowledgeService`
2. `FakeMCPConnector`
3. `query_internal_log`
4. `partner_trace.get_request_detail`
5. `FakeLLMProvider` 默认模型
6. `LongTermMemoryManager`
7. 项目内 SQLite checkpoint store
8. 本地 SQLite tool audit
9. 未接真实 MCP
10. 未接 Milvus / Elasticsearch / Redis
11. 未接保险核心系统
12. 未接 OpenTelemetry

TASK5 的目标不是替换现有主流程，而是新增一组完整、可读、可测试的真实 API client 示例，作为未来替换 mock/stub 的落点。

---

## 本轮必须实现

必须新增目录：

```text
app/integrations/
  __init__.py
  base_http_client.py
  knowledge_api_client.py
  log_api_client.py
  partner_trace_api_client.py
  mcp_http_client.py
  llm_api_client_example.py
  long_term_memory_api_client.py
  audit_api_client.py
  checkpoint_backend_examples.py
  vector_search_api_client.py
  insurance_core_api_client.py
  observability_api_client.py
```

必须满足：

1. 所有真实 API 示例代码默认不启用。
2. 所有真实 API 示例代码必须完整，不要只写空函数。
3. 所有真实 API 示例必须带 TODO 注释，说明未来替换真实地址、真实鉴权、真实字段映射的位置。
4. 所有真实 API 示例必须支持 `request_id` / `trace_id` 透传。
5. 所有真实 API 示例必须支持 timeout。
6. 所有真实 API 示例必须有异常处理。
7. 所有真实 API 示例必须有脱敏处理或脱敏 TODO。
8. 现有 mock/stub 主流程保持不变。
9. 不要真实请求外部系统。
10. 必须备注后续请使用对应 client 进行替换。
11. 不改变 `/api/chat` 响应格式。
12. 所有已有测试继续通过。

建议新增环境变量，但默认不启用：

```text
ENABLE_REAL_INTEGRATIONS=false
KNOWLEDGE_API_BASE_URL=
LOG_API_BASE_URL=
PARTNER_TRACE_API_BASE_URL=
MCP_HTTP_BASE_URL=
LONG_TERM_MEMORY_API_BASE_URL=
AUDIT_API_BASE_URL=
CHECKPOINT_BACKEND_URL=
VECTOR_SEARCH_API_BASE_URL=
INSURANCE_CORE_API_BASE_URL=
OBSERVABILITY_API_BASE_URL=
INTEGRATION_API_TOKEN=
INTEGRATION_TIMEOUT_SECONDS=10
```

---

## 本轮不要实现

本轮不要实现：

1. 不替换当前 `InMemoryKnowledgeService`
2. 不替换当前 `FakeMCPConnector`
3. 不替换当前 `query_internal_log`
4. 不替换当前 `partner_trace.get_request_detail`
5. 不启用真实外部请求
6. 不接真实 Milvus
7. 不接真实 Elasticsearch
8. 不接真实 Redis
9. 不接真实 MCP Server
10. 不接真实保险核心系统
11. 不接真实 OpenTelemetry
12. 不改变 `/api/chat` 响应格式
13. 不做策略治理和工具元数据化
14. 不新增 `ToolMetadata`
15. 不新增 `ToolRiskLevel`
16. 不新增 `ToolOperationType`
17. 不改造 PolicyGate 为 metadata 模式

---

## 需要新增或修改的文件

新增：

```text
app/integrations/__init__.py
app/integrations/base_http_client.py
app/integrations/knowledge_api_client.py
app/integrations/log_api_client.py
app/integrations/partner_trace_api_client.py
app/integrations/mcp_http_client.py
app/integrations/llm_api_client_example.py
app/integrations/long_term_memory_api_client.py
app/integrations/audit_api_client.py
app/integrations/checkpoint_backend_examples.py
app/integrations/vector_search_api_client.py
app/integrations/insurance_core_api_client.py
app/integrations/observability_api_client.py
```

可能修改：

```text
app/config/settings.py
README.md
tests/test_integration_clients.py
```

不得修改主流程以启用真实外部请求。

---

## 代码设计要求

### base_http_client.py

实现统一 HTTP client 示例。

要求：

1. 使用 `httpx.AsyncClient`
2. 支持 base_url
3. 支持 timeout
4. 支持默认 headers
5. 支持 request_id / trace_id 透传
6. 支持 JSON 请求
7. 支持异常处理
8. 支持响应状态码检查
9. 支持最小脱敏日志
10. 默认不在主流程中实例化

建议接口：

```python
class BaseIntegrationHTTPClient:
    async def get_json(...)
    async def post_json(...)
    async def close(...)
```

TODO 注释必须说明：

```text
TODO: 替换真实 base_url
TODO: 替换真实鉴权方式
TODO: 补充生产级重试、熔断和审计
TODO: 补充字段脱敏策略
```

### knowledge_api_client.py

未来用于替换 `InMemoryKnowledgeService`。

必须提供：

```python
async def search(query: str, top_k: int, request_id: str | None, trace_id: str | None) -> list[dict]
async def pre_search(query: str, intent: str, top_k: int, request_id: str | None, trace_id: str | None) -> list[dict]
```

返回结构对齐当前 `KnowledgeChunk`：

```text
content
source
score
metadata
```

### log_api_client.py

未来用于替换 `query_internal_log`。

必须提供：

```python
async def query_internal_log(request_id: str, trace_id: str | None = None) -> dict
```

TODO 注释说明未来接日志平台、网关日志、链路日志字段映射。

### partner_trace_api_client.py

未来用于替换 fake MCP tool `partner_trace.get_request_detail` 或作为真实 MCP server 背后的外部 API client。

必须提供：

```python
async def get_request_detail(request_id: str, trace_id: str | None = None) -> dict
```

返回结构应兼容当前 FakeMCPConnector 返回。

### mcp_http_client.py

未来用于替换 `FakeMCPConnector`。

必须提供：

```python
async def list_tools(request_id: str | None = None, trace_id: str | None = None) -> list[dict]
async def call_tool(tool_name: str, arguments: dict, request_id: str | None = None, trace_id: str | None = None) -> dict
```

TODO 注释说明真实 MCP 协议、鉴权、工具 schema 映射位置。

### llm_api_client_example.py

未来用于真实 LLM Provider 的底层 API 示例。

必须提供：

```python
async def chat(messages: list[dict], request_id: str | None = None, trace_id: str | None = None) -> str
async def chat_json(messages: list[dict], request_id: str | None = None, trace_id: str | None = None) -> dict
```

默认不替换 `FakeLLMProvider` 或现有 OpenAI-compatible Provider。

### long_term_memory_api_client.py

未来用于替换 `LongTermMemoryManager` stub。

必须提供：

```python
async def retrieve(...)
async def extract_and_update(...)
```

TODO 注释说明未来接 PostgreSQL / Milvus / 记忆治理服务的位置。

### audit_api_client.py

未来用于替换本地 SQLite tool audit。

必须提供：

```python
async def write_tool_call_log(payload: dict, request_id: str | None = None, trace_id: str | None = None) -> dict
async def query_tool_call_logs(session_key: str, request_id: str | None = None, trace_id: str | None = None) -> list[dict]
```

默认不替换当前 `ToolCallLogStore`。

### checkpoint_backend_examples.py

未来用于替换项目内 SQLite checkpoint store。

必须包含示例类或函数：

```python
class PostgreSQLCheckpointBackendExample: ...
class RedisCheckpointBackendExample: ...
```

要求：

1. 代码示例完整
2. 默认不连接真实 PostgreSQL / Redis
3. TODO 注释说明真实连接池、序列化、事务、并发控制位置

### vector_search_api_client.py

未来用于替换内存知识检索。

必须提供：

```python
async def search_vectors(query: str, top_k: int, filters: dict | None = None, request_id: str | None = None, trace_id: str | None = None) -> list[dict]
async def keyword_search(query: str, top_k: int, filters: dict | None = None, request_id: str | None = None, trace_id: str | None = None) -> list[dict]
```

TODO 注释说明未来 Milvus / Elasticsearch / OpenSearch 的替换点。

### insurance_core_api_client.py

未来用于保险核心系统能力。

必须提供示例方法：

```python
async def get_policy(policy_no: str, request_id: str | None = None, trace_id: str | None = None) -> dict
async def get_product(product_code: str, request_id: str | None = None, trace_id: str | None = None) -> dict
async def validate_proposal(payload: dict, request_id: str | None = None, trace_id: str | None = None) -> dict
```

必须明确 TODO：

```text
TODO: 未来接真实保险核心系统前必须增加鉴权、审批、脱敏、审计和只读限制
```

### observability_api_client.py

未来用于替换当前 Runtime Execution Logging 或接入 OpenTelemetry / 内部观测平台。

必须提供：

```python
async def emit_event(event: dict, request_id: str | None = None, trace_id: str | None = None) -> dict
async def emit_trace_span(span: dict, request_id: str | None = None, trace_id: str | None = None) -> dict
```

默认不接真实 OpenTelemetry。

---

## 测试要求

新增测试：

```text
tests/test_integration_clients.py
```

必须测试：

1. 所有 integration client 可以 import
2. 默认配置下不会真实请求外部系统
3. BaseIntegrationHTTPClient 能构造 request headers，包含 request_id / trace_id
4. API client 方法在未配置 base_url 时抛出清晰错误
5. 敏感字段脱敏函数能处理 token、secret、password
6. client 方法签名包含 request_id / trace_id
7. 现有所有测试继续通过

不得要求真实网络请求。

可以使用 `httpx.MockTransport` 测试成功和异常分支。

---

## README 更新要求

README.md 必须新增：

1. Future Real API Integration Examples 说明
2. `app/integrations/` 目录说明
3. 每个 client 对应当前哪个 mock/stub
4. 默认不启用真实外部请求说明
5. 如何未来替换：
   - InMemoryKnowledgeService
   - FakeMCPConnector
   - query_internal_log
   - partner_trace.get_request_detail
   - LongTermMemoryManager
   - SQLite checkpoint
   - SQLite tool audit
   - Runtime logging / OpenTelemetry
6. `request_id` / `trace_id` 透传说明
7. 脱敏和 TODO 边界说明

---

## 验收命令

完成后必须能运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

---

## 验收请求或验收标准

验收标准：

1. `/api/chat` 行为不变
2. 现有所有测试继续通过
3. 新增 integration client 测试通过
4. `app/integrations/` 下每个文件都有完整示例代码
5. 所有真实 API 示例默认不启用
6. 所有真实 API 示例支持 request_id / trace_id / timeout / 异常处理
7. README 明确说明当前仍然使用 mock/stub 主流程

