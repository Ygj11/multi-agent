# TASK_log.md

## 当前任务

基于当前已经完成并通过测试的 MVP，新增 Runtime Execution Logging。

本阶段目标不是生产级审计系统，而是让开发者可以通过日志清楚看到一次 `/api/chat` 请求从入口到最终响应经过了哪些模块、每一步输入输出摘要是什么、最终走了哪个子 Agent、调用了哪些工具、返回了什么结果。

本阶段不替代 TASK4 的 `tool_call_logs` SQLite 审计表。TASK4 关注可持久化审计和证据回放；本阶段关注运行时链路日志和开发调试可观测性。

---

## 1. 第四阶段目标

实现从请求入口到最终响应的运行时执行链路日志。

一次 `/api/chat` 请求，日志中至少能看到：

1. `request_received`
2. `request_adapted`
3. `session_key_created`
4. `session_loaded`
5. `user_message_saved`
6. `original_query`
7. `query_rewrite_started`
8. `query_rewrite_finished`
9. `intent_recognition_started`
10. `intent_recognition_finished`
11. `memory_context_loaded`
12. `knowledge_hint_loaded`
13. `orchestrator_context_built`
14. `langgraph_node_enter`
15. `langgraph_node_exit`
16. `route_decision`
17. `subagent_selected`
18. `troubleshooting_started`
19. `tool_call_requested`
20. `policy_gate_checked`
21. `tool_call_started`
22. `tool_call_finished`
23. `mcp_call_started`
24. `mcp_call_finished`
25. `evidence_built`
26. `assistant_message_saved`
27. `short_memory_compressed`
28. `response_finalized`
29. `response_returned`

目标：

```text
通过日志看清一次请求的 Runtime 执行路径。
```

---

## 2. 本轮必须实现的内容

必须实现：

1. 新增统一 logger 工具
2. 使用 Python `logging`
3. 不使用 `print`
4. 提供 `log_event` 方法
5. 日志尽量结构化，建议 JSON line 风格
6. 所有关键节点通过 `log_event` 输出
7. `/api/chat` 入口和出口打日志
8. RequestAdapter 打日志
9. SessionManager / MessageStore 打日志
10. LangGraph 节点 enter/exit 打日志
11. QueryRewriteNode 打 started/finished 日志
12. IntentRecognitionNode 打 started/finished 日志
13. ContextBuilder 打 knowledge hints 和 context built 日志
14. SubAgentManager 打 subagent selected 日志
15. TroubleshootingAgent 打 started、tool evidence、evidence built 日志
16. ToolBroker 打 tool call requested/started/finished 日志
17. PolicyGate 打 policy_gate_checked 日志
18. KnowledgeService 打 search/pre_search 日志
19. MCPConnector/FakeMCPConnector 打 MCP call started/finished 日志
20. ShortTermMemoryManager 打 compressed 日志
21. response finalized/returned 日志
22. 日志 data 字段必须脱敏
23. 保持当前所有测试继续通过
24. 新增测试验证关键日志事件出现
25. README 增加 Runtime Execution Logging 说明

建议新增文件：

```text
app/observability/
  __init__.py
  logger.py
```

---

## 3. 本轮不要实现的内容

本轮不要实现：

1. 不接 OpenTelemetry
2. 不接真实审计平台
3. 不接 ELK / Loki / Splunk
4. 不做分布式 trace
5. 不做前端日志查看页面
6. 不做复杂日志采样
7. 不做生产级脱敏引擎
8. 不改造为异步日志队列
9. 不改变 `/api/chat` 核心响应格式
10. 不接真实 MCP Server
11. 不接真实 Milvus
12. 不接真实 Redis
13. 不接真实保险核心系统

---

## 4. 日志格式设计

使用 Python `logging`。

建议输出 JSON line 风格，每条日志是一个 JSON 对象字符串。

示例：

```json
{
  "timestamp": "2026-05-16T10:00:00.000Z",
  "level": "INFO",
  "event": "query_rewrite_finished",
  "request_id": "req_xxx",
  "trace_id": "trace_xxx",
  "session_key": "pingan_health:web:u001:s001",
  "user_id": "u001",
  "tenant_id": "pingan_health",
  "node": "query_rewrite",
  "message": "Query rewrite finished",
  "data": {
    "rewritten_query_preview": "排查 requestId=REQ_001 的健康险个险接口 E102 错误原因"
  }
}
```

要求：

1. 每条日志必须是单行
2. `data` 必须是 dict
3. data 中只放摘要
4. 不输出完整敏感字段
5. JSON 序列化失败时要安全降级为字符串摘要

---

## 5. 日志字段设计

日志字段至少包含：

```text
timestamp
level
event
request_id
trace_id
session_key
user_id
tenant_id
node
message
data
```

字段说明：

| 字段 | 说明 |
|---|---|
| timestamp | UTC ISO 时间 |
| level | INFO / WARNING / ERROR |
| event | 机器可读事件名 |
| request_id | 当前请求 id |
| trace_id | 当前链路 id |
| session_key | 多用户多会话隔离键 |
| user_id | 用户 id |
| tenant_id | 租户 id |
| node | 当前模块或 LangGraph 节点 |
| message | 人类可读短消息 |
| data | 脱敏后的结构化摘要 |

可选字段：

```text
channel
session_id
tool_name
subagent_name
duration_ms
```

---

## 6. 日志打印位置设计

所有关键日志必须通过统一方法：

```python
log_event(...)
```

建议接口：

```python
def log_event(
    event: str,
    *,
    level: str = "INFO",
    request_id: str | None = None,
    trace_id: str | None = None,
    session_key: str | None = None,
    user_id: str | None = None,
    tenant_id: str | None = None,
    node: str | None = None,
    message: str = "",
    data: dict | None = None,
) -> None:
    ...
```

也可以支持 `context` 参数，但必须保证日志字段完整。

不得到处手写 logging JSON 拼接。

---

## 7. LangGraph 节点日志要求

每个 LangGraph 节点必须至少打：

```text
langgraph_node_enter
langgraph_node_exit
```

节点包括：

1. `load_session`
2. `save_user_message`
3. `query_rewrite`
4. `intent_recognition`
5. `build_orchestrator_context`
6. `route_intent`
7. `call_troubleshooting_agent`
8. `direct_answer`
9. `save_assistant_message`
10. `compress_short_memory`
11. `finalize_response`

`route_intent` 必须额外输出：

```text
route_decision
```

data 示例：

```json
{
  "intent": "troubleshooting",
  "next_node": "call_troubleshooting_agent"
}
```

---

## 8. QueryRewriteNode 日志要求

必须输出：

```text
query_rewrite_started
query_rewrite_finished
original_query
```

data 至少包含：

```text
original_query_preview
rewritten_query_preview
used_short_summary
recent_message_count
```

不能输出完整敏感长文本。

---

## 9. IntentRecognitionNode 日志要求

必须输出：

```text
intent_recognition_started
intent_recognition_finished
```

data 至少包含：

```text
intent
confidence
target_subagent
required_tools
used_short_summary
recent_message_count
```

---

## 10. ContextBuilder 日志要求

必须输出：

```text
memory_context_loaded
knowledge_hint_loaded
orchestrator_context_built
```

`build_for_subagent` 建议输出：

```text
subagent_context_built
```

data 至少包含：

```text
recent_message_count
has_short_summary
knowledge_hint_count
available_subagents
available_tools
allowed_tools
skill_name
```

---

## 11. SubAgentManager 日志要求

调用子 Agent 前必须输出：

```text
subagent_selected
```

data 至少包含：

```text
subagent_name
intent
session_key
```

如果子 Agent 不存在，必须输出 WARNING 或 ERROR 级别日志。

---

## 12. TroubleshootingAgent 日志要求

必须输出：

```text
troubleshooting_started
evidence_built
```

建议输出：

```text
troubleshooting_finished
```

data 至少包含：

```text
request_id_in_task
tool_sequence
evidence_count
evidence_types
diagnosis_preview
responsibility_preview
```

工具调用本身由 ToolBroker 输出，不需要在 TroubleshootingAgent 重复输出完整结果。

---

## 13. ToolBroker 日志要求

每次调用必须输出：

```text
tool_call_requested
tool_call_started
tool_call_finished
```

如果工具不存在：

```text
tool_call_finished
```

level 应为 WARNING。

data 至少包含：

```text
tool_name
allowed
success
error
duration_ms
arguments_preview
result_preview
```

---

## 14. PolicyGate 日志要求

每次策略判断必须输出：

```text
policy_gate_checked
```

data 至少包含：

```text
tool_name
allowed
reason
shell_exec_enabled
```

对于 shell_exec：

```text
command_preview
```

不得输出危险命令完整长参数或敏感路径。

---

## 15. KnowledgeService 日志要求

`search` 和 `pre_search` 必须输出：

```text
knowledge_search_started
knowledge_search_finished
```

或：

```text
knowledge_presearch_started
knowledge_presearch_finished
```

data 至少包含：

```text
query_preview
top_k
hit_count
sources
```

---

## 16. MCPConnector 日志要求

`FakeMCPConnector.call_tool` 必须输出：

```text
mcp_call_started
mcp_call_finished
```

data 至少包含：

```text
tool_name
request_id
found
summary_preview
```

`list_tools` 可输出：

```text
mcp_list_tools
```

---

## 17. MessageStore / SessionManager 日志要求

SessionManager 必须输出：

```text
session_loaded
memory_context_loaded
```

MessageStore 必须输出：

```text
user_message_saved
assistant_message_saved
```

data 至少包含：

```text
session_key
role
content_preview
recent_message_count
has_short_summary
```

---

## 18. ShortTermMemoryManager 日志要求

每次压缩后必须输出：

```text
short_memory_compressed
```

data 至少包含：

```text
session_key
summary_preview
intent
```

---

## 19. /api/chat 请求入口和响应出口日志要求

请求入口必须输出：

```text
request_received
```

RequestAdapter 完成后必须输出：

```text
request_adapted
session_key_created
original_query
```

响应前必须输出：

```text
response_finalized
response_returned
```

data 至少包含：

```text
tenant_id
channel
user_id
session_id
session_key
message_count
original_query_preview
answer_preview
intent
```

---

## 20. 敏感信息脱敏要求

日志 data 只允许放脱敏摘要。

必须脱敏的字段名：

```text
password
secret
token
api_key
authorization
id_card
phone
mobile
bank_card
health_info
medical_record
```

要求：

1. 默认只输出 preview，不输出完整长文本
2. preview 建议限制在 120 字以内
3. 对 dict/list 递归脱敏
4. 对未知对象安全转字符串并截断
5. 不输出完整签名、密钥、token
6. 不输出真实客户个人信息

建议在 `app/observability/logger.py` 中实现：

```python
sanitize_data(data: Any) -> Any
preview_text(text: str, limit: int = 120) -> str
```

---

## 21. 测试要求

必须保持现有所有测试继续通过。

新增测试建议：

```text
tests/test_runtime_logging.py
```

必须测试：

1. `/api/chat` 一次 `REQ_001 为什么返回 E102？` 后日志中包含：
   - `request_received`
   - `request_adapted`
   - `session_key_created`
   - `session_loaded`
   - `query_rewrite_started`
   - `query_rewrite_finished`
   - `intent_recognition_started`
   - `intent_recognition_finished`
   - `orchestrator_context_built`
   - `route_decision`
   - `subagent_selected`
   - `troubleshooting_started`
   - `tool_call_requested`
   - `policy_gate_checked`
   - `tool_call_started`
   - `tool_call_finished`
   - `mcp_call_started`
   - `mcp_call_finished`
   - `evidence_built`
   - `assistant_message_saved`
   - `short_memory_compressed`
   - `response_finalized`
   - `response_returned`
2. 日志使用 Python logging 捕获，不检查 print
3. 日志中有 request_id、trace_id、session_key
4. 日志 data 不包含明文 `secret`、`token`、`password`
5. ToolBroker 调用 shell_exec 被拒绝时也产生日志：
   - `tool_call_requested`
   - `policy_gate_checked`
   - `tool_call_finished`
6. KnowledgeService search 产生日志
7. FakeMCPConnector call_tool 产生日志

可以使用 pytest `caplog` 捕获日志。

---

## 22. README 更新要求

README.md 必须新增：

1. Runtime Execution Logging 说明
2. 日志格式说明
3. 关键 event 列表
4. 如何通过日志观察一次 `/api/chat` 请求链路
5. 日志脱敏说明
6. 本阶段不是生产级审计系统的说明
7. 与 `tool_call_logs` SQLite 审计表的区别

必须继续保留：

1. 安装方式
2. 测试命令
3. 启动命令
4. SQLite 持久化说明
5. Tool audit 说明
6. InMemoryKnowledgeService 说明
7. FakeMCPConnector 说明
8. shell_exec 安全说明

---

## 23. 验收命令

完成后必须能运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

---

## 24. 验收请求

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

响应仍必须包含：

```text
request_id
session_key
original_query
rewritten_query
intent
answer
```

控制台日志中应能看到完整链路：

```text
request_received
request_adapted
session_loaded
query_rewrite_started
query_rewrite_finished
intent_recognition_started
intent_recognition_finished
route_decision
subagent_selected
troubleshooting_started
tool_call_requested
policy_gate_checked
tool_call_finished
mcp_call_started
mcp_call_finished
evidence_built
assistant_message_saved
short_memory_compressed
response_returned
```

