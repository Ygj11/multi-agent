# P3 Agent Runtime State Governance 架构治理任务

## 任务定位

本任务不是“把 checkpoint 里几个大字段删掉”的局部优化，而是一次 Agent 运行时状态架构治理。

当前项目已经完成了意图体系、Query Rewrite 多轮上下文、子 Agent/Skill 选择、ToolExecutor、审批链路、工具模式 mock/real 等主干能力。随着主流程变完整，`AgentGraphState` 已经从“节点间传递状态”逐渐膨胀成了：

- 节点运行时上下文
- 多轮会话窗口
- 实体记忆快照
- 工具执行结果
- 审批恢复数据
- 最终响应数据
- 调试排障临时信息
- checkpoint 持久化内容

这些职责混在一个 state 里，会导致后续 Agent 架构继续复杂化时出现存储膨胀、边界混乱、隐私风险、恢复语义不清、测试只覆盖偶然字段等问题。

本任务目标是建立清晰的 Agent Runtime State Governance：明确哪些数据只属于本次图执行，哪些数据应该长期持久化，哪些数据只保存引用，哪些数据进入审计，哪些数据只在 debug 模式下保存。

本任务采用“从持久化契约源头变小”的方案，不通过定时清理、TTL 或额外 DebugTraceStore 来解决膨胀问题。业务事实数据默认长期保留，但运行时大对象不允许进入持久化契约。

## 当前问题

### 1. GraphState 同时承担运行时和持久化职责

当前 `orchestrator.run()` 执行结束后，会把完整 state 写入 checkpoint。完整 state 中可能包含：

- `conversation_window`
- `recent_messages`
- `entity_bag`
- `pending_messages`
- `pending_tools`
- `verification_results`
- `subagent_result`
- 工具调用结果
- LLM 原始中间信息
- 节点路径和临时判断

这些字段对于图执行有用，但不一定适合作为 checkpoint 的持久化契约。

### 2. 多个持久化系统职责重叠

项目中已经存在多个事实存储：

- `messages`：会话消息
- `graph_checkpoints`：图状态快照
- `tool_execution_logs`：工具执行日志
- `approval_requests`：审批请求和恢复
- evidence 相关结构：用于回答和核验的事实证据

但当前 checkpoint 仍倾向于保存“全量 state”，导致同一份信息可能同时存在于 messages、tool logs、approval、checkpoint 中。

### 3. Debug 数据和业务恢复数据混在一起

完整 state 对 debug 很有帮助，但对业务恢复不必要。

如果默认把完整 state 长期保存，会带来：

- 数据库持续膨胀
- 敏感数据扩大持久化范围
- 后续 schema 演进困难
- 很难定义哪些字段是真正稳定的持久化契约

### 4. 审批恢复需要的是 Resume State，不是完整 GraphState

审批 pending / approved / rejected 场景确实需要恢复执行上下文，但它需要的是：

- 当前审批对应的请求上下文
- 待执行工具调用
- 工具参数
- 已选择的 agent / skill
- 必要实体
- 审批链路 id

它不应该依赖完整 `conversation_window`、完整 `recent_messages` 或其他调试临时信息。

### 5. 缺少状态字段生命周期治理

当前字段缺少统一分类：

- runtime only
- durable checkpoint
- durable reference
- audit log
- memory
- debug temporary
- deprecated

没有生命周期分类时，新功能会继续把临时字段塞进 `AgentGraphState`，然后被 checkpoint 自动持久化。

## 架构目标

### 总原则

1. `AgentGraphState` 可以服务图执行，但不能天然等于持久化契约。
2. Durable checkpoint 必须是显式投影出来的 `CheckpointSnapshot`。
3. 审批恢复必须使用专门的 `AgentResumeState`。
4. 多轮会话上下文应从 `messages`、短期摘要、实体抽取结果重建，而不是依赖 checkpoint 全量窗口。
5. 工具执行事实应进入 `tool_execution_logs` 和 evidence，不应完整塞进 checkpoint。
6. 不新增 DebugTraceStore，不把完整 GraphState 作为调试快照长期保存。
7. 不新增状态清理策略，不通过 TTL 解决状态膨胀；需要长期保留的是业务事实，不是运行时大对象。
8. 所有持久化 payload 必须带 `schema_version`。
9. 本任务不定义入库脱敏策略；只要求 checkpoint 不保存凭证类字段和完整运行时原始大对象。
10. SQLite 初始化代码只保留新表结构；当前任务不做自动补字段、旧结构判断、旧表重建或 legacy checkpoint 兼容。旧库不符合新 schema 时，由开发/部署动作手动删除后重新初始化。

## 目标架构

### 1. Runtime State

`AgentGraphState` 继续作为图执行过程中的运行时状态。

它可以包含节点需要的中间字段，例如：

```text
conversation_window
recent_messages
entity_bag
available_agents
agent_card_summaries
skill_candidates
verification_results
pending_messages
pending_tools
llm_reason
graph_path
```

但这些字段默认属于 runtime only，不因为存在于 state 中就自动进入 checkpoint。

### 2. CheckpointSnapshot

新增显式持久化模型 `CheckpointSnapshot`，只保存“请求级恢复和排障所必需的摘要状态”。

建议字段：

```text
schema_version
request_id
trace_id
tenant_id
channel
user_id
session_id
session_key
thread_id
created_at
updated_at
original_query
rewritten_query
rewrite_type
intent
sub_intent
entities
selected_agent
selected_skill_id
approval_required
approval_id
approval_status
answer
error
graph_path
tool_log_refs
evidence_refs
message_refs
```

明确不保存：

```text
conversation_window
recent_messages
entity_bag 原始完整对象
available_agents
完整 agent card
完整 skill schemas
完整 pending tool schemas
完整 verification_results 列表
完整 LLM messages
完整 raw LLM response
完整 tool result payload
```

### 3. AgentResumeState

新增审批和中断恢复专用模型 `AgentResumeState`。

它比 `CheckpointSnapshot` 更关注“恢复执行”，但仍不等于完整 `AgentGraphState`。

建议字段：

```text
schema_version
request_id
trace_id
session_key
thread_id
auth_context_summary
original_query
rewritten_query
intent
sub_intent
entities
selected_agent
selected_skill_id
approval_id
approval_status
parent_approval_id
root_approval_id
approval_depth
pending_tool_call
pending_tool_name
pending_tool_arguments
pending_tool_is_write
pending_messages
tool_log_refs
evidence_refs
resume_reason
```

`pending_messages` 需要进一步分级：

- 如果是恢复 LLM tool calling 所必需，允许保存经过裁剪的 messages。
- 如果只是 debug 上下文，不进入 `AgentResumeState`。

### 4. ToolExecutionLogStore

工具执行日志作为工具调用事实权威来源。

Checkpoint 只保存引用：

```text
tool_log_refs: [
  {
    "tool_name": "...",
    "tool_call_id": "...",
    "execution_id": "...",
    "status": "success|failed|pending_approval"
  }
]
```

工具结果详情保留在 `tool_execution_logs`，由权限和审计策略控制。

### 5. EvidenceStore

回答生成和核验所需的结构化事实进入 evidence。

Checkpoint 只保存 evidence 引用：

```text
evidence_refs: [
  {
    "id": "...",
    "type": "tool_result|knowledge|policy|manual",
    "source": "...",
    "created_at": "..."
  }
]
```

### 6. ConversationStore / Memory

多轮会话上下文的权威来源应是：

- 原始消息：`messages`
- 短期摘要：short summary
- 当前轮抽取实体：`entities`
- 必要时的 session entity memory

`conversation_window` 和 `recent_messages` 是为了本次 Query Rewrite 构建出来的运行时视图，不是 checkpoint 契约。

### 7. 永久保留业务事实，不保留运行时大对象

本任务不引入状态 TTL、Retention、Cleanup，也不新增 DebugTraceStore。

保留原则：

- `messages` 可以长期保留。
- `tool_execution_logs` 可以长期保留。
- `approval_requests` 可以长期保留。
- `CheckpointSnapshot` 可以长期保留。
- evidence 可以长期保留。

禁止长期保留：

- 完整 `AgentGraphState`
- 完整 `conversation_window`
- 完整 `recent_messages`
- 完整 `entity_bag` 内部对象
- 完整 prompt messages
- 完整 raw LLM response
- 完整运行时 tool schemas
- 只服务节点临时判断的 debug 字段

核心原则：

```text
不是靠清理旧数据解决膨胀，而是从源头禁止运行时大状态进入持久化契约。
```

## 状态字段分类规则

新增或更新 `GRAPH_STATE_FIELD_AUTHORITY`，每个字段必须有以下属性：

```text
owner
source
kind
persistence
```

`kind` 可选：

```text
runtime
checkpoint
resume
memory
audit
debug_temporary
reference
deprecated
```

`persistence` 可选：

```text
none
checkpoint_snapshot
resume_state
message_store
tool_log_store
evidence_store
approval_store
```

新增架构测试：任何 `AgentGraphState` 字段如果没有声明生命周期分类，测试失败。

## 推荐新增文件

```text
app/runtime/state_contracts.py
app/runtime/state_projector.py
tests/test_runtime_state_contracts.py
tests/test_checkpoint_projection.py
tests/test_approval_resume_state.py
```

### `state_contracts.py`

定义持久化契约：

```text
CheckpointSnapshot
AgentResumeState
ToolLogRef
EvidenceRef
MessageRef
StateFieldPolicy
```

建议使用 Pydantic model，方便 schema version、校验、序列化和测试。

### `state_projector.py`

只允许通过 projector 从 `AgentGraphState` 生成持久化 payload：

```text
project_checkpoint_snapshot(state) -> CheckpointSnapshot
project_approval_resume_state(state) -> AgentResumeState
```

禁止业务代码直接把完整 state 写进 checkpoint。

## 需要修改的核心文件

### 1. `app/runtime/orchestrator.py`

当前逻辑：

```text
graph.ainvoke(...) -> state
checkpoint_store.save(thread_id, state)
```

目标逻辑：

```text
graph.ainvoke(...) -> state
snapshot = project_checkpoint_snapshot(state)
checkpoint_store.save_snapshot(thread_id, snapshot)
```

禁止在这里保存完整 `AgentGraphState`。如果需要排查，依赖结构化日志、测试断点、tool logs、message metadata 和 checkpoint 摘要。

### 2. `app/runtime/checkpoint.py`

从“保存任意 state dict”改成“保存有 schema version 的 snapshot”。

建议接口：

```text
save_snapshot(thread_id, snapshot)
load_snapshot(thread_id) -> CheckpointSnapshot | None
delete_snapshot(thread_id)
```

本任务不做旧数据兼容：

- 不做 legacy loader。
- 不做 `if column missing then alter table add column` 这类自动补字段。
- 不做 `if schema mismatch then drop table` 这类运行时旧表判断。
- 初始化代码只声明新表结构。
- 如果当前 sqlite 表结构不符合新契约，开发和测试环境手动删除旧 sqlite 后重新初始化。
- 生产迁移不是本任务目标；后续真正上线前再单独设计正式 migration。

### 3. `app/storage/sqlite.py`

只保留新表结构：

```text
graph_checkpoints:
  thread_id
  schema_version
  snapshot_json
  created_at
  updated_at
```

删除旧建表逻辑，不在代码中判断旧表结构。新写入只能写 `snapshot_json`。

### 4. `app/runtime/handlers/approval_handler.py`

审批 pending 时，不再把完整 GraphState 当作恢复依据。

目标：

- 创建审批请求时保存 `AgentResumeState`
- 审批通过后从 `AgentResumeState` 重建最小运行时输入
- 继续执行 pending tool call
- 恢复后重新进入必要的 graph 节点

验收重点：

- approved resume 能继续执行工具
- rejected resume 能返回拒绝结果
- 二次审批链路不丢失 parent/root/depth
- 不依赖完整 `conversation_window`

### 5. `app/runtime/handlers/message_commit_handler.py`

消息提交只记录消息与必要 metadata。

不要把完整 state、完整 tool result、完整 verification 列表写入 message metadata。

### 6. `app/tools/executor.py`

工具执行后写入 `tool_execution_logs`，并向 state 返回轻量引用。

state 中可以保留当前节点需要的 tool result，但 checkpoint 投影只能保存引用和摘要。

### 7. `app/runtime/graph_state.py`

升级字段权威表，明确每个字段：

- 谁写入
- 谁消费
- 是否 runtime only
- 是否进入 checkpoint
- 是否进入 resume
- 是否进入 audit

## 实施阶段

### Phase 0：现状测量和字段盘点

目标是先量化问题，不直接改业务行为。

执行：

1. 增加测试或脚本统计一次典型请求最终 state 的 JSON 大小。
2. 统计 checkpoint payload 中最大的 top-level 字段。
3. 列出当前 `AgentGraphState` 全字段和消费点。
4. 标注字段生命周期分类。

建议新增脚本：

```text
scripts/audit_graph_state_size.py
```

验收：

- 能输出典型请求 checkpoint size。
- 能输出 top 10 大字段。
- `GRAPH_STATE_FIELD_AUTHORITY` 覆盖所有 state 字段。

### Phase 1：引入状态契约和投影器

执行：

1. 新增 `CheckpointSnapshot`。
2. 新增 `AgentResumeState`。
3. 新增 `project_checkpoint_snapshot()`。
4. 新增 `project_approval_resume_state()`。
5. 增加单元测试覆盖 checkpoint/resume projection 的 allowlist 和 denylist。

验收：

- projection 输出稳定。
- projection 不包含 runtime-only 字段。
- projection 包含恢复和排障所需字段。
- checkpoint projection 不包含凭证类字段和完整运行时原始大对象。

### Phase 2：替换 checkpoint 写入链路

执行：

1. 修改 `orchestrator.run()`，保存 `CheckpointSnapshot`。
2. 修改 `SQLiteCheckpointStore`，支持 `snapshot_json`。
3. 删除旧 checkpoint 建表逻辑，只保留 `graph_checkpoints` 新 schema。
4. 删除新代码对旧 `state_json` 全量 state 的依赖。
5. 更新相关测试。

验收：

- 新请求写入 snapshot 格式。
- 正常请求 checkpoint payload 明显变小。
- 当前开发库如果存在旧表结构，需要手动删除 sqlite 后重新初始化。
- 代码中不存在自动补字段和 legacy checkpoint fallback。
- `/api/chat` 返回不变。

### Phase 3：审批恢复从完整 state 迁移到 Resume State

执行：

1. 审批创建时保存 `AgentResumeState`。
2. 审批通过时从 `AgentResumeState` 恢复 pending tool call。
3. 审批拒绝时从 `AgentResumeState` 返回拒绝结果。
4. 二次审批链路保留 parent/root/depth。

验收：

- `tests/test_approval_full_flow.py` 通过。
- approved / rejected / chain resume 全部通过。
- 审批恢复不依赖完整 `conversation_window`。
- checkpoint 中不保存完整 pending tool schemas。

### Phase 4：SQLite Schema 收口和持久化边界验收

执行：

1. 检查 `sqlite.py` 中 checkpoint、approval、tool log、messages 的表结构。
2. 删除 checkpoint 旧全量 state 建表逻辑和旧字段写入。
3. 确认没有启动时自动 alter table 补字段、schema mismatch 判断、自动 drop 旧表的兜底逻辑。
4. 确认业务事实数据仍然长期保存。
5. 确认运行时大对象没有进入任何持久化表的 JSON payload。

验收：

- sqlite 初始化代码只声明新契约表结构。
- checkpoint 表只保存 `snapshot_json` 级别的数据。
- 不新增 DebugTraceStore。
- 不新增 Retention/Cleanup。
- 不新增 TTL 配置。

### Phase 5：架构验收和文档

执行：

1. 更新架构文档，说明 state、memory、checkpoint、approval、tool log、evidence 的边界。
2. 新增 architecture acceptance tests。
3. 更新 `.env.example`。
4. 更新开发调试说明。

验收：

- `uv run pytest` 全量通过。
- 新增测试覆盖 checkpoint projection、resume state、sqlite schema、持久化边界。
- 文档能解释“为什么 GraphState 不等于 checkpoint”。

## 验收标准

### 功能验收

- `/api/chat` 正常请求返回结构不变。
- Query Rewrite 多轮上下文能力不退化。
- 意图识别和子 Agent/Skill 选择不退化。
- Tool calling 正常执行。
- mock / real tool mode 不受影响。
- 审批 pending / approved / rejected / chained approval 正常。

### 存储验收

默认 checkpoint 不允许包含：

```text
conversation_window
recent_messages
available_agents
agent_card_summaries
完整 entity_bag 对象
完整 verification_results
完整 raw LLM messages
完整 raw LLM response
完整 tool result payload
完整 pending tool schemas
```

默认 checkpoint 推荐大小：

```text
普通请求 < 10KB
审批 pending 请求 < 50KB
```

如果超过阈值，测试应提示最大的字段来源。

### 架构验收

- 所有 `AgentGraphState` 字段都有生命周期分类。
- 新增持久化字段必须先定义 schema 和生命周期分类。
- 业务恢复只依赖 `CheckpointSnapshot` / `AgentResumeState` / 权威 store，不依赖完整 state。
- 不新增 DebugTraceStore，调试依赖结构化日志、断点、tool logs、message metadata 和 checkpoint 摘要。
- 不新增状态 TTL 或清理任务。

### 持久化边界验收

- API key、token、authorization、password、secret 不允许进入 checkpoint。
- 本任务不定义手机号、身份证、保单号、受理号等业务字段的入库脱敏策略。
- 工具参数和工具结果不能无脑完整进入 checkpoint；如需长期保存，应进入 tool log 或 evidence。
- 完整 prompt、完整 raw LLM response、完整 GraphState 不允许进入 checkpoint。

## 非目标

本任务不负责：

- 重写 LangGraph 主流程
- 改变 `/api/chat` 响应 schema
- 重做意图体系
- 重做 Query Rewrite 业务逻辑
- 重做 Skill 匹配算法
- 引入外部向量库或长期记忆系统
- 删除 messages / tool logs / approval store
- 新增 DebugTraceStore
- 新增 Retention / Cleanup / TTL 机制
- 做生产级 migration 系统
- 做旧 checkpoint legacy fallback

本任务要求新代码不再写入完整 `AgentGraphState`。如果当前 sqlite 旧表结构不符合任务目标，开发和测试环境手动删除旧数据库后重新初始化，不做自动补字段、旧结构判断和旧表自动重建。

## 风险点

### 1. 审批恢复风险

审批恢复是最容易被 checkpoint 改动影响的链路。

控制方式：

- 先引入 `AgentResumeState`
- 用审批全链路测试保护

### 2. 开发排障能力下降风险

开发阶段完整 state 很方便，如果直接删掉全量 checkpoint，可能影响排查。

控制方式：

- 保留结构化日志。
- 保留 VSCode debug 断点排查。
- 保留 tool logs。
- 保留 message metadata 的必要摘要。
- 保留 `CheckpointSnapshot` 的关键链路摘要。

### 3. 旧 sqlite 数据不兼容风险

旧环境中可能已经有 `state_json`。

控制方式：

- 本任务明确不做旧数据兼容。
- 开发和测试环境手动删除旧 sqlite 后重新初始化。
- 真正生产上线前，如需保留历史数据，另开 migration 任务。

### 4. 字段投影遗漏风险

如果 checkpoint 太瘦，可能缺少排障信息。

控制方式：

- tool/evidence/message 通过 refs 关联
- checkpoint 保存关键路由摘要
- 结构化日志和测试辅助脚本支持排查字段大小和投影结果

## 推荐提交顺序

1. `state_contracts` + `state_projector` + tests
2. checkpoint store 直接切换到 snapshot schema
3. orchestrator 改为保存 snapshot
4. approval resume state 改造
5. sqlite schema 收口和旧字段删除
6. docs + architecture acceptance tests

## 最终完成定义

当满足以下条件时，任务才算完成：

- 项目默认不再把完整 `AgentGraphState` 写入 checkpoint。
- Checkpoint、Resume、ToolLog、Evidence、Message 的职责边界清晰。
- 审批恢复不依赖完整 state。
- 不新增 DebugTraceStore、Retention、Cleanup 或 TTL。
- sqlite 初始化代码只保留新契约表结构，不做自动补字段、旧结构判断、旧表自动重建和 legacy fallback。
- 所有 state 字段有生命周期分类。
- 全量测试通过。
- 文档能指导后续开发者新增字段时应该放在哪里，而不是继续把所有东西塞进 GraphState。
