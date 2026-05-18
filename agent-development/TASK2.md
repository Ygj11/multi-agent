# TASK2.md

## 当前任务

基于已经通过测试的第一阶段增强版 MVP，实施第二阶段增强。

第二阶段目标是增强：

1. 会话持久化
2. 多轮记忆可靠性
3. LangGraph checkpoint 持久化
4. 项目可维护性

本轮仍然不要实现完整企业级平台，不接真实 MCP、真实 Milvus、真实 Redis、真实保险核心系统。

第一阶段已有能力必须继续可用，第一阶段已有测试必须继续通过。

---

## 1. 第二阶段目标

第二阶段要把第一阶段的内存存储能力升级为本地 SQLite 持久化能力，使服务重启后仍能保留：

1. 用户消息历史
2. assistant 回复历史
3. session summary
4. LangGraph checkpoint
5. 多用户、多会话、多轮对话隔离状态

第二阶段仍然是本地可运行、可测试、可维护的 MVP，不做生产级分布式架构。

核心目标：

```text
从“内存可运行 MVP”升级为“SQLite 本地持久化 MVP”。
```

---

## 2. 本轮必须实现的内容

必须实现：

1. 新增 SQLite 本地数据库支持
2. 新增数据库初始化逻辑
3. MessageStore 从内存实现切换为 SQLite 实现
4. SessionManager 基于 SQLite MessageStore 加载 recent messages
5. ShortTermMemoryManager 将 session_summary 持久化到 SQLite
6. LangGraph checkpoint 使用 SQLite 持久化方案
7. 保留第一阶段所有 API 行为
8. 保留第一阶段所有工具、子 Agent、LLM Provider 行为
9. 保证 `/api/chat` 响应结构不破坏兼容性
10. 保证 `session_key` 规则不变
11. 增加 SQLite 持久化相关测试
12. 增加服务重建后仍能读取历史上下文的测试
13. 增加 checkpoint 持久化相关测试
14. 更新 README.md
15. 确保第一阶段所有测试继续通过

建议新增模块：

```text
app/storage/
  __init__.py
  sqlite.py

app/session/
  sqlite_message_store.py

app/memory/
  sqlite_short_term_memory_manager.py

app/runtime/
  checkpoint.py
```

如果实现时发现更符合现有项目结构的命名方式，可以调整，但职责边界必须清晰。

---

## 3. 本轮不要实现的内容

本轮不要实现：

1. 真实 Redis
2. 真实 Redis Streams
3. 真实 Milvus
4. 真实 Elasticsearch
5. 真实 MCP Server
6. 真实保险核心系统 API
7. 真实外部渠道 trace
8. 生产级权限系统
9. 生产级审计系统
10. 前端页面
11. 复杂 RAG
12. 向量检索
13. 多实例分布式部署
14. 用户登录鉴权
15. 真实客户数据样例

---

## 4. 数据存储方案

第二阶段使用 SQLite 作为本地持久化存储。

默认数据库文件建议：

```text
.data/agent_mvp.sqlite3
```

要求：

1. `.data/` 目录不存在时自动创建
2. SQLite 文件路径可通过环境变量配置
3. 测试中必须能使用临时 SQLite 文件，避免污染本地开发数据
4. 数据库初始化必须幂等
5. 不要求引入 ORM
6. 可以使用 Python 标准库 `sqlite3`
7. 如需异步封装，可以使用 `asyncio.to_thread`
8. 不能因为 SQLite 持久化破坏现有 async 接口

建议环境变量：

```text
SQLITE_DB_PATH=.data/agent_mvp.sqlite3
```

---

## 5. SQLite 持久化要求

必须至少包含以下表。

### 5.1 messages 表

用于保存所有用户和 assistant 消息。

建议字段：

```sql
id INTEGER PRIMARY KEY AUTOINCREMENT,
session_key TEXT NOT NULL,
role TEXT NOT NULL,
content TEXT NOT NULL,
metadata_json TEXT NOT NULL,
created_at TEXT NOT NULL
```

索引要求：

```sql
CREATE INDEX IF NOT EXISTS idx_messages_session_created
ON messages(session_key, created_at);
```

### 5.2 short_term_memory 表

用于保存每个 session 的短期摘要。

建议字段：

```sql
session_key TEXT PRIMARY KEY,
summary TEXT NOT NULL,
updated_at TEXT NOT NULL
```

### 5.3 graph_checkpoints 表

用于 LangGraph checkpoint 持久化。

具体字段可根据所选 LangGraph SQLite checkpointer 实现调整。

要求：

1. checkpoint 必须按 `thread_id=session_key` 隔离
2. 服务重启或重新创建 app 后，同一个 session_key 可继续多轮对话
3. README 中说明当前 checkpoint 存储方案和后续替换 PostgreSQL 的方式

---

## 6. MessageStore 从内存切换为 SQLite 的要求

第一阶段 `MessageStore` 是内存实现。

第二阶段必须切换为 SQLite 持久化实现，且保持原有接口兼容：

```python
async def append(
    session_key: str,
    role: str,
    content: str,
    metadata: dict | None = None,
) -> dict:
    ...

async def list_by_session(
    session_key: str,
    limit: int | None = None,
) -> list[dict]:
    ...
```

要求：

1. `append` 必须写入 SQLite
2. `list_by_session` 必须从 SQLite 读取
3. `metadata` 必须以 JSON 字符串存储
4. 读取时必须还原为 dict
5. limit 不为空时返回最近 N 条消息
6. 不同 session_key 的消息不得互相污染
7. 保存消息时必须保留 metadata 中的：
   - request_id
   - trace_id
   - original_query
   - rewritten_query
   - intent
   - session_key

可以保留内存版实现作为测试或备用类，但默认 app 必须使用 SQLite 版本。

---

## 7. SessionManager 从内存切换为 SQLite 的要求

`SessionManager` 仍然作为会话加载入口。

要求：

1. `SessionManager.load_session(session_key)` 必须从 SQLite MessageStore 读取 recent messages
2. 必须从 SQLite ShortTermMemoryManager 读取 short_summary
3. 默认 recent messages 数量保持第一阶段行为，建议 `recent_limit=6`
4. 不允许跨 session_key 读取上下文
5. 接口保持兼容，避免影响 LangGraph 节点

---

## 8. ShortTermMemoryManager 持久化 session_summary 的要求

第一阶段 short summary 在内存中。

第二阶段必须持久化到 SQLite。

要求：

1. `get_summary(session_key)` 从 SQLite 读取
2. `compress_after_turn(...)` 生成摘要后写入 SQLite
3. 同一个 session_key 多次写入时更新原 summary
4. 不同 session_key 的 summary 严格隔离
5. 服务重启或重新创建 app 后，第二轮追问仍能读取上一轮 summary
6. 摘要内容仍需至少记录：
   - 上一轮 requestId
   - 错误码
   - 接口名
   - 初步结论

---

## 9. LangGraph checkpoint 持久化要求

第一阶段使用内存 checkpointer。

第二阶段必须实现 SQLite checkpoint 持久化。

要求：

1. LangGraph 执行时仍必须使用：

```python
config = {
    "configurable": {
        "thread_id": session_key
    }
}
```

2. checkpoint 必须持久化到 SQLite
3. checkpoint 必须按 session_key/thread_id 隔离
4. app 重建后，同一个 session_key 的图状态可以继续
5. 不同 session_key 的 checkpoint 不得互相污染
6. 如果 LangGraph 官方 SQLite checkpointer 可用，优先使用官方实现
7. 如果官方 SQLite checkpointer 需要额外依赖，必须在 `pyproject.toml` 中明确添加
8. 如果官方实现不可用，可以实现本地 SQLite checkpoint adapter，但必须有测试覆盖

README 中必须说明：

1. 当前 checkpoint 使用 SQLite
2. 第一阶段 MemorySaver 已替换
3. 后续可替换 PostgreSQL checkpointer

---

## 10. 多轮对话测试要求

必须保留第一阶段多轮测试，并新增 SQLite 持久化多轮测试。

新增测试建议：

```text
tests/test_sqlite_persistence.py
tests/test_sqlite_multi_turn_memory.py
tests/test_sqlite_checkpoint.py
```

必须覆盖：

1. 第一轮：

```text
REQ_001 为什么返回 E102？
```

2. 重新创建 app 或重新创建 Store/Manager

3. 第二轮：

```text
那这个一般是谁的问题？
```

4. 第二轮必须能识别上一轮 `REQ_001` 的 `E102` 上下文

5. 第二轮响应中必须体现：
   - E102
   - 签名校验失败
   - timestamp
   - 密钥版本或字段排序
   - 问题归属或排查方向

---

## 11. 多用户隔离测试要求

必须保留第一阶段多用户隔离测试，并新增 SQLite 持久化隔离测试。

必须覆盖：

```text
u001 + s001 -> pingan_health:web:u001:s001
u002 + s001 -> pingan_health:web:u002:s001
```

测试要求：

1. u001 第一轮询问 `REQ_001 为什么返回 E102？`
2. 重建 app 或 Store/Manager
3. u002 使用相同 session_id 追问 `那这个一般是谁的问题？`
4. u002 不得读取 u001 的上下文
5. u002 的 intent 不应被 u001 历史污染为 troubleshooting
6. SQLite messages、short_term_memory、checkpoint 都必须按 session_key 隔离

---

## 12. 回归测试要求

第一阶段已有测试必须继续通过：

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

新增测试后，必须保证：

```bash
uv run pytest
```

全部通过。

回归重点：

1. `/api/chat` 响应结构不变
2. FakeLLMProvider 仍默认启用
3. OpenAICompatibleLLMProvider 仍默认不启用
4. shell_exec 仍默认禁用
5. ToolBroker 仍强制经过 PolicyGate
6. TroubleshootingAgent 仍读取 `app/skills/troubleshooting/SKILL.md`
7. QueryRewriteNode 和 IntentRecognitionNode 行为不倒退
8. LangGraph 仍走真实 StateGraph

---

## 13. README 更新要求

README.md 必须更新以下内容：

1. SQLite 本地持久化说明
2. 默认数据库路径
3. 如何通过环境变量配置 SQLite 路径
4. 数据库初始化说明
5. messages 表说明
6. short_term_memory 表说明
7. LangGraph SQLite checkpoint 说明
8. 多轮对话在服务重启后的保持方式
9. 多用户隔离说明
10. 测试命令
11. 启动命令
12. 如何清理本地 SQLite 数据
13. 当前仍然是 mock/stub 的能力
14. 下一阶段建议

README 必须继续包含第一阶段已有内容：

1. 安装方式
2. 测试命令
3. 启动命令
4. curl 验证示例
5. LangGraph 状态机流程说明
6. 多轮对话说明
7. 真实 LLM 启用方式
8. shell_exec 安全说明
9. 当前 mock/stub 能力列表

---

## 14. 验收命令

完成后必须能运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

如本地存在旧 `.data/agent_mvp.sqlite3`，测试不得依赖该文件。

测试应使用临时数据库路径，避免污染开发数据。

---

## 15. 验收请求

启动服务：

```bash
uv run uvicorn app.main:app --reload
```

第一轮请求：

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

第一轮响应必须包含：

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
answer 包含 E102、签名校验失败、timestamp、密钥版本或字段排序
```

然后重启服务。

第二轮请求：

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
        "content": "那这个一般是谁的问题？"
      }
    ]
  }'
```

第二轮响应必须能识别“这个”指向上一轮 `REQ_001` 的 `E102` 签名校验失败问题。

多用户隔离验收：

```text
u001 + s001 -> pingan_health:web:u001:s001
u002 + s001 -> pingan_health:web:u002:s001
```

`u002` 不得读取 `u001` 的消息、summary 或 checkpoint。

