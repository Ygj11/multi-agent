# P5 Runtime Slimming And Log Governance Task

优先级：企业级 P5

## 任务定位

本任务用于对当前 Agent 主干运行时做一次系统性瘦身。

P4 系列已经补齐了 fallback 语义、规则治理、prompt manifest/eval、tool contract 等企业级治理能力。治理能力增强后，当前项目出现了一个新问题：主流程可观测性更强，但运行态 state、节点、日志、任务包装和历史字段开始偏厚。

本任务不改变业务能力，不改变 agent/skill 的核心选择策略，而是让主干流程更清晰、更轻、更容易排查和维护。

## 当前检查结论

基于当前代码检查和一次实际请求观察：

- `app/runtime/graph.py` 注册了 22 个 graph node。
- 一条正常 troubleshooting 请求实际经过 15 个 node。
- 最终 runtime state 中约 48 个 key。
- 较重字段示例：
  - `subagent_result` 约 19KB
  - `agent_selection` 约 4.7KB
  - `available_agents` 约 3.4KB
  - `assembled_task` 约 2.8KB
- 当前每个 graph node 都打印 enter/exit 两条日志，正常请求仅节点日志就约 30 条。

这不是“架构乱”，而是运行时治理能力叠加后，需要做一轮边界收敛。

## 和 P4.5 的边界

P4.5 关注：

- span / metrics / replay
- release readiness
- 上线准入检查

P5 关注：

- graph 节点是否过细
- state 是否携带不必要的大对象
- 日志是否过度打印
- 消息 metadata 是否误持久化 debug trace
- task/context 模型是否重复包装
- 历史字段是否残留

P5 可以在 P4.5 之前或之后执行，但建议在生产压测前完成。

## 总体目标

## 当前实施状态

已完成：

- P5.1 Runtime State Slimming
- P5.2 Graph Node Slimming
- P5.4 Message Metadata And Trace Boundary
- P5.3 Log Governance
- P5.5 Task Model Simplification
- P5.6 Historical Residue Cleanup

关键落地结果：

- `discover_agents` 节点已从 graph 注册和正常路径中删除。
- `assemble_task` 节点已合并进 `dispatch_agent`，任务对象只作为局部变量，不再写入 graph state。
- `available_agents`、`selected_agent_card`、`assembled_task`、`verification_results` 不再作为 `AgentGraphState` 字段。
- `agent_selection` 完整候选对象改为轻量 `agent_selection_summary`。
- `messages.metadata` 默认不再保存完整 `decision_traces` 和 `selected_skill_metadata` 大对象。
- 新增 `LOG_GRAPH_NODE_EVENTS`、`LOG_DISABLED_SERVICE_EVENTS`、`LOG_DECISION_TRACE_IN_MESSAGES` 配置。
- `RequestAdapter` 日志已从多条合并为一条 `request_adapted`。
- disabled knowledge service 默认不再逐次打印 INFO。
- LLM provider 日志支持 `request_id`、`trace_id`、`session_key` 链路字段。
- `AgentTaskAssembler` 直接生成 `SubAgentTask`，`DispatchAgentNode` 不再执行第二次模型转换，`AgentTaskEnvelope` 已删除。
- `SubAgentTask` 只保存 `agent_name`、`agent_card_version` 与任务字段；完整 AgentCard 不再进入 `metadata`，子 Agent 通过 `AgentCardLoader` 重新加载并校验。
- 已删除 Skill 选择中的 `extracted_interface_name` / `interface_match` 残留，以及 `OrchestratorContext` 中未消费的 Agent discovery 字段和 `conversation_window`。

### 目标 1：瘦 runtime state

让 `AgentGraphState` 只保留节点路由和后续执行必需字段。

大对象、debug trace、完整候选列表不默认进入 state。

### 目标 2：降低日志噪声

保留关键业务事件和错误事件，节点 enter/exit 改为可配置或 debug 级别。

### 目标 3：简化节点链路

删除或合并纯搬运节点，降低正常请求的 graph_path 长度。

### 目标 4：统一任务模型

减少 `AgentTaskEnvelope -> SubAgentTask` 的二次包装。

### 目标 5：清理历史残留

删除已经不符合当前业务建模的字段和逻辑，例如 `interface_name` skill scoring 残留。

## 不在本任务范围

- 不改变 intent taxonomy。
- 不改变 agent card 业务含义。
- 不改变 skill 文件业务内容。
- 不引入新的 direct-answer gate。
- 不重写 ToolExecutionPipeline。
- 不改造 MySQL 或 SQLite 表结构。
- 不删除审批主流程。
- 不删除 final compliance verification。
- 不改变 OpenSDK/Internal LLM provider 接入方式。

## P5.1 Runtime State Slimming

### 问题

当前 state 中存在一些运行时大字段和 debug 字段：

- `available_agents`
- `agent_selection`
- `selected_agent_card`
- `assembled_task`
- `verification_results`
- `query_rewrite_decision_trace`
- `intent_decision_trace`
- `agent_selection_decision_trace`

其中部分字段只是为了测试或调试，并非主干路由必需。

### 设计原则

`AgentGraphState` 只保存三类字段：

1. 路由必需字段
2. 后续节点执行必需字段
3. 响应 / checkpoint 需要的摘要字段

完整对象不进 state，必要时保留轻量 ref 或 summary。

### 建议改动

#### 1. 删除 `available_agents` 默认 state 输出

当前 `discover_agents` 节点写入 `available_agents`，但 `select_agent` 不消费它。

建议：

- 删除 `discover_agents` 节点；或
- 合并进 `select_agent` 内部，仅作为 selection 的局部变量。

如果仍需调试，可写入 `agent_selection_decision_trace.available_agent_count`，不要写完整 AgentCard 列表。

#### 2. 收缩 `agent_selection`

当前 state 保存完整 `selection.model_dump()`，其中包含 candidates 和 card 信息。

建议改为：

```python
agent_selection_summary = {
    "selected_agent": str,
    "confidence": float,
    "selection_method": str,
    "fallback_used": bool,
    "fallback_reason": str | None,
    "candidate_count": int,
}
```

完整 candidates 只进日志或 trace，不进入 state。

#### 3. 收缩 `selected_agent_card`

当前 state 保存完整 AgentCard。

建议改为：

```python
selected_agent_card_ref = {
    "agent_name": str,
    "version": str,
}
```

后续需要完整 AgentCard 时，通过 `AgentCardLoader.get_agent_card(agent_name)` 读取。

例外：审批 resume 如确实需要当时快照，应该进入 `approval_requests.resume_state_json` 的专用 resume payload，而不是常规 state 大字段。

#### 4. 删除 `assembled_task` state 大对象

`assemble_task` 只是参数组装层，`dispatch_agent` 立即消费。

建议：

- 合并 `assemble_task` 和 `dispatch_agent`；或
- `dispatch_agent` 直接调用 assembler，不把 `assembled_task` 写入 state。

#### 5. 合并 verification 字段

当前同时有：

- `verification_results`
- `pre_answer_verification_result`

建议保留一个字段：

```python
pre_answer_verification = {
    "passed": bool,
    "action": str,
    "code": str | None,
    "verifier_name": str,
}
```

完整 verification result 可进入日志，不默认进入 state。

### 验收标准

- 正常请求最终 state key 数减少至少 20%。
- `available_agents` 不再默认出现在 state。
- `assembled_task` 不再默认出现在 state。
- `agent_selection` 不再包含完整 candidates/card dump。
- checkpoint snapshot 仍能保存：
  - request_id
  - original_query
  - rewritten_query
  - intent/sub_intent
  - selected_agent
  - selected_skill_id
  - approval 信息
  - answer
  - graph_path
- 现有主干测试通过。

## P5.2 Graph Node Slimming

### 问题

当前 graph 正常请求路径较长：

```text
route_entry
load_session
save_user_message
query_rewrite
intent_recognition
build_orchestrator_context
discover_agents
select_agent
assemble_task
dispatch_agent
check_human_approval_required
pre_answer_verify
save_assistant_message
compress_short_memory
finalize_response
```

其中以下节点更像纯搬运：

- `route_entry`
- `discover_agents`
- `assemble_task`
- `finalize_response`

### 建议改动

#### 1. 保留 `route_entry` 但降低存在感

`route_entry` 用于 approval resume 分流，语义上可以保留。

但它没有业务动作，只追加 `graph_path`。

建议：

- 保留节点，但不打印 enter/exit INFO 日志。
- 或把路由判断放到 entry conditional，不再作为显式业务节点记录。

#### 2. 删除或合并 `discover_agents`

推荐删除。

替代方案：

```text
build_orchestrator_context -> select_agent
```

`select_agent` 内部自行从 `AgentCardLoader` 读取候选。

#### 3. 合并 `assemble_task` 与 `dispatch_agent`

推荐形成：

```text
select_agent -> dispatch_agent
```

`dispatch_agent` 内部完成：

1. 读取 `OrchestratorContext`
2. 读取 selected AgentCard
3. 构建 task
4. 调用 subagent

### 验收标准

- 正常请求路径减少至少 2 个节点。
- graph_path 仍能说明关键业务阶段。
- approval resume 流程不受影响。
- clarification 流程不受影响。
- 测试中不再依赖 `discover_agents` 作为必经节点。

## P5.3 Log Governance

### 问题

当前日志存在两个问题：

1. 日志数量偏多。
2. 有些日志缺少完整链路字段。

典型现象：

- 每个 graph node 都有 `langgraph_node_enter` 和 `langgraph_node_exit`。
- `RequestAdapter` 对一次请求打印多条相近日志。
- `knowledge_api_disabled` 在知识库关闭时仍每次打印。
- 部分 LLM 日志只有 `request_id`，缺少 `trace_id/session_key`。
- 部分 skill/knowledge 日志没有 request_id。

### 建议新增配置

```env
LOG_GRAPH_NODE_EVENTS=false
LOG_DISABLED_SERVICE_EVENTS=false
LOG_DECISION_TRACE_IN_MESSAGES=false
```

默认建议：

```text
local: LOG_GRAPH_NODE_EVENTS=true
test: false
staging/prod: false
```

### 建议改动

#### 1. graph enter/exit 降噪

`_log_node_enter` / `_log_node_exit` 只在配置开启时打印。

保留：

- request_received
- response_returned
- response_finalized
- llm_chat_finished
- tool_execution_finished
- approval events
- fallback/error/warning

#### 2. 合并 RequestAdapter 日志

当前：

- `session_key_created`
- `request_adapted`
- `original_query`

建议合并为一条：

```text
request_adapted
```

data 包含：

- session_key
- message_count
- original_query_preview
- auth_source

#### 3. disabled service 日志降级

`DisabledKnowledgeService` 可以不在每次 search/pre_search 打 INFO。

建议：

- 默认不打印。
- 或改 DEBUG。
- 或只在启动时记录一次 knowledge disabled。

#### 4. LLM 日志补齐上下文

所有 LLM provider 日志应支持：

- request_id
- trace_id
- session_key
- scene
- model
- latency_ms
- finish_reason

当前 LLMProvider Protocol 只有 request_id。

建议后续扩展为：

```python
async def chat(..., request_id=None, trace_id=None, session_key=None)
```

或者引入 `RuntimeCallContext`。

#### 5. 日志敏感信息治理

当前日志脱敏只按 key 匹配，无法识别字符串中的保单号/手机号/身份证号。

P5 不强制实现完整脱敏引擎，但至少应：

- 保单号、手机号、身份证号在日志 preview 中脱敏。
- query preview 不应暴露完整身份证/手机号。

### 验收标准

- prod/staging 默认不输出每个 graph node enter/exit。
- 正常请求日志量减少至少 40%。
- LLM 日志可通过 request_id/trace_id/session_key 串起来。
- RequestAdapter 日志合并为一条。
- DisabledKnowledgeService 不再每次输出 INFO。

## P5.4 Message Metadata And Trace Boundary

### 问题

`MessageCommitHandler.save_assistant_message()` 会把完整 decision trace 写入 messages.metadata：

```python
decision_traces = {
    query_rewrite,
    intent_recognition,
    agent_selection,
    skill_selection,
}
```

但 `graph_state.py` 中这些字段被标记为：

```text
kind = debug_temporary
persistence = none
```

这产生了边界不一致：标记为不持久化，但实际进入了 `messages` 表。

### 建议改动

#### 方案 A：默认不写完整 decision trace 到 messages

推荐。

messages.metadata 只保留摘要：

```python
{
    "request_id": "...",
    "trace_id": "...",
    "intent": "...",
    "sub_intent": "...",
    "selected_agent": "...",
    "selected_skill_id": "...",
    "fallback_summary": {
        "query_rewrite": "...",
        "intent_recognition": "...",
        "agent_selection": "...",
        "skill_selection": "..."
    }
}
```

完整 trace 走日志或未来 replay store。

#### 方案 B：更新 StateFieldAuthority

如果业务要求 messages 持久化完整 trace，则把这些字段的 persistence 改为 `message_store`。

不推荐，因为 messages 会变重，也会混合“用户对话记录”和“内部决策调试信息”。

### 验收标准

- `messages.metadata_json` 不再默认保存完整 decision trace。
- 多轮 query rewrite 仍能读取 clarification 所需字段：
  - `need_clarification`
  - `clarification_question`
  - `missing_required_entities`
  - `entities`
  - `intent/sub_intent`
- 现有多轮澄清测试通过。

## P5.5 Task Model Simplification

### 问题

当前主 agent 到 subagent 的任务传递存在两层：

```text
AgentTaskEnvelope
-> DispatchAgentNode
-> SubAgentTask
```

同时 `OrchestratorContext` 也携带部分重复字段：

- original_query
- rewritten_query
- intent
- entities
- short_summary
- recent_messages
- auth_context

### 建议改动

#### 1. 统一任务模型

选择一个主任务模型作为标准：

```text
SubAgentTask
```

或重命名为更通用的：

```text
AgentTask
```

推荐逐步做：

1. 先让 `AgentTaskAssembler` 直接输出 `SubAgentTask`。
2. 删除 `AgentTaskEnvelope`。
3. `DispatchAgentNode.dispatch()` 不再做模型转换。

#### 2. AgentCard 不进入 task 大对象

任务只保存：

```python
agent_name
agent_card_version
```

subagent 内部需要 AgentCard 时，从 loader 或 manager 获取。

如果必须保留快照，需要明确原因：比如审批 resume 需要当时可用工具快照。

#### 3. 精简 OrchestratorContext

建议删除或移动：

- `available_subagents`
- `agent_candidate_summaries`

建议保留：

- original_query
- rewritten_query
- intent/sub_intent
- entities
- entity_bag
- recent_messages
- short_summary
- lightweight_knowledge_hints
- auth_context

`conversation_window` 是否保留需评估：

- intent recognition 会用。
- subagent 阶段目前基本不直接用。

可以只留在 query/intent 阶段，不进入 subagent parent context。

### 验收标准

- 主 agent 到 subagent 只经过一个任务模型。
- `assembled_task` 不再写入 graph state。
- `SubAgentTask.metadata` 不再塞完整 AgentCard dump。
- 工具可见性、skill selection、approval resume 流程保持可用。

## P5.6 Historical Residue Cleanup

### 问题

当前仍有一些历史字段和逻辑不符合最新设计：

### 1. `interface_name` 残留

实体抽取中已删除 `interface_name` 方向，但 skill selection 仍有：

- `extracted_interface_name`
- `extract_interface_name`
- `interface_match`
- `required_context.interface_name`

建议清理：

- 删除 `SkillSelectionContext.extracted_interface_name`
- 删除 `SkillContextResolver.extract_interface_name`
- 删除 `SkillRuleScorer` 中 interface scoring
- 删除 tests 中对 interface_name 的依赖

例外：如果后续业务重新明确接口名是实体，则应回到 `EntityExtractor` 统一建模，而不是在 SkillContextResolver 内写小正则。

### 2. 默认 Skill 字段清理

当前已明确不需要默认 skill 兜底，`SkillMetadata` 和 SKILL.md frontmatter 不再保留默认 skill 标记。

### 3. `available_subagents` / `agent_candidate_summaries`

当前在 `OrchestratorContext` 中存在，但主流程基本不消费。

建议删除，或移动到 debug trace。

### 验收标准

- `rg "interface_name"` 只剩业务 mock 返回或历史文档，不再参与 skill scoring。
- 不存在默认 skill 字段参与 runtime 行为。
- 无未使用上下文字段进入 runtime schema。

## P5.7 Evidence Persistence Switch

### 问题

当前 `ToolExecutor._log()` 在每次工具执行后同时写：

1. `tool_execution_logs`
2. `evidence`

但当前主流程几乎不读取 `evidence`，它更偏未来审计/证据复用能力。

### 建议改动

新增配置：

```env
ENABLE_EVIDENCE_STORE=true
```

默认建议：

```text
local/test: false
staging/prod: true
```

或：

```text
local/test: true, 但只在有测试显式启用时开启
```

取决于你是否希望本地也保留证据表。

### 验收标准

- evidence 保存可通过配置开关控制。
- 关闭时不影响 tool_execution_logs。
- 关闭时不影响最终回答。
- 开启时现有 evidence tests 通过。

## 推荐执行顺序

推荐拆成以下子任务依次完成：

```text
P5.1 Runtime State Slimming
P5.2 Graph Node Slimming
P5.3 Log Governance
P5.4 Message Metadata And Trace Boundary
P5.5 Task Model Simplification
P5.6 Historical Residue Cleanup
P5.7 Evidence Persistence Switch
```

建议先做：

```text
P5.1 -> P5.2 -> P5.4 -> P5.3 -> P5.6 -> P5.5 -> P5.7
```

原因：

- 先瘦 state 和节点，收益最大。
- 再修 message metadata，避免 debug trace 继续进库。
- 日志治理依赖你对 state/节点边界的新判断。
- 历史残留清理风险较低。
- task model simplification 涉及面更广，放后面更稳。
- evidence switch 是独立开关，可最后做。

## 详细实施步骤

### Step 1：建立 baseline 测试

新增测试或脚本记录当前 baseline：

- 正常请求 graph_path
- state key count
- forbidden state fields
- messages metadata 大小
- 日志开关行为

建议新增：

```text
tests/test_runtime_state_slimming.py
tests/test_log_governance.py
tests/test_message_metadata_boundary.py
```

### Step 2：删除 discover_agents 节点

改动：

- `app/runtime/graph.py`
- `app/runtime/node_contracts.py`
- `app/runtime/graph_state.py`
- 相关测试

验收：

- graph 不再注册 `discover_agents`。
- `available_agents` 不再进入 state。
- agent selection 仍正常。

### Step 3：收缩 selection 和 task state

改动：

- `select_agent` 返回 summary，不返回完整 `agent_selection`。
- `selected_agent_card` 改为 ref，或只保留 `selected_agent`。
- `assemble_task` 不再写 `assembled_task`。

验收：

- state 中不再有完整 AgentCard dump。
- dispatch 仍能拿到完整 AgentCard。

### Step 4：调整 message metadata

改动：

- `MessageCommitHandler.save_assistant_message`
- 多轮澄清依赖的 metadata 保留。
- decision trace 改为 summary 或开关控制。

验收：

- 多轮澄清仍可识别 pending clarification。
- `messages.metadata_json` 不再保存完整 trace。

### Step 5：日志开关与上下文补齐

改动：

- settings 新增日志配置。
- `_log_node_enter/_log_node_exit` 受配置控制。
- RequestAdapter 日志合并。
- Knowledge disabled 日志降噪。
- LLM chat 支持 trace_id/session_key。

验收：

- 单请求日志量显著下降。
- LLM 日志链路字段完整。

### Step 6：清理历史残留字段

改动：

- 删除 interface_name scoring。
- 清理 `SkillSelectionContext.extracted_interface_name`。
- 默认 skill 字段已删除，不再保留 deprecated 兼容。

验收：

- 测试通过。
- 无 runtime 代码依赖 interface_name。

### Step 7：Evidence 保存开关

改动：

- settings 新增 `ENABLE_EVIDENCE_STORE`。
- create_app 根据配置决定是否注入 `EvidenceStore`。
- tests 显式覆盖开启/关闭场景。

验收：

- 默认行为符合环境预期。
- tool logs 不受影响。

## 风险点

### 1. 多轮澄清依赖 message metadata

不能误删：

- `need_clarification`
- `clarification_question`
- `missing_required_entities`
- `entities`
- `intent`
- `sub_intent`

### 2. 审批 resume 依赖 pending messages/tools

不能把审批恢复所需字段从 `approval_requests.resume_state_json` 中删掉。

尤其保留：

- `pending_messages`
- `pending_tools`
- `pending_tool_call`
- `selected_skill_id`
- `selected_skill_metadata`
- `skill_selection_score`
- `skill_selection_reason`

### 3. AgentCard 快照与动态读取的权衡

如果从 state 中删除完整 AgentCard，dispatch 时需要重新从 loader 读取。

风险：

- 请求执行过程中 AgentCard 文件热更新，可能导致选择时和执行时版本不一致。

建议：

- 本地开发可接受动态读取。
- 生产可以通过 `agent_name + version` 做一致性校验。

### 4. 日志降噪不能影响错误定位

INFO 日志减少后，必须保证以下事件仍可定位：

- request received/returned
- LLM error/fallback
- intent unknown
- no skill
- tool error/timeout
- approval required
- verification block

## 验收总标准

完成 P5 后需要满足：

- 正常请求 graph_path 至少减少 2 个节点。
- 正常请求 final state key 数减少至少 20%。
- `available_agents` 不进入 state。
- `assembled_task` 不进入 state。
- 完整 `decision_trace` 不默认进入 `messages.metadata_json`。
- graph node enter/exit 日志可关闭，且 staging/prod 默认关闭。
- 单请求 INFO 日志量减少至少 40%。
- LLM 日志支持完整链路字段。
- `interface_name` 不再参与 skill scoring。
- 全量测试通过。

## 建议新增质量门禁

新增测试断言：

```python
FORBIDDEN_RUNTIME_STATE_FIELDS = {
    "available_agents",
    "assembled_task",
}
```

新增 message metadata 断言：

```python
assert "decision_traces" not in assistant_message["metadata"]
```

新增日志配置断言：

```python
assert settings.log_graph_node_events is False when APP_ENV in {"staging", "prod"}
```

## 任务完成后的预期主干路径

目标正常路径：

```text
load_session
save_user_message
query_rewrite
intent_recognition
build_orchestrator_context
select_agent
dispatch_agent
check_human_approval_required
pre_answer_verify
save_assistant_message
compress_short_memory
finalize_response
```

进一步可选目标：

```text
load_session
save_user_message
query_rewrite
intent_recognition
select_agent
dispatch_agent
pre_answer_verify
save_assistant_message
compress_short_memory
finalize_response
```

第二个目标需要把 `build_orchestrator_context` 合并到 `dispatch_agent` 前的局部上下文构建中，改动更大，建议作为 P5 后半段或 P5.5 实施。
