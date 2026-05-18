# TASK1.md

## 当前任务

基于以下文件实现第一阶段增强版 MVP：

1. `enterprise_health_insurance_agent_architecture_detailed_v3.md`
2. `AGENTS.md`

本轮目标是实现一个可以本地运行、可以测试、能体现真实 LangGraph 状态机控制的健康险个险业务对接 Agent MVP。

本轮不要实现完整企业级平台，只实现第一阶段增强版 MVP。

---

## 1. 第一阶段增强版 MVP 目标

必须实现：

1. FastAPI `/api/chat`
2. RequestAdapter
3. ResponseAdapter
4. SessionManager
5. MessageStore
6. QueryRewriteNode
7. IntentRecognitionNode
8. ContextBuilder
9. 真实 LangGraph StateGraph
10. AgentOrchestrator
11. SubAgentManager
12. TroubleshootingAgent
13. ToolRegistry
14. PolicyGate
15. ToolBroker
16. mock tool：`get_knowledge`
17. mock tool：`query_internal_log`
18. 受限 shell_exec 工具
19. FakeLLMProvider
20. OpenAICompatibleLLMProvider 完整代码，但默认不启用
21. MCPConnector stub
22. ShortTermMemoryManager
23. LongTermMemoryManager stub
24. pytest 测试
25. README.md

---

## 2. 技术栈

使用：

- Python 3.12
- uv
- FastAPI
- uvicorn
- Pydantic
- pytest
- httpx
- LangGraph
- asyncio

可选依赖：

- openai

真实大模型 Provider 可以使用 OpenAI-compatible SDK，但默认运行和测试不能依赖真实 API key。

---

## 3. 项目结构要求

请创建如下项目结构：

```text
app/
  main.py

  config/
    settings.py

  schemas/
    message.py
    query_rewrite.py
    intent.py
    runtime.py
    tool.py
    subagent.py

  adapters/
    request_adapter.py
    response_adapter.py

  runtime/
    orchestrator.py
    graph.py
    graph_state.py
    context_builder.py

  session/
    session_manager.py
    message_store.py

  memory/
    short_term_memory_manager.py
    long_term_memory_manager.py

  query/
    query_rewrite_node.py
    intent_recognition_node.py

  llm/
    provider.py
    fake_provider.py
    openai_provider.py

  tools/
    registry.py
    policy_gate.py
    broker.py
    builtin_tools.py
    shell_exec_tool.py

  mcp/
    connector.py

  subagents/
    manager.py
    troubleshooting_agent.py

  skills/
    query_rewrite/
      SKILL.md
    troubleshooting/
      SKILL.md

tests/
  test_query_rewrite.py
  test_intent_recognition.py
  test_tool_broker.py
  test_chat_troubleshooting.py
  test_langgraph_flow.py
  test_multi_turn_memory.py
  test_multi_user_isolation.py
  test_shell_exec_tool.py
```

---

## 4. API 要求

实现：

```text
POST /api/chat
```

请求示例：

```json
{
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
}
```

响应示例：

```json
{
  "request_id": "...",
  "session_key": "pingan_health:web:u001:s001",
  "original_query": "REQ_001 为什么返回 E102？",
  "rewritten_query": "排查 requestId=REQ_001 的健康险个险接口 E102 错误原因",
  "intent": "troubleshooting",
  "answer": "根据模拟日志，REQ_001 返回 E102，初步判断为签名校验失败。建议检查签名规则版本、timestamp 是否参与签名、密钥版本和字段排序方式。"
}
```

---

## 5. session_key 规则

session_key 必须使用如下格式：

```text
{tenant_id}:{channel}:{user_id}:{session_id}
```

示例：

```text
pingan_health:web:u001:s001
pingan_health:web:u002:s001
```

要求：

1. 同一个 session_key 下可以进行多轮对话。
2. 不同 user_id 即使 session_id 相同，也必须生成不同 session_key。
3. 不同 session_key 的上下文不能互相污染。
4. LangGraph 执行时必须使用 session_key 作为 thread_id。

---

## 6. RequestAdapter 要求

实现外部请求到内部 InboundMessage 的转换。

必须做到：

1. 保留 original_query。
2. 生成 request_id。
3. 生成 trace_id。
4. 生成 session_key。
5. 不要把用户消息转成 system message。
6. 提取用户最后一条 message 作为当前 query。

---

## 7. ResponseAdapter 要求

实现内部响应到外部 HTTP response 的转换。

响应至少包含：

1. request_id
2. session_key
3. original_query
4. rewritten_query
5. intent
6. answer

---

## 8. LangGraph StateGraph 要求

必须实现真实 LangGraph StateGraph，不能只用普通 if/else 串联流程代替。

建议文件：

```text
app/runtime/graph.py
app/runtime/graph_state.py
```

### 8.1 GraphState

GraphState 至少包含：

```python
class AgentGraphState(TypedDict, total=False):
    request_id: str
    trace_id: str
    tenant_id: str
    channel: str
    user_id: str
    session_id: str
    session_key: str

    original_query: str
    rewritten_query: str
    intent: str
    confidence: float

    recent_messages: list[dict]
    short_summary: str | None

    orchestrator_context: dict
    subagent_result: dict | None
    answer: str

    error: str | None
```

### 8.2 LangGraph 节点

LangGraph 至少包含以下节点：

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

### 8.3 条件路由

必须实现条件路由：

```text
intent = troubleshooting -> call_troubleshooting_agent
intent != troubleshooting -> direct_answer
```

### 8.4 thread_id

graph 执行时必须使用：

```python
config = {
    "configurable": {
        "thread_id": session_key
    }
}
```

### 8.5 checkpointer

第一阶段可以使用内存 checkpointer。

要求：

1. 代码结构中要体现 checkpointer。
2. README 中说明后续可以替换为 SQLite/PostgreSQL checkpointer。
3. 测试中要证明同一个 session_key 可以多轮延续。

---

## 9. AgentOrchestrator 要求

AgentOrchestrator 必须基于 LangGraph 执行，不要只使用普通函数串联。

固定主干流程：

```text
load_session
-> save_user_message
-> query_rewrite
-> intent_recognition
-> build_orchestrator_context
-> conditional route
   -> troubleshooting: call_troubleshooting_agent
   -> other: direct_answer
-> save_assistant_message
-> compress_short_memory
-> finalize_response
```

---

## 10. QueryRewriteNode 要求

实现规则版 QueryRewriteNode，后续预留 LLM 改写接口。

规则：

1. 如果用户输入包含 `REQ_001` 和 `E102`，输出：

```text
排查 requestId=REQ_001 的健康险个险接口 E102 错误原因
```

2. 如果用户输入包含 `REQ_002` 和 `E102`，输出：

```text
排查 requestId=REQ_002 的健康险个险接口 E102 错误原因
```

3. 如果用户输入是多轮追问，例如：

```text
那这个一般是谁的问题？
```

并且 session recent_messages 或 short_summary 中存在 E102 / requestId，则改写为：

```text
继续排查上一轮 requestId 的 E102 签名校验失败问题，并判断问题归属
```

4. 如果无法识别，则：

```text
rewritten_query = original_query
```

---

## 11. IntentRecognitionNode 要求

实现规则版 IntentRecognitionNode。

规则：

1. 如果 query 包含 `E102`、`失败`、`报错`、`requestId`、`REQ_`，intent = `troubleshooting`
2. 如果 query 是追问，并且 session short_summary 或 recent_messages 中存在 E102 / requestId，intent = `troubleshooting`
3. 如果 query 包含 `等待期`、`责任`、`条款`，intent = `product_rule_qa`
4. 否则 intent = `unknown`

troubleshooting 对应：

```text
target_subagent = troubleshooting_agent
required_tools = query_internal_log, get_knowledge
```

输出至少包含：

1. intent
2. confidence
3. target_subagent
4. required_tools

---

## 12. ContextBuilder 要求

ContextBuilder 是独立公共组件，不属于主 Agent，也不属于子 Agent。

必须实现两级上下文构建。

### 12.1 build_for_orchestrator

用于主 Agent 协调上下文。

必须包含：

1. original_query
2. rewritten_query
3. intent
4. session_key
5. recent_messages
6. short_summary
7. available_subagents
8. available_tools
9. lightweight_knowledge_hints

### 12.2 build_for_subagent

用于子 Agent 任务上下文。

必须包含：

1. task
2. rewritten_query
3. intent
4. allowed_tools
5. troubleshooting skill 内容
6. mock knowledge hint
7. recent troubleshooting context

---

## 13. SubAgentManager 要求

实现固定子 Agent catalog。

第一阶段只需要一个子 Agent：

```text
troubleshooting_agent
```

必须提供：

1. register / catalog 能力
2. call_subagent 能力
3. 根据名称调用 troubleshooting_agent

---

## 14. TroubleshootingAgent 要求

实现问题排查子 Agent。

逻辑：

1. 读取 `app/skills/troubleshooting/SKILL.md`
2. 如果 task 中包含 requestId，则调用 `query_internal_log`
3. 如果错误码是 E102，则结合 mock 日志、mock knowledge 和 skill 输出排查建议
4. 如果没有 requestId，则基于 skill 给出通用排查步骤
5. 如果是第二轮追问“那这个一般是谁的问题？”，应能基于 short_summary 或 recent_messages 判断仍在讨论上一轮 E102 问题
6. 输出内容要能体现：
   - E102
   - 签名校验失败
   - timestamp
   - 密钥版本
   - 字段排序
   - 初步问题归属或建议排查方向

---

## 15. ToolRegistry 要求

注册以下工具：

1. `get_knowledge`
2. `query_internal_log`
3. `shell_exec`

---

## 16. PolicyGate 要求

第一阶段规则：

1. `get_knowledge` 允许
2. `query_internal_log` 允许
3. `shell_exec` 默认拒绝
4. `shell_exec` 只有在 `ENABLE_SHELL_EXEC=true` 且命令在 allowlist 中才允许
5. 其他工具拒绝

---

## 17. ToolBroker 要求

所有工具执行必须经过 ToolBroker。

ToolBroker 执行前必须调用 PolicyGate。

ToolBroker 至少负责：

1. 工具存在性校验
2. PolicyGate 校验
3. 工具执行
4. 工具结果标准化
5. 工具异常标准化

---

## 18. mock tool：get_knowledge

如果 query 包含 E102，返回：

```text
E102 通常表示签名校验失败，常见原因包括签名字段排序不一致、timestamp 未参与签名、密钥版本不一致、空值字段处理方式不一致、body 序列化方式不一致、渠道方仍使用旧版签名规则。
```

---

## 19. mock tool：query_internal_log

如果 request_id = REQ_001，返回：

```json
{
  "found": true,
  "request_id": "REQ_001",
  "channel": "XX_CHANNEL",
  "product_code": "ESHENGBAO",
  "interface_name": "submitProposal",
  "error_code": "E102",
  "error_message": "signature verification failed",
  "server_sign": "B82D****",
  "partner_sign": "A9F3****",
  "signature_rule_version": "v2",
  "suspected_reason": "partner signature does not include timestamp"
}
```

如果 request_id = REQ_002，返回：

```json
{
  "found": true,
  "request_id": "REQ_002",
  "channel": "XX_CHANNEL",
  "product_code": "ESHENGBAO",
  "interface_name": "submitProposal",
  "error_code": "E102",
  "error_message": "signature verification failed",
  "server_sign": "C72E****",
  "partner_sign": "C72E****",
  "signature_rule_version": "v2",
  "suspected_reason": "timestamp expired"
}
```

如果 request_id 不存在，返回：

```json
{
  "found": false,
  "message": "未查询到该 requestId 的模拟日志"
}
```

mock 数据可以直接写进代码，例如：

```text
app/tools/builtin_tools.py
```

或者：

```text
app/mock_data.py
```

不需要单独创建 docs/mock_data 目录。

---

## 20. shell_exec 工具要求

允许实现 shell_exec，但必须安全受限。

要求：

1. 默认禁用
2. 只有 `ENABLE_SHELL_EXEC=true` 时才允许
3. 禁止使用 `shell=True`
4. 必须使用命令 allowlist
5. 第一阶段 allowlist 只允许：
   - echo
   - pwd
   - ls
6. timeout 最多 5 秒
7. 工作目录限制在项目根目录
8. 必须经过 PolicyGate 和 ToolBroker
9. 必须有测试覆盖默认禁用和 allowlist 行为
10. 不允许执行 rm、curl、wget、ssh、scp、cat 敏感文件等高风险命令

---

## 21. LLM Provider 要求

### 21.1 FakeLLMProvider

默认启用。

必须实现：

1. chat
2. chat_json

FakeLLMProvider 使用规则返回确定性结果，保证测试稳定。

---

### 21.2 OpenAICompatibleLLMProvider

必须提供完整代码：

```text
app/llm/openai_provider.py
```

要求：

1. 支持 `OPENAI_API_KEY`
2. 支持 `OPENAI_BASE_URL`
3. 支持 `OPENAI_MODEL`
4. 支持 `ENABLE_REAL_LLM=true`
5. 支持 chat
6. 支持 chat_json
7. 支持 tools 参数
8. 支持 timeout
9. 支持异常处理
10. 默认不启用
11. 没有 API key 时不影响测试

可以使用可选导入：

```python
try:
    from openai import AsyncOpenAI
except ImportError:
    AsyncOpenAI = None
```

如果 `ENABLE_REAL_LLM=true` 但没有安装 openai 或没有配置 API key，需要抛出清晰错误。

---

## 22. SessionManager / MessageStore 要求

第一阶段可以使用本地文件实现。

要求：

1. 同一个 session_key 保存多条消息
2. 不同 user_id 的 session_key 不同，消息隔离
3. MessageStore 提供 append 和 list_by_session
4. 消息包含 role、content、metadata
5. 多轮对话时，第二轮可以读取第一轮 recent_messages

---

## 23. ShortTermMemoryManager 要求

第一阶段简单实现。

要求：

1. 每轮 answer 后调用 `compress_after_turn`
2. 不需要真实 LLM 压缩
3. 可以用规则摘要
4. summary 至少能记录：
   - 上一轮 requestId
   - 错误码
   - 接口名
   - 初步结论
5. 第二轮追问时可以用 summary 补全上下文

---

## 24. LongTermMemoryManager 要求

第一阶段只预留接口。

必须实现：

```python
async def retrieve(...):
    return []

async def extract_and_update(...):
    return None
```

---

## 25. MCPConnector 要求

第一阶段只预留 stub。

文件：

```text
app/mcp/connector.py
```

必须实现：

```python
async def list_tools(...):
    return []

async def call_tool(...):
    raise NotImplementedError
```

不接真实 MCP。

---

## 26. Skills 要求

### 26.1 app/skills/query_rewrite/SKILL.md

内容至少包括：

```text
你是健康险个险业务 Agent 的 query 改写器。
你的任务是将用户输入改写为适合意图识别、知识检索和工具调用的标准查询。
必须保留用户原始语义，不得编造产品、接口、保单、客户信息。
```

### 26.2 app/skills/troubleshooting/SKILL.md

内容至少包括：

```text
当出现 E102 签名校验失败时，优先检查：
1. 签名字段排序是否一致
2. timestamp 是否参与签名
3. 密钥版本是否一致
4. 空值字段是否参与签名
5. body 序列化是否一致
6. 渠道方是否使用旧版签名规则

排查时应先查内部日志，再结合知识库和历史上下文输出结论。
没有 requestId 时，应提示用户补充 requestId 或错误报文。
```

---

## 27. 测试要求

必须实现以下测试文件：

```text
tests/test_query_rewrite.py
tests/test_intent_recognition.py
tests/test_tool_broker.py
tests/test_chat_troubleshooting.py
tests/test_langgraph_flow.py
tests/test_multi_turn_memory.py
tests/test_multi_user_isolation.py
tests/test_shell_exec_tool.py
```

测试要求：

1. `uv run pytest` 全部通过
2. 使用 FastAPI TestClient 或 httpx 测试 `/api/chat`
3. 测试 QueryRewriteNode 能识别 E102 和 requestId
4. 测试 IntentRecognitionNode 能将 E102 / requestId 识别为 troubleshooting
5. 测试 ToolBroker 调用工具前会经过 PolicyGate
6. 测试 `/api/chat` 输入 `REQ_001 为什么返回 E102？` 能返回问题排查答案
7. 测试真实 LangGraph 图会走 troubleshooting 分支
8. 测试同一 session 第二轮追问能使用第一轮上下文
9. 测试不同 user_id 的 session 隔离
10. 测试 shell_exec 默认禁用
11. 测试 shell_exec 开启后只允许 allowlist 命令
12. 测试 OpenAICompatibleLLMProvider 文件存在且默认不影响运行

---

## 28. README 要求

README.md 必须包含：

1. 项目说明
2. 架构简图
3. 本地安装
4. 测试命令
5. 启动命令
6. curl 示例
7. LangGraph 状态机流程说明
8. 多轮对话说明
9. 真实 LLM Provider 启用方式
10. shell_exec 安全说明
11. 当前 mock/stub 能力列表
12. 下一阶段建议

---

## 29. 本轮不要做

本轮不要实现：

1. 真实保险核心 API
2. 真实 Milvus
3. 真实 Redis Streams
4. 真实 MCP Server
5. 真实外部渠道 trace
6. 真实生产权限系统
7. 前端页面
8. 生产级审计系统
9. 真实客户数据样例
10. 复杂数据库持久化
11. 完整企业级权限系统

---

## 30. 验收命令

完成后必须能运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

---

## 31. 验收请求

启动后，请求：

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

应返回包含：

1. request_id
2. session_key
3. original_query
4. rewritten_query
5. intent
6. answer

其中：

```text
intent = troubleshooting
session_key = pingan_health:web:u001:s001
answer 中应提到 E102、签名校验失败、timestamp、密钥版本或字段排序。
```

---

## 32. 多轮验收

第一轮：

```text
REQ_001 为什么返回 E102？
```

第二轮：

```text
那这个一般是谁的问题？
```

第二轮回答应能识别“这个”指的是上一轮 REQ_001 的 E102 签名失败问题。

---

## 33. 多用户隔离验收

同样 session_id，不同 user_id：

```text
u001 + s001 -> pingan_health:web:u001:s001
u002 + s001 -> pingan_health:web:u002:s001
```

两者上下文不能互相污染。