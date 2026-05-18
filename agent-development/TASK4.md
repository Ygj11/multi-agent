# TASK4.md

## 当前任务

基于当前已经完成并通过测试的 TASK1、TASK2、TASK3，实现第四阶段增强。

第四阶段目标：

```text
工具调用审计 + Trace + 结构化证据增强
```

当前系统已经具备：

1. FastAPI `/api/chat`
2. LangGraph StateGraph
3. SQLite MessageStore
4. ShortTermMemory 持久化
5. InMemoryKnowledgeService
6. FakeMCPConnector
7. ToolRegistry / PolicyGate / ToolBroker
8. TroubleshootingAgent 调用 `query_internal_log`、`get_knowledge`、`partner_trace.get_request_detail`
9. 现有测试全部通过

TASK4 要把当前系统从“能回答”升级为：

```text
工具调用可审计
证据链可回放
问题排查结果结构化
```

本轮仍然是本地 MVP，不接真实审计系统、OpenTelemetry、真实 MCP Server、Milvus、Redis 或保险核心系统。

---

## 1. 第四阶段目标

第四阶段要实现：

1. 所有工具调用都有 SQLite 审计日志
2. 工具调用成功、失败、被 PolicyGate 拒绝都必须记录
3. MCP 工具调用也必须纳入同一审计链路
4. shell_exec 默认被拒绝时也必须写入审计日志
5. TroubleshootingAgent 不只拼接 answer，还要输出结构化 evidence
6. graph final state 或 subagent_result 中可以读取结构化 evidence
7. `/api/chat` 核心响应字段保持向后兼容
8. TASK1/TASK2/TASK3 的所有已有测试继续通过

目标不是实现完整生产审计平台，而是在 SQLite 本地实现可测试、可回放的审计雏形。

---

## 2. 本轮必须实现的内容

必须实现：

1. 新增 SQLite 表 `tool_call_logs`
2. 新增或扩展数据库初始化逻辑
3. 新增 ToolCallLog 存储组件，建议命名为 `ToolCallLogStore`
4. `ToolBroker` 每次工具调用都写入 `tool_call_logs`
5. `ToolCall` schema 补充：
   - `request_id`
   - `trace_id`
   - `session_key`
6. LangGraph state 将 `request_id`、`trace_id`、`session_key` 传递到 ToolCall
7. `ToolBroker` 成功调用工具时写入审计日志
8. `ToolBroker` 工具执行异常时写入审计日志
9. `PolicyGate` 拒绝工具调用时也写入审计日志
10. `shell_exec` 默认被拒绝时也写入审计日志
11. MCP 工具 `partner_trace.get_request_detail` 调用也必须写入审计日志
12. `TroubleshootingAgent` 返回结构化 evidence
13. `SubAgentResult` 扩展为可表达：
    - `diagnosis`
    - `evidence`
    - `recommendation`
    - `responsibility`
    - `confidence`
14. `/api/chat` 响应可以暂不暴露完整 evidence，但必须保持核心响应字段不变
15. 测试中必须能读取 graph final state 或 `subagent_result` 中的 evidence
16. README 增加 tool audit 和 structured evidence 说明
17. 保持所有已有测试继续通过

---

## 3. 本轮不要实现的内容

本轮不要实现：

1. 真实审计系统
2. OpenTelemetry
3. 前端 trace 页面
4. 真实 MCP Server
5. 真实 Milvus
6. 真实 Elasticsearch
7. 真实 Redis
8. 真实保险核心系统
9. 复杂权限系统
10. 真实长期记忆
11. 生产级脱敏引擎
12. 复杂审计报表
13. 分布式 trace
14. 真实用户登录鉴权
15. 改变 `/api/chat` 现有核心响应格式

---

## 4. tool_call_logs SQLite 表设计

必须新增 SQLite 表：

```text
tool_call_logs
```

字段至少包含：

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
request_id TEXT,
trace_id TEXT,
session_key TEXT,
tool_name TEXT NOT NULL,
arguments_json TEXT NOT NULL,
allowed INTEGER NOT NULL,
success INTEGER NOT NULL,
result_json TEXT,
error TEXT,
started_at TEXT NOT NULL,
finished_at TEXT NOT NULL,
duration_ms INTEGER NOT NULL,
created_at TEXT NOT NULL
```

索引建议：

```sql
CREATE INDEX IF NOT EXISTS idx_tool_call_logs_session_created
ON tool_call_logs(session_key, created_at);

CREATE INDEX IF NOT EXISTS idx_tool_call_logs_trace
ON tool_call_logs(trace_id);

CREATE INDEX IF NOT EXISTS idx_tool_call_logs_request
ON tool_call_logs(request_id);
```

要求：

1. 数据库初始化必须幂等
2. 测试必须使用临时 SQLite 文件
3. 不要求引入 ORM
4. 优先继续使用当前 `sqlite3` 轻量封装
5. `arguments_json` 和 `result_json` 必须是合法 JSON 字符串
6. 对不可 JSON 序列化对象，要做安全 fallback
7. 不得记录明显敏感原文，例如完整 secret、token、password

---

## 5. ToolCall schema 扩展要求

当前 `ToolCall` 至少包含：

```python
name: str
arguments: dict
session_key: str | None
```

第四阶段必须扩展为：

```python
class ToolCall(BaseModel):
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    request_id: str | None = None
    trace_id: str | None = None
    session_key: str | None = None
```

要求：

1. 保持向后兼容，已有测试中未传 `request_id` / `trace_id` 的调用不能失败
2. `TroubleshootingAgent` 创建 ToolCall 时必须传入：
   - request_id
   - trace_id
   - session_key
3. 如果 ToolCall 缺少 request_id 或 trace_id，ToolBroker 仍要写审计日志，但字段可以为 null

---

## 6. ToolBroker 审计增强要求

`ToolBroker` 必须接入 `ToolCallLogStore`。

建议新增：

```text
app/tools/audit_store.py
```

或：

```text
app/audit/tool_call_log_store.py
```

`ToolBroker` 初始化建议：

```python
class ToolBroker:
    def __init__(
        self,
        registry: ToolRegistry,
        policy_gate: PolicyGate,
        audit_store: ToolCallLogStore | None = None,
    ) -> None:
        ...
```

要求：

1. 每次 `ToolBroker.call(...)` 都记录 started_at
2. 调用结束记录 finished_at
3. 计算 duration_ms
4. 工具不存在也要写审计日志
5. PolicyGate 拒绝也要写审计日志
6. 工具执行成功要写审计日志
7. 工具执行异常要写审计日志
8. 审计失败不得中断主业务流程，但测试中应能发现审计写入成功
9. ToolBroker 返回的 ToolResult 行为保持向后兼容

---

## 7. PolicyGate 拒绝调用时的审计要求

PolicyGate 本身只负责判断是否允许，不直接写数据库。

审计写入应由 ToolBroker 统一完成。

当 PolicyGate 返回拒绝时，ToolBroker 必须写入：

```text
allowed = false
success = false
error = 拒绝原因
```

必须覆盖：

1. 未授权工具
2. 未注册工具
3. shell_exec 默认禁用
4. shell_exec 命令不在 allowlist

---

## 8. MCP 工具调用审计要求

MCP 工具必须继续通过：

```text
ToolBroker -> PolicyGate -> MCP tool wrapper -> FakeMCPConnector
```

`partner_trace.get_request_detail` 调用必须写入 `tool_call_logs`。

日志字段要求：

```text
tool_name = partner_trace.get_request_detail
allowed = true
success = true
arguments_json 包含 request_id
result_json 包含 found、request_id、summary 等可回放信息
session_key = 当前 session_key
request_id = 当前请求 request_id
trace_id = 当前请求 trace_id
```

如果 FakeMCPConnector 返回未知工具或异常：

1. ToolBroker 必须记录审计日志
2. `success` 应能体现调用失败
3. `error` 应保存失败原因

---

## 9. shell_exec 拒绝和执行审计要求

shell_exec 当前默认禁用，本轮必须保证：

1. 默认禁用时调用 shell_exec 会写入 `tool_call_logs`
2. `allowed=false`
3. `success=false`
4. `error` 包含 disabled 或等价拒绝原因

当 `ENABLE_SHELL_EXEC=true` 且命令在 allowlist 中：

1. `allowed=true`
2. `success=true`
3. `result_json` 保存 stdout/stderr/returncode
4. `duration_ms` 有值

当命令不在 allowlist：

1. `allowed=false`
2. `success=false`
3. `error` 包含 allowlist 或等价拒绝原因

不得因为审计增强放宽 shell_exec 安全边界。

---

## 10. TroubleshootingAgent 结构化 evidence 输出要求

`TroubleshootingAgent` 当前已经调用内部日志、知识库和 MCP trace。

第四阶段必须将 evidence 结构化。

每条 evidence 至少包含：

```text
type
source
tool_name
summary
raw_ref 或 result_preview
confidence
```

建议结构：

```json
{
  "type": "internal_log",
  "source": "query_internal_log",
  "tool_name": "query_internal_log",
  "summary": "内部日志显示 REQ_001 在 submitProposal 返回 E102，疑似渠道签名未包含 timestamp。",
  "result_preview": {
    "request_id": "REQ_001",
    "error_code": "E102",
    "interface_name": "submitProposal"
  },
  "confidence": 0.9
}
```

必须至少包含三类证据：

1. 内部日志证据
2. 知识库证据
3. 渠道侧 trace 证据

对 REQ_001：

1. 内部日志证据应来自 `query_internal_log`
2. 知识库证据应来自 `get_knowledge`
3. 渠道侧 trace 证据应来自 `partner_trace.get_request_detail`

---

## 11. LangGraph state 如何传递 request_id / trace_id / session_key

当前 graph state 已包含：

```text
request_id
trace_id
session_key
```

第四阶段要求：

1. `call_troubleshooting_agent` 构造 `SubAgentTask` 时必须把 request_id、trace_id 放入 task metadata
2. `TroubleshootingAgent` 创建每个 ToolCall 时必须传：
   - request_id
   - trace_id
   - session_key
3. `ToolBroker` 使用 ToolCall 中的这些字段写审计
4. graph final state 中保留 `subagent_result`
5. 测试必须能从 final state 中读取 evidence

建议 `SubAgentTask.metadata`：

```json
{
  "request_id": "...",
  "trace_id": "..."
}
```

---

## 12. /api/chat 是否暴露 evidence 的设计要求

本阶段 `/api/chat` 可以暂不暴露完整 evidence。

必须保持现有核心响应字段不变：

```text
request_id
session_key
original_query
rewritten_query
intent
answer
```

允许向后兼容地新增可选字段，例如：

```text
evidence_summary
```

但不强制。

要求：

1. 不能移除或重命名现有字段
2. 不能破坏已有 API 测试
3. 完整 evidence 至少要存在于 graph final state 的 `subagent_result`
4. 如果暴露 evidence，必须避免输出敏感原始数据

---

## 13. 需要新增或修改的文件列表

建议新增：

```text
app/tools/audit_store.py
```

或：

```text
app/audit/
  __init__.py
  tool_call_log_store.py
```

可能修改：

```text
app/storage/sqlite.py
app/schemas/tool.py
app/schemas/subagent.py
app/tools/broker.py
app/tools/policy_gate.py
app/subagents/troubleshooting_agent.py
app/runtime/graph.py
app/main.py
app/adapters/response_adapter.py
README.md
```

新增或修改测试：

```text
tests/test_tool_call_audit.py
tests/test_troubleshooting_evidence.py
tests/test_chat_troubleshooting.py
tests/test_mcp_tool_broker.py
tests/test_shell_exec_tool.py
```

---

## 14. 测试要求

必须保持所有已有测试继续通过。

新增或增强测试：

1. ToolBroker 成功调用 `query_internal_log` 会写入 `tool_call_logs`
2. ToolBroker 成功调用 `get_knowledge` 会写入 `tool_call_logs`
3. ToolBroker 成功调用 `partner_trace.get_request_detail` 会写入 `tool_call_logs`
4. PolicyGate 拒绝 `shell_exec` 时也会写入 `tool_call_logs`
5. shell_exec allowlist 命令执行成功时会写入 `tool_call_logs`
6. shell_exec 非 allowlist 命令被拒绝时会写入 `tool_call_logs`
7. `/api/chat` 一次 `REQ_001` 后，SQLite 中至少有三条 tool log：
   - `query_internal_log`
   - `get_knowledge`
   - `partner_trace.get_request_detail`
8. 不同 session_key 的 tool logs 隔离
9. `tool_call_logs.arguments_json` 不应包含明文敏感数据
10. `TroubleshootingAgent` 对 `REQ_001` 返回结构化 evidence
11. evidence 中应包含内部日志证据、知识库证据、渠道侧 trace 证据
12. graph final state 的 `subagent_result` 中能读取 evidence
13. 所有已有 TASK1/TASK2/TASK3 测试继续通过

敏感数据测试建议：

```text
arguments_json 不包含 secret
arguments_json 不包含 token
arguments_json 不包含 password
```

如果当前工具参数中没有敏感字段，也应实现最小脱敏函数并测试它对敏感 key 生效。

---

## 15. README 更新要求

README.md 必须新增：

1. 第四阶段 tool audit 说明
2. `tool_call_logs` 表说明
3. ToolBroker 审计链路说明
4. PolicyGate 拒绝也会记录审计的说明
5. MCP 工具调用审计说明
6. shell_exec 拒绝和执行审计说明
7. TroubleshootingAgent structured evidence 说明
8. 如何查询 SQLite tool_call_logs
9. `/api/chat` 核心响应保持兼容说明
10. 当前不接真实审计系统 / OpenTelemetry 的说明

必须继续保留：

1. 安装方式
2. 测试命令
3. 启动命令
4. curl 示例
5. LangGraph 状态机说明
6. SQLite 持久化说明
7. InMemoryKnowledgeService 说明
8. FakeMCPConnector 说明
9. shell_exec 安全说明

---

## 16. 验收命令

完成后必须能运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

测试必须使用临时 SQLite 数据库，不得依赖或污染本地 `.data/agent_mvp.sqlite3`。

---

## 17. 验收请求

启动服务：

```bash
uv run uvicorn app.main:app --reload
```

请求：

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "pingan_health",
    "channel": "web",
    "user_id": "u001",
    "session_id": "s001",
    "messages": [
      {
        "role": "user",
        "content": "REQ_001 为什么返回 E102？"
      }
    ]
  }'
```

响应必须继续包含：

```text
request_id
session_key
original_query
rewritten_query
intent
answer
```

并且 answer 仍应包含：

```text
E102
签名校验失败
timestamp
渠道侧 trace
旧版签名规则 或 timestamp 未参与签名
```

SQLite 中必须能查询到当前请求对应的工具调用日志：

```text
query_internal_log
get_knowledge
partner_trace.get_request_detail
```

测试中必须能从 graph final state 或 `subagent_result` 读取结构化 evidence。

---

## 18. 当前不做的内容

第四阶段完成后，以下内容仍不做：

1. 不接真实审计系统
2. 不接 OpenTelemetry
3. 不做前端 trace 页面
4. 不接真实 MCP Server
5. 不接真实 Milvus
6. 不接真实 Elasticsearch
7. 不接真实 Redis
8. 不接真实保险核心系统
9. 不实现复杂权限系统
10. 不实现真实长期记忆
11. 不做生产级脱敏引擎
12. 不做复杂审计报表
13. 不做分布式 trace
14. 不保存真实客户、保单、健康告知或理赔数据
15. 不改变 `/api/chat` 现有核心响应格式，除非保持向后兼容

