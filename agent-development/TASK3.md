# TASK3.md

## 当前任务

基于已经完成并通过测试的第一阶段增强版 MVP 和 TASK2 SQLite 持久化能力，实施第三阶段增强。

第三阶段目标是在当前稳定基础上新增：

1. RAG 雏形：`KnowledgeService` / `InMemoryKnowledgeService`
2. MCP 雏形：`MCPConnector` / `FakeMCPConnector`
3. 将 `get_knowledge` tool 改造成调用 `KnowledgeService`
4. 将外部渠道 trace 查询通过 MCP 工具能力接入问题排查流程
5. 问题排查子 Agent 在内部日志证据不足或需要判断渠道侧行为时，可以通过 MCP 查询外部渠道 trace
6. 保持 TASK1 和 TASK2 已有测试继续通过
7. 不接真实 Milvus、Elasticsearch、Redis、MCP Server、保险核心系统

本轮仍然不是完整企业级平台，只实现本地可运行、可测试、能体现 RAG 与 MCP 边界的 MVP 能力。

---

## 1. 第三阶段目标

第三阶段要把当前 mock 知识能力和 MCP stub 升级为更接近架构蓝图的本地雏形：

```text
固定主干轻量知识预检索
+ 子 Agent 任务级知识查询
+ MCP 外部渠道 trace 查询雏形
+ ToolBroker / PolicyGate 统一治理
```

核心目标：

1. `KnowledgeService` 成为独立公共组件，不属于主 Agent，也不属于子 Agent。
2. `InMemoryKnowledgeService` 提供关键词检索能力，替代原先硬编码在 `get_knowledge` tool 内的知识字符串。
3. `ContextBuilder.build_for_orchestrator()` 可以从 `KnowledgeService` 获取 `lightweight_knowledge_hints`。
4. `TroubleshootingAgent` 继续先查内部日志，再查知识，再在需要判断渠道侧行为时通过 fake MCP 查询渠道侧 trace。
5. MCP 外部能力必须通过 ToolBroker / PolicyGate，不能绕过工具治理。
6. `/api/chat` 对 `REQ_001 为什么返回 E102？` 的回答要能同时体现内部日志、知识库依据、渠道侧 trace 证据和问题归属。

---

## 2. 本轮必须实现的内容

必须实现：

1. 新增 `KnowledgeService` 抽象接口
2. 新增 `InMemoryKnowledgeService`
3. 新增 knowledge chunk schema 或等价结构
4. 支持 keyword search
5. 支持按 query 返回 knowledge chunks
6. 内置健康险个险接口联调相关 mock knowledge
7. `get_knowledge` tool 改造成调用 `KnowledgeService`
8. `ContextBuilder` 注入并使用 `KnowledgeService`
9. `ContextBuilder.build_for_orchestrator()` 从 KnowledgeService 获取 `lightweight_knowledge_hints`
10. 保留 `MCPConnector` 抽象
11. 新增 `FakeMCPConnector`
12. `FakeMCPConnector` 支持 `list_tools`
13. `FakeMCPConnector` 支持 `call_tool`
14. 实现 fake MCP tool：`partner_trace.get_request_detail`
15. 将 fake MCP tool 通过统一 MCP tool wrapper 注册到 `ToolRegistry`
16. `PolicyGate` 放行受控 MCP 工具调用
17. `ToolBroker` 覆盖 MCP 工具调用路径
18. `TroubleshootingAgent` 改造成按顺序收集：
    - 内部日志证据
    - KnowledgeService 知识依据
    - 渠道侧 trace 证据
19. `/api/chat` 对 REQ_001 的回答中体现渠道侧 trace 和旧版签名规则
20. 保持 SQLite 持久化、多轮记忆、多用户隔离能力不倒退
21. 保持 TASK1/TASK2 所有已有测试继续通过
22. 新增第三阶段 RAG/MCP 相关测试
23. 更新 README.md

---

## 3. 本轮不要实现的内容

本轮不要实现：

1. 真实 MCP Server
2. 真实 Milvus
3. 真实 Elasticsearch
4. 真实 Redis
5. 真实 Redis Streams
6. 真实保险核心系统 API
7. 真实外部渠道系统
8. 真实生产权限系统
9. 生产级审计系统
10. 前端页面
11. embedding
12. 向量检索
13. reranker
14. 复杂 RAG pipeline
15. 复杂知识版本治理
16. 复杂权限系统
17. 真实客户数据样例

---

## 4. RAG / KnowledgeService 设计要求

新增独立知识服务模块，建议目录：

```text
app/knowledge/
  __init__.py
  schemas.py
  service.py
  in_memory_service.py
```

`KnowledgeService` 是抽象接口，建议提供：

```python
class KnowledgeService(Protocol):
    async def search(self, query: str, top_k: int = 3) -> list[KnowledgeChunk]: ...
    async def pre_search(self, query: str, intent: str, top_k: int = 3) -> list[KnowledgeChunk]: ...
```

也可以使用 ABC，但必须清晰表达抽象边界。

返回结果至少包含：

```text
content
source
score
metadata
```

建议 schema：

```python
class KnowledgeChunk(BaseModel):
    content: str
    source: str
    score: float
    metadata: dict[str, Any]
```

要求：

1. KnowledgeService 不依赖 FastAPI。
2. KnowledgeService 不属于主 Agent。
3. KnowledgeService 不属于子 Agent。
4. KnowledgeService 可被 tool、ContextBuilder、子 Agent 复用。
5. 本阶段不接 Milvus。
6. 本阶段不接 Elasticsearch。
7. 本阶段不做 embedding。
8. 本阶段只做本地 keyword search。

---

## 5. InMemoryKnowledgeService 设计要求

`InMemoryKnowledgeService` 是本阶段默认实现。

必须支持：

1. 初始化内置 knowledge chunks
2. keyword search
3. query 命中多个 chunk 时按 score 降序返回
4. `top_k` 控制返回数量
5. 未命中时返回空列表，或返回低分通用提示 chunk，但测试中行为必须明确

内置 mock knowledge 至少包含：

1. E102 签名校验失败
2. submitProposal 接口说明
3. timestamp 参与签名规则
4. 密钥版本不一致
5. 字段排序不一致
6. 空值字段处理不一致

建议 mock knowledge 示例：

```text
E102 通常表示签名校验失败，常见原因包括签名字段排序不一致、timestamp 未参与签名、密钥版本不一致、空值字段处理方式不一致、body 序列化方式不一致、渠道方仍使用旧版签名规则。

submitProposal 是健康险个险投保提交接口，常见联调问题包括签名失败、字段映射错误、产品编码不一致和时间戳过期。

当前 v2 签名规则要求 timestamp 参与签名 base string，且字段排序必须与接口文档一致。
```

score 可以使用简单规则：

1. query 包含 chunk keyword 加分
2. 命中 `E102`、`timestamp`、`签名` 等核心词加分
3. 不要求复杂相关性算法

---

## 6. get_knowledge tool 改造要求

当前 `get_knowledge` tool 是硬编码字符串。

第三阶段必须改为调用 `KnowledgeService`。

要求：

1. `get_knowledge` 仍作为 ToolRegistry 中的内部 tool 注册
2. tool 调用仍必须经过 `ToolBroker -> PolicyGate`
3. tool 内部通过注入的 `KnowledgeService` 查询
4. 返回结构可以是字符串或结构化 dict，但测试必须明确
5. 若返回字符串，必须包含命中的 knowledge content
6. 若返回结构化 dict，至少包含：
   - chunks
   - query
   - hit_count
7. 保持已有测试对 `get_knowledge` 的核心断言继续通过，尤其应继续能返回“签名校验失败”等信息
8. 不允许 `get_knowledge` 绕过 KnowledgeService 继续写死 E102 文案

建议实现方式：

```python
def build_get_knowledge_tool(knowledge_service: KnowledgeService):
    async def get_knowledge(query: str, top_k: int = 3, **kwargs):
        chunks = await knowledge_service.search(query=query, top_k=top_k)
        ...
    return get_knowledge
```

---

## 7. MCPConnector 抽象设计要求

保留并增强当前 `app/mcp/connector.py` 中的 `MCPConnector` 抽象。

要求：

1. `MCPConnector` 表达外部 MCP 能力边界
2. 必须提供：

```python
async def list_tools(...) -> list[dict]: ...
async def call_tool(tool_name: str, arguments: dict) -> dict: ...
```

3. 抽象不连接真实 MCP Server
4. 抽象层不依赖具体业务工具
5. 真实 MCP 接入点必须清晰保留
6. README 中说明当前是 FakeMCPConnector，未来可替换真实 MCP client

---

## 8. FakeMCPConnector 设计要求

新增 `FakeMCPConnector`，建议文件：

```text
app/mcp/fake_connector.py
```

要求：

1. 继承或实现 `MCPConnector` 接口
2. `list_tools` 返回 fake MCP 工具描述
3. `call_tool` 根据 tool name 调用 fake MCP 工具
4. 未知 tool name 返回清晰错误或 `success=false`
5. 不连接网络
6. 不依赖真实外部系统
7. 测试必须覆盖 `list_tools` 和 `call_tool`

`list_tools` 至少返回：

```json
[
  {
    "name": "partner_trace.get_request_detail",
    "description": "查询合作方渠道侧请求 trace 明细",
    "input_schema": {
      "request_id": "string"
    }
  }
]
```

---

## 9. partner_trace.get_request_detail fake MCP tool 设计要求

必须实现 fake MCP tool：

```text
partner_trace.get_request_detail
```

输入：

```json
{
  "request_id": "REQ_001"
}
```

### 9.1 REQ_001 返回

对 `REQ_001` 返回渠道侧 trace，显示渠道侧仍使用旧版签名规则，未将 timestamp 纳入签名原文。

建议返回：

```json
{
  "found": true,
  "request_id": "REQ_001",
  "partner": "XX_CHANNEL",
  "trace_source": "partner_trace",
  "partner_signature_rule_version": "v1",
  "expected_signature_rule_version": "v2",
  "timestamp_included_in_sign": false,
  "base_string_fields": ["appId", "nonce", "body"],
  "missing_fields": ["timestamp"],
  "summary": "渠道侧 trace 显示仍使用旧版 v1 签名规则，签名原文未包含 timestamp。"
}
```

### 9.2 REQ_002 返回

对 `REQ_002` 返回渠道侧 trace，显示 timestamp 过期或渠道侧时间窗口异常。

建议返回：

```json
{
  "found": true,
  "request_id": "REQ_002",
  "partner": "XX_CHANNEL",
  "trace_source": "partner_trace",
  "partner_signature_rule_version": "v2",
  "expected_signature_rule_version": "v2",
  "timestamp_included_in_sign": true,
  "timestamp_status": "expired",
  "summary": "渠道侧 trace 显示 timestamp 已过期，疑似渠道侧时间窗口或重放策略异常。"
}
```

### 9.3 未知 requestId 返回

未知 requestId 返回：

```json
{
  "found": false,
  "request_id": "REQ_UNKNOWN",
  "message": "未查询到该 requestId 的渠道侧 trace"
}
```

---

## 10. TroubleshootingAgent 如何使用 KnowledgeService 和 MCPConnector

`TroubleshootingAgent` 必须继续读取自己的：

```text
app/skills/troubleshooting/SKILL.md
```

执行顺序必须体现：

1. 先查内部日志 `query_internal_log`
2. 再通过 `get_knowledge` tool 查询 KnowledgeService
3. 判断是否需要查询渠道侧 trace
4. 如需要，调用 fake MCP tool：`partner_trace.get_request_detail`
5. 汇总内部日志证据、知识库依据、渠道侧 trace 证据
6. 输出最终答案

需要调用 MCP 的典型情况：

1. 内部日志存在，但只能看到我方验签失败，需要判断渠道侧签名规则或签名原文
2. 内部日志 suspected_reason 指向渠道侧行为
3. 错误码是 E102，且需要确认 timestamp 是否参与签名
4. 用户追问“是谁的问题”“渠道方的问题吗”等归属判断
5. 内部日志未命中，但有 requestId，需要尝试查询渠道侧 trace

最终回答必须区分：

1. 内部日志证据
2. 知识库依据
3. 渠道侧 trace 证据
4. 初步问题归属
5. 建议处理动作

对 `REQ_001`，回答必须提到：

```text
E102
签名校验失败
timestamp
渠道侧 trace
旧版签名规则 或 timestamp 未参与签名
```

---

## 11. ToolBroker / PolicyGate 如何覆盖 MCP 工具调用

MCP 调用必须通过 ToolBroker / PolicyGate，不能由子 Agent 直接调用 connector。

推荐实现方式：

1. 新增 MCP tool wrapper
2. 将 wrapper 注册进 ToolRegistry
3. ToolBroker 调用 wrapper
4. wrapper 内部调用 `FakeMCPConnector.call_tool`

建议工具名：

```text
mcp.partner_trace.get_request_detail
```

或：

```text
partner_trace.get_request_detail
```

无论选择哪种，测试和 README 必须保持一致。

PolicyGate 必须新增规则：

1. 允许 `get_knowledge`
2. 允许 `query_internal_log`
3. 允许 fake MCP 工具 `partner_trace.get_request_detail` 或 `mcp.partner_trace.get_request_detail`
4. `shell_exec` 仍默认拒绝
5. 未注册/未知工具仍拒绝

ToolBroker 必须继续负责：

1. 工具存在性校验
2. PolicyGate 校验
3. 工具执行
4. 工具结果标准化
5. 工具异常标准化

---

## 12. ContextBuilder 如何使用 lightweight_knowledge_hints

`ContextBuilder` 是独立公共组件，第三阶段必须注入 KnowledgeService。

`build_for_orchestrator` 要求：

1. 接收 `original_query`、`rewritten_query`、`intent` 等现有参数
2. 调用 `KnowledgeService.pre_search(...)`
3. 将 top knowledge chunks 转成 `lightweight_knowledge_hints`
4. hints 应是轻量文本，不要塞入大量全文
5. 对 `E102` query，hints 至少包含签名校验失败、timestamp 或字段排序相关信息
6. 不影响 recent_messages、short_summary、available_tools、available_subagents

`build_for_subagent` 要求：

1. 继续读取 troubleshooting `SKILL.md`
2. 可以使用 KnowledgeService 获取更具体的 mock knowledge hint
3. 保留 `recent_troubleshooting_context`
4. 不在主干流程加载大量知识

---

## 13. 需要新增或修改的文件列表

建议新增：

```text
app/knowledge/
  __init__.py
  schemas.py
  service.py
  in_memory_service.py

app/mcp/
  fake_connector.py

tests/
  test_knowledge_service.py
  test_mcp_connector.py
  test_mcp_tool_broker.py
```

可能修改：

```text
app/main.py
app/runtime/context_builder.py
app/schemas/runtime.py
app/tools/builtin_tools.py
app/tools/policy_gate.py
app/tools/registry.py
app/subagents/troubleshooting_agent.py
app/mcp/connector.py
tests/test_tool_broker.py
tests/test_chat_troubleshooting.py
tests/test_langgraph_flow.py
README.md
```

不要求修改数据库 schema，除非实现者决定持久化知识或 MCP 调用记录。本阶段默认不持久化 knowledge 和 MCP trace。

---

## 14. 测试要求

必须保持现有 TASK1/TASK2 测试继续通过：

```text
tests/test_query_rewrite.py
tests/test_intent_recognition.py
tests/test_tool_broker.py
tests/test_chat_troubleshooting.py
tests/test_langgraph_flow.py
tests/test_multi_turn_memory.py
tests/test_multi_user_isolation.py
tests/test_shell_exec_tool.py
tests/test_sqlite_persistence.py
```

必须新增或增强测试：

1. `KnowledgeService` 可以根据 E102 检索知识
2. `KnowledgeService` 返回结果包含：
   - content
   - source
   - score
   - metadata
3. `get_knowledge` tool 调用 KnowledgeService
4. `ContextBuilder` 可以获取 `lightweight_knowledge_hints`
5. `FakeMCPConnector.list_tools` 正常
6. `FakeMCPConnector.call_tool` 查询 `REQ_001` 正常
7. `FakeMCPConnector.call_tool` 查询未知 requestId 返回 `found=false`
8. ToolBroker / PolicyGate 覆盖 MCP 工具调用
9. 未授权 MCP 工具或未知工具被拒绝
10. `TroubleshootingAgent` 对 `REQ_001` 能结合内部日志、KnowledgeService、FakeMCPConnector 输出结论
11. `/api/chat` 对 `REQ_001` 的回答中应提到：
    - E102
    - 签名校验失败
    - timestamp
    - 渠道侧 trace
    - 旧版签名规则或 timestamp 未参与签名
12. 第二轮追问仍能使用第一轮上下文
13. 不同 user_id 的 session 仍然隔离
14. SQLite 持久化测试继续通过
15. shell_exec 仍默认禁用

建议新增测试文件：

```text
tests/test_knowledge_service.py
tests/test_mcp_connector.py
tests/test_mcp_tool_broker.py
tests/test_troubleshooting_with_mcp.py
```

所有测试必须通过：

```bash
uv run pytest
```

---

## 15. README 更新要求

README.md 必须更新以下内容：

1. 第三阶段新增能力说明
2. RAG / KnowledgeService 架构说明
3. InMemoryKnowledgeService 当前 mock knowledge 列表
4. `get_knowledge` tool 已改为调用 KnowledgeService
5. MCPConnector 抽象说明
6. FakeMCPConnector 说明
7. fake MCP tool：`partner_trace.get_request_detail` 说明
8. MCP 工具必须通过 ToolBroker / PolicyGate 的说明
9. TroubleshootingAgent 新排查链路：
   - 内部日志
   - 知识库依据
   - 渠道侧 trace
   - 初步归属
10. `/api/chat` curl 示例更新，展示回答中包含渠道侧 trace
11. 当前仍然不接真实 Milvus、Elasticsearch、Redis、MCP Server、保险核心系统
12. 测试命令
13. 启动命令
14. 下一阶段建议

README 必须继续保留：

1. SQLite 持久化说明
2. session_key 多用户隔离说明
3. LangGraph 状态机说明
4. FakeLLMProvider 默认启用说明
5. OpenAICompatibleLLMProvider 启用方式
6. shell_exec 安全说明

---

## 16. 验收命令

完成后必须能运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

测试必须使用临时 SQLite 数据库，不能依赖或污染本地 `.data/agent_mvp.sqlite3`。

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

响应必须包含：

```text
request_id
session_key
original_query
rewritten_query
intent
answer
```

并且：

```text
session_key = pingan_health:web:u001:s001
intent = troubleshooting
```

`answer` 必须提到：

```text
E102
签名校验失败
timestamp
渠道侧 trace
旧版签名规则 或 timestamp 未参与签名
```

多轮验收：

第一轮：

```text
REQ_001 为什么返回 E102？
```

第二轮：

```text
那这个一般是谁的问题？
```

第二轮回答必须仍能识别“这个”指的是上一轮 `REQ_001` 的 `E102` 签名校验失败问题，并且可以结合渠道侧 trace 判断初步问题归属。

多用户隔离验收：

```text
u001 + s001 -> pingan_health:web:u001:s001
u002 + s001 -> pingan_health:web:u002:s001
```

`u002` 不得读取 `u001` 的 messages、session_summary、checkpoint、knowledge hints 或 MCP trace 结果。

---

## 18. 当前不做的内容

第三阶段完成后，以下能力仍然不做：

1. 不接真实 MCP Server
2. 不接真实 Milvus
3. 不接真实 Elasticsearch
4. 不接真实 Redis
5. 不接真实 Redis Streams
6. 不接真实保险核心系统
7. 不接真实合作方渠道系统
8. 不实现前端
9. 不实现复杂权限系统
10. 不实现生产级审计系统
11. 不做 embedding
12. 不做向量检索
13. 不做 reranker
14. 不做真实知识版本治理
15. 不保存真实客户、保单、健康告知或理赔数据

