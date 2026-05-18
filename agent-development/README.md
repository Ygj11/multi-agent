# 健康险个险业务对接 Agent MVP

这是第三阶段增强版 MVP，用于验证健康险个险业务对接 Agent 的核心运行时思想：固定主干流程、主 Agent 协调、子 Agent 深度执行、工具调用受控、多用户多会话隔离、SQLite 本地持久化、InMemory RAG 雏形和 Fake MCP 外部能力雏形。

## 架构简图

```text
FastAPI /api/chat
-> RequestAdapter
-> AgentOrchestrator
-> LangGraph StateGraph
   -> load_session
   -> save_user_message
   -> query_rewrite
   -> intent_recognition
   -> build_orchestrator_context
   -> route_intent
      -> troubleshooting: call_troubleshooting_agent
      -> other: direct_answer
   -> save_assistant_message
   -> compress_short_memory
   -> finalize_response
-> ResponseAdapter

TroubleshootingAgent
-> query_internal_log 内部日志
-> get_knowledge / InMemoryKnowledgeService 知识依据
-> partner_trace.get_request_detail / FakeMCPConnector 渠道侧 trace
-> 汇总内部证据、知识依据、渠道侧证据、初步归属和建议动作
```

## 安装方式

```bash
uv sync
```

## 测试命令

```bash
uv run pytest
```

## 启动命令

```bash
uv run uvicorn app.main:app --reload
```

## SQLite 本地持久化

第二阶段默认使用 SQLite 保存消息、短期记忆和项目内 checkpoint。

默认数据库路径：

```text
.data/agent_mvp.sqlite3
```

可以通过环境变量修改：

```powershell
$env:SQLITE_DB_PATH="D:\tmp\agent_mvp.sqlite3"
```

数据库初始化由 `app/storage/sqlite.py` 幂等完成，目录不存在时会自动创建。

当前表：

```text
messages
short_term_memory
graph_checkpoints
tool_call_logs
```

`messages` 保存 user/assistant 消息和 metadata JSON；`short_term_memory` 保存每个 `session_key` 的 session_summary；`graph_checkpoints` 保存每个 `thread_id=session_key` 的最新 LangGraph state；`tool_call_logs` 保存每次工具调用审计记录。

清理本地开发数据：

```powershell
Remove-Item -LiteralPath ".data\agent_mvp.sqlite3" -Force
```

## Tool Audit

第四阶段新增工具调用审计。所有经过 `ToolBroker` 的工具调用都会写入 SQLite：

```text
tool_call_logs
```

字段包括：

```text
request_id
trace_id
session_key
tool_name
arguments_json
allowed
success
result_json
error
started_at
finished_at
duration_ms
created_at
```

覆盖范围：

```text
query_internal_log 成功调用
get_knowledge 成功调用
partner_trace.get_request_detail MCP 工具调用
shell_exec 默认拒绝
shell_exec allowlist 命令执行
shell_exec 非 allowlist 命令拒绝
未知工具或未授权工具拒绝
```

审计链路：

```text
ToolBroker
-> PolicyGate
-> ToolRegistry / Tool
-> ToolCallLogStore
-> SQLite tool_call_logs
```

PolicyGate 只负责允许或拒绝，审计写入统一由 ToolBroker 完成。即使 PolicyGate 拒绝调用，也会记录 `allowed=false`、`success=false` 和拒绝原因。

`arguments_json` 会对常见敏感字段做最小脱敏，例如：

```text
secret
token
password
api_key
authorization
```

查询示例：

```powershell
sqlite3 .data\agent_mvp.sqlite3 "select tool_name, allowed, success, error from tool_call_logs order by id;"
```

## Runtime Execution Logging

当前阶段新增 Runtime Execution Logging，用于开发时观察一次 `/api/chat` 请求从入口到最终响应的执行链路。它和 `tool_call_logs` 不同：

```text
Runtime Execution Logging -> 控制台结构化日志，帮助开发调试链路
tool_call_logs            -> SQLite 持久化审计，帮助回放工具调用
```

日志使用 Python `logging`，统一入口在：

```text
app/observability/logger.py
```

所有关键模块通过 `log_event(...)` 输出 JSON line 风格日志。字段包括：

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

一次 `REQ_001 为什么返回 E102？` 请求中，可以看到类似事件：

```text
request_received
request_adapted
session_key_created
session_loaded
query_rewrite_started
query_rewrite_finished
intent_recognition_started
intent_recognition_finished
memory_context_loaded
knowledge_hint_loaded
orchestrator_context_built
langgraph_node_enter
langgraph_node_exit
route_decision
subagent_selected
troubleshooting_started
tool_call_requested
policy_gate_checked
tool_call_started
tool_call_finished
mcp_call_started
mcp_call_finished
evidence_built
assistant_message_saved
short_memory_compressed
response_finalized
response_returned
```

日志 data 只放摘要，并会递归脱敏常见敏感字段：

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

本阶段不接 OpenTelemetry、不接真实审计平台、不做分布式 trace。生产级可观测后续可以在 `log_event` 外层替换或扩展。

## InMemoryKnowledgeService

第三阶段新增独立知识服务：

```text
app/knowledge/service.py
app/knowledge/in_memory_service.py
```

`KnowledgeService` 是抽象接口，`InMemoryKnowledgeService` 是当前默认实现。它只做本地 keyword search，不接 Milvus、Elasticsearch，也不做 embedding。

内置 mock knowledge 包括：

```text
E102 签名校验失败
submitProposal 接口说明
timestamp 参与签名规则
密钥版本不一致
字段排序不一致
空值字段处理不一致
```

知识片段返回结构包含：

```text
content
source
score
metadata
```

`ContextBuilder.build_for_orchestrator()` 会调用 KnowledgeService 生成 `lightweight_knowledge_hints`，主干流程只使用轻量提示，不加载复杂 RAG 上下文。

## get_knowledge Tool

`get_knowledge` 仍是 ToolRegistry 中的内部 tool，但已改为调用 `KnowledgeService`。

调用路径：

```text
TroubleshootingAgent
-> ToolBroker
-> PolicyGate
-> get_knowledge
-> InMemoryKnowledgeService.search()
```

这样知识检索仍然受 ToolBroker / PolicyGate 管控。

## FakeMCPConnector

第三阶段保留 `MCPConnector` 抽象，并新增：

```text
app/mcp/fake_connector.py
```

当前 fake MCP tool：

```text
partner_trace.get_request_detail
```

能力：

```text
REQ_001 -> 渠道侧 trace 显示仍使用旧版 v1 签名规则，签名原文未包含 timestamp
REQ_002 -> 渠道侧 trace 显示 timestamp 过期或渠道侧时间窗口异常
未知 requestId -> found=false
```

MCP 工具不会被子 Agent 直接调用，而是通过 wrapper 注册进 ToolRegistry：

```text
ToolBroker -> PolicyGate -> partner_trace.get_request_detail wrapper -> FakeMCPConnector.call_tool()
```

MCP 工具调用同样写入 `tool_call_logs`。对 `REQ_001`，日志中会记录 `partner_trace.get_request_detail` 的调用参数和渠道侧 trace 结果摘要。

## Structured Evidence

`TroubleshootingAgent` 现在不仅生成 answer，还会在 graph final state 的 `subagent_result` 中返回结构化证据。

`subagent_result` 至少包含：

```text
diagnosis
evidence
recommendation
responsibility
confidence
```

每条 evidence 至少包含：

```text
type
source
tool_name
summary
result_preview
confidence
```

对 `REQ_001`，结构化 evidence 会包含：

```text
internal_log      -> query_internal_log
knowledge         -> get_knowledge / InMemoryKnowledgeService
partner_trace     -> partner_trace.get_request_detail / FakeMCPConnector
```

`/api/chat` 当前仍保持核心响应格式兼容，默认不暴露完整 evidence；测试和内部调用可以从 LangGraph final state 或 checkpoint 中读取 `subagent_result.evidence`。

## curl 验证示例

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

响应会包含：

```text
request_id
session_key
original_query
rewritten_query
intent
answer
```

对 `REQ_001 为什么返回 E102？`，`answer` 应包含：

```text
E102
签名校验失败
timestamp
渠道侧 trace
旧版签名规则 或 timestamp 未参与签名
```

其中 `session_key` 格式为：

```text
{tenant_id}:{channel}:{user_id}:{session_id}
```

## LangGraph 状态机流程说明

本项目使用真实 `langgraph.graph.StateGraph`，不是普通函数串联。节点包括：

```text
load_session
save_user_message
query_rewrite
intent_recognition
build_orchestrator_context
route_intent
call_troubleshooting_agent
direct_answer
save_assistant_message
compress_short_memory
finalize_response
```

条件路由：

```text
intent = troubleshooting -> call_troubleshooting_agent
intent != troubleshooting -> direct_answer
```

执行图时使用 `session_key` 作为 LangGraph config 的 `thread_id`：

```python
config = {
    "configurable": {
        "thread_id": session_key
    }
}
```

LangGraph 编译阶段当前仍使用 `MemorySaver`，同时项目内通过 `SQLiteCheckpointStore` 将每次图执行后的最终 state 持久化到 `graph_checkpoints` 表。这个类位于：

```text
app/runtime/checkpoint.py
```

它是后续替换官方 SQLite/PostgreSQL checkpointer 的清晰接入点。无论当前项目内 checkpoint store，还是未来官方 checkpointer，都必须继续使用 `thread_id=session_key` 隔离。

## 多轮对话说明

`MessageStore` 和 `ShortTermMemoryManager` 都以 `session_key` 为隔离键，并持久化到 SQLite。`SessionManager` 默认读取最近 30 轮消息，也就是最多 60 条 user/assistant 消息，并同时读取 `short_summary`。

第一轮：

```text
REQ_001 为什么返回 E102？
```

第二轮：

```text
那这个一般是谁的问题？
```

第二轮会从同一 `session_key` 的 recent messages 和 short summary 中恢复上一轮 E102 / requestId 上下文。即使重启服务，只要 SQLite 文件仍在，同一个 `session_key` 也可以继续多轮对话。

多用户隔离规则：

```text
u001 + s001 -> pingan_health:web:u001:s001
u002 + s001 -> pingan_health:web:u002:s001
```

不同 `session_key` 的 messages、summary 和 checkpoint 均不会互相读取。

## 真实 LLM 启用方式

默认使用 `FakeLLMProvider`，不依赖网络和 API key。

真实 OpenAI-compatible Provider 位于：

```text
app/llm/openai_provider.py
```

启用方式：

```bash
set ENABLE_REAL_LLM=true
set OPENAI_API_KEY=your_api_key
set OPENAI_BASE_URL=https://your-compatible-endpoint/v1
set OPENAI_MODEL=your-model
```

PowerShell 可使用：

```powershell
$env:ENABLE_REAL_LLM="true"
$env:OPENAI_API_KEY="your_api_key"
$env:OPENAI_BASE_URL="https://your-compatible-endpoint/v1"
$env:OPENAI_MODEL="your-model"
```

如果 `ENABLE_REAL_LLM=true` 但未安装 openai 或未配置 API key，会抛出清晰错误。默认测试不会启用真实 LLM。

## shell_exec 安全说明

`shell_exec` 已实现但默认禁用。

安全边界：

```text
默认禁用
必须 ENABLE_SHELL_EXEC=true 才允许
必须经过 PolicyGate 和 ToolBroker
不使用 shell=True
只允许 echo、pwd、ls
timeout 最多 5 秒
工作目录限制在项目根目录
拒绝 rm、curl、wget、ssh、scp 等高风险命令
```

启用示例：

```powershell
$env:ENABLE_SHELL_EXEC="true"
```

## HTTP / MCP HTTP 工具说明

当前除了 fake MCP wrapper，也提供可供子 Agent 后续调用真实接口的受控工具入口：

```text
http_request
mcp_http.call_tool
```

安全边界：

```text
默认禁用
必须 ENABLE_HTTP_TOOLS=true 才允许
必须经过 PolicyGate 和 ToolBroker
只允许 GET / POST
只允许 http / https URL
如配置 ALLOWED_HTTP_TOOL_HOSTS，则 host 必须命中白名单
timeout 不得超过 HTTP_TOOL_TIMEOUT，默认 5 秒
工具调用会进入 tool_call_logs 审计链路
```

启用示例：

```powershell
$env:ENABLE_HTTP_TOOLS="true"
$env:ALLOWED_HTTP_TOOL_HOSTS="api.example.internal,mcp.example.internal"
$env:HTTP_TOOL_TIMEOUT="5"
```

`http_request` 参数示例：

```json
{
  "method": "GET",
  "url": "https://api.example.internal/logs",
  "params": {"requestId": "REQ_001"}
}
```

`mcp_http.call_tool` 参数示例：

```json
{
  "base_url": "https://mcp.example.internal",
  "tool_name": "partner_trace.get_request_detail",
  "arguments": {"request_id": "REQ_001"}
}
```

当前排障主链路仍默认使用 `FakeMCPConnector`，不会主动调用真实 HTTP / MCP HTTP 接口。

## 当前 mock/stub 能力列表

## TASK5 真实 API 示例代码

本阶段新增 `app/integrations/`，为当前 mock/stub 能力提供未来真实 API 接入示例，但默认不启用、不会主动请求外部系统。

```text
base_http_client.py              统一 httpx client 示例，支持 request_id / trace_id、timeout、异常处理和脱敏
knowledge_api_client.py          未来替换 InMemoryKnowledgeService
log_api_client.py                未来替换 query_internal_log mock tool
partner_trace_api_client.py      未来替换 partner_trace.get_request_detail fake MCP tool
mcp_http_client.py               未来接真实 MCP HTTP 网关
llm_api_client_example.py        未来接真实模型服务示例，当前默认仍使用 FakeLLMProvider
long_term_memory_api_client.py   未来接长期记忆服务
audit_api_client.py              未来接真实审计平台
checkpoint_backend_examples.py   未来替换项目内 SQLite checkpoint store
vector_search_api_client.py      未来接 Milvus / Elasticsearch / OpenSearch
insurance_core_api_client.py     未来接保险核心系统
observability_api_client.py      未来接 OpenTelemetry collector 或内部观测平台
```

这些示例代码都保留 TODO，用来标注真实地址、真实鉴权、字段映射、脱敏和权限控制的替换点。当前主流程仍走本地 mock/stub，避免测试依赖外部环境。

## TASK6 固定子 Agent Catalog

当前通过 `SubAgentManager` 固定注册以下子 Agent，不支持自由 spawn：

```text
troubleshooting_agent
compliance_security_agent
document_parse_agent
change_impact_analysis_agent
```

新增子 Agent：

```text
compliance_security_agent
  检查手机号、身份证号、凭据、健康/医疗信息和外发风险，输出脱敏建议。

document_parse_agent
  解析 markdown / text / json / yaml 文档内容，提取标题、接口、字段、错误码和摘要。

change_impact_analysis_agent
  分析接口字段、错误码、签名规则、知识文档变更影响，必要时通过 get_knowledge 查询 mock 知识库。
```

每个子 Agent 都有输入 schema、输出 schema，并且必须经由 LangGraph 条件路由和 `SubAgentManager` 调用。需要工具时仍通过 `ToolBroker / PolicyGate`，本阶段没有引入策略治理和工具元数据化。

### 多 Skill 动态选择

当前已经支持“一个子 Agent 拥有多个 skills，并按请求上下文动态选择一个 skill”。

目录结构示例：

```text
app/skills/troubleshooting_agent/signature_error/SKILL.md
app/skills/troubleshooting_agent/missing_field/SKILL.md
app/skills/troubleshooting_agent/callback_failure/SKILL.md

app/skills/compliance_security_agent/privacy_check/SKILL.md
app/skills/compliance_security_agent/external_message_review/SKILL.md
app/skills/compliance_security_agent/sensitive_data_redaction/SKILL.md

app/skills/document_parse_agent/api_doc_parse/SKILL.md
app/skills/document_parse_agent/markdown_parse/SKILL.md
app/skills/document_parse_agent/error_code_extract/SKILL.md

app/skills/change_impact_analysis_agent/api_field_change/SKILL.md
app/skills/change_impact_analysis_agent/signature_rule_change/SKILL.md
app/skills/change_impact_analysis_agent/error_code_change/SKILL.md
```

每个 `SKILL.md` 必须包含 YAML frontmatter，例如 `skill_id`、`name`、`description`、`agent`、`intent_tags`、`business_domain`、`required_context`、`enabled`、`is_default`。

运行时流程：

```text
IntentRecognitionNode 识别 intent
LangGraph route_intent 路由到固定子 Agent
ContextBuilder.build_skill_selection_context 构建最小选择上下文
SkillCatalog 只加载该子 Agent 的 skill metadata
SkillSelector 用规则 + 关键词相似度选择 selected_skill_id
SkillCatalog.load_skill_content 只加载选中 skill 的完整 SKILL.md
ContextBuilder.build_for_subagent 只把 selected skill 正文注入 SubAgentContext
子 Agent 执行任务并在 subagent_result / graph state 中返回 selected_skill_id
```

渐进式披露边界：

```text
主流程和主 Agent 只看到 skill metadata summary
未选中的 skill 不加载完整正文
不允许根据用户输入动态读取任意本地文件
候选 skill 必须来自固定 SkillCatalog
selected_skill_id 会进入 subagent_result 和 graph state，便于日志、测试和回放
```

当前选择算法：

```text
intent_tags 命中 intent 加权
intent_tags / description 命中 original_query、rewritten_query、short_summary 加权
required_context 存在 request_id、error_code、interface_name 时加权
business_domain 匹配加权
error_code / interface_name 命中 skill metadata 加权
没有明显匹配时回退到 is_default=true 的 skill
```

当前不会接真实 embedding、Milvus、Elasticsearch 或真实 LLM 做 skill selection。

示例：

```text
REQ_001 为什么返回 E102？ -> troubleshooting.signature_error
submitProposal 报文字段缺失，appId 不能为空 -> troubleshooting.missing_field
REQ_001 回调失败，渠道未收到回调 -> troubleshooting.callback_failure
签名规则变更：timestamp 必须加入签名原文 -> change_impact.signature_rule_change
```

新增意图路由：

```text
compliance_review -> call_compliance_security_agent
document_parse -> call_document_parse_agent
change_impact_analysis -> call_change_impact_analysis_agent
troubleshooting -> call_troubleshooting_agent
其他 -> direct_answer
```

示例请求：

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d "{\"tenant_id\":\"pingan_health\",\"user_id\":\"u001\",\"session_id\":\"s-agent\",\"messages\":[{\"role\":\"user\",\"content\":\"请做合规检查：手机号13800138000，健康告知能不能外发给渠道？\"}]}"
```

mock tools：

```text
get_knowledge
query_internal_log
partner_trace.get_request_detail
http_request（默认禁用）
mcp_http.call_tool（默认禁用）
```

stub：

```text
LongTermMemoryManager
官方 LangGraph SQLite checkpointer
真实审计系统 / OpenTelemetry
```

mock/stub 服务：

```text
InMemoryKnowledgeService
FakeMCPConnector
MCPConnector 抽象
```

默认 LLM：

```text
FakeLLMProvider
```

当前固定注册的子 Agent：

```text
troubleshooting_agent
compliance_security_agent
document_parse_agent
change_impact_analysis_agent
```

## 下一阶段建议

下一阶段可以逐步替换 mock/stub：

```text
将项目内 SQLiteCheckpointStore 替换为官方 SQLite/PostgreSQL checkpointer
将 InMemoryKnowledgeService 替换为真实知识库和版本过滤
接入真实日志查询工具
完善 Audit/Trace
将 FakeMCPConnector 替换为真实 MCP Connector
扩展接口映射、对接方案、产品规则和更多业务子 Agent
增加权限、脱敏和人工审批能力
```
