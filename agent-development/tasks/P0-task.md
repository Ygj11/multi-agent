# P0 Platform Slimming Tasks

P0 任务目标：先稳住企业级 harness 的主链路边界，降低 `Graph / ToolExecutor / create_app` 三个核心入口的复杂度。P0 不追求新增能力，重点是让现有能力更清晰、更可测试、更容易上线。

## 1. 拆瘦 ToolExecutor 为执行 Pipeline

### 目标

把 `ToolExecutor.execute` 中的参数校验、Agent 可见性、权限、资源访问、pre_tool verification、人工审批、真实执行、日志/evidence 记录拆成清晰阶段。

### 为什么要做

当前 `app/tools/executor.py` 职责过多，是后续接真实权限、审批、MCP、外部工具、审计时最容易膨胀的点。企业级 harness 中，工具执行应该是一个可插拔 pipeline，而不是一个巨型方法。

### 涉及文件

- `app/tools/executor.py`
- `app/tools/registry.py`
- `app/tools/tool_execution_log_store.py`
- `app/auth/authorization_service.py`
- `app/verification/*`
- `app/evidence/*`
- `tests/test_tool_*`
- `tests/test_approval_*`

### 建议实现

新增或拆出：

```text
app/tools/execution_pipeline.py
app/tools/guards/availability_guard.py
app/tools/guards/argument_guard.py
app/tools/guards/authorization_guard.py
app/tools/guards/verification_guard.py
app/tools/guards/approval_guard.py
app/tools/dispatcher.py
app/tools/recorder.py
```

推荐执行顺序：

```text
tool exists
-> AgentCard visibility
-> required arguments
-> scope/resource authorization
-> pre_tool VerificationService
-> write approval guard
-> local/MCP dispatch
-> log/evidence recording
```

### 验收标准

- `ToolExecutor.execute` 主体变成 pipeline 调用，不再承载全部细节。
- 原有 tool schema、权限、审批、MCP、日志测试全部通过。
- 新增测试覆盖 guard 顺序。
- 缺参优先于审批。
- 写工具不绕过审批。
- approved tool 仍有幂等和参数一致性校验。

## 2. 拆瘦 graph.py 审批/验证/澄清节点逻辑

### 目标

保留 LangGraph 节点名称和路由结构，但把复杂节点内部逻辑下沉到 handler/service。

### 为什么要做

`app/runtime/graph.py` 当前既是流程图，又处理审批链、审批恢复、verification route、澄清回答、消息保存、短期记忆压缩。Graph 应该主要表达“节点和边”，而不是塞满业务操作。

### 涉及文件

- `app/runtime/graph.py`
- `app/approval/service.py`
- `app/runtime/orchestrator.py`
- `app/verification/*`
- `app/session/message_store.py`
- `app/memory/short_term_memory_manager.py`
- 新增 `app/runtime/handlers/*`
- `tests/test_approval_*`
- `tests/test_clarification_flow.py`
- `tests/test_final_compliance_check.py`

### 建议实现

新增：

```text
app/runtime/handlers/approval_handler.py
app/runtime/handlers/verification_handler.py
app/runtime/handlers/clarification_handler.py
app/runtime/handlers/message_commit_handler.py
app/runtime/handlers/memory_handler.py
```

Graph 节点变成：

```python
async def create_approval_request(self, state):
    return await self.approval_handler.create_request(state)
```

### 验收标准

- `AgentGraphFactory.build()` 的节点和路由语义不变。
- `graph.py` 行数明显下降。
- 审批 pending、approved resume、second approval、rejected、idempotency 测试通过。
- clarification 仍经过 `pre_answer_verify`。
- pending answer 仍保存 message、压缩 memory。

## 3. 拆分 main.py Bootstrap

### 目标

把 `create_app` 中的依赖构造拆成分组 bootstrap，让 app 启动逻辑可读、可测、可替换。

### 为什么要做

当前 `app/main.py::create_app` 同时创建 storage、LLM、knowledge、MCP、tools、verification、approval、skills、subagents、graph、routes。上线后不同环境的装配差异会越来越多，继续堆在 main.py 会失控。

### 涉及文件

- `app/main.py`
- 新增 `app/bootstrap/storage.py`
- 新增 `app/bootstrap/llm.py`
- 新增 `app/bootstrap/tools.py`
- 新增 `app/bootstrap/verification.py`
- 新增 `app/bootstrap/approval.py`
- 新增 `app/bootstrap/agents.py`
- 新增 `app/bootstrap/graph.py`
- `tests/test_main.py`
- `tests/test_*initialization*`

### 建议实现

拆成：

```text
build_storage(settings)
build_llm(settings)
build_tooling(settings, db, llm_provider)
build_verification(llm_provider)
build_approval(...)
build_agents(...)
build_graph(...)
```

`create_app` 只保留：

```text
settings
-> bootstrap dependencies
-> create FastAPI
-> attach app.state
-> register routes
-> lifespan
```

### 验收标准

- `/api/chat`、`/api/approval/callback`、`/api/approval/{approval_id}` 行为不变。
- `app.state` 暴露对象不变或有明确迁移。
- `create_app` 更短，依赖分组清楚。
- 初始化测试通过。

## 4. 明确 Mock / Production 边界

### 目标

把生产主链路、MVP mock、测试 fake 分清楚，避免上线时误用 mock 数据或 mock HTTP。

### 为什么要做

当前 `app/tools/agent_tools.py` 中同时有工具注册、业务 mock 数据、mock HTTP response。这对 MVP 很快，但上线前风险较大。

### 涉及文件

- `app/tools/agent_tools.py`
- `app/integrations/*`
- `tests/fakes/*`
- `tests/test_endo_aftercare_tools.py`
- `tests/test_endo_aftercare_tool_calling_loop.py`

### 建议实现

拆分：

```text
app/tools/agent_tools.py
app/tools/handlers/endo_tools.py
app/tools/handlers/policy_tools.py
app/tools/definitions/endo_definitions.py
tests/fakes/fake_endo_tools.py
```

生产语义中，mock handler 应明确标记：

```text
MVP mock implementation, not production wired.
```

### 验收标准

- 生产注册入口不再包含大段 mock 数据。
- 测试 fake 放在 tests 范围。
- `notice_*` 写工具仍保持 `is_write=True`。
- tool calling 测试仍通过。

## 5. 固化主链路契约测试

### 目标

在瘦身前后固定主链路行为，防止 refactor 改坏流程。

### 为什么要做

P0 任务会移动核心代码。没有契约测试，容易出现“单元测试都过，但主流程断了”的情况。

### 涉及文件

- `tests/test_main_flow_acceptance.py`
- `tests/test_approval_*`
- `tests/test_tool_calling_runner_*`
- `tests/test_auth_*`
- `tests/test_verification_*`

### 建议新增覆盖

```text
/api/chat normal read path
/api/chat clarification path
/api/chat write tool approval pending path
approval callback approved resume path
approval callback rejected path
tool permission denied path
pre_answer verification patch path
```

### 验收标准

- P0 refactor 前先跑通契约测试。
- P0 每个任务完成后契约测试仍通过。
- 输出字段 `ChatResponse` 不回归。
- Graph path 关键节点不回归。

## 6. Graph State 权威字段表与冗余字段瘦身一期

### 目标

在不大改 Graph state 结构的前提下，先明确每类 state 字段的权威来源，并清理低风险冗余字段，为后续更大范围的节点字段瘦身打基础。

### 为什么要做

当前各节点之间存在字段重复，例如：

```text
principal / auth_context.principal
entities / entity_bag / conversation_window
recent_messages / orchestrator_context.recent_messages
selected_skill_* / subagent_result.selected_skill_*
approval_request / approval_id / approval_status / approval_payloads
verification_results / pre_answer_verification_result
```

这些字段不是全部错误，但缺少“哪个字段是权威字段”的规则。继续堆功能会让节点间输入输出越来越难理解。字段瘦身应该尽早做，但必须在主链路契约测试之后做，避免破坏 `/api/chat`、审批、verification 和 memory 主链路。

### 涉及文件

- `app/runtime/graph_state.py`
- `app/runtime/graph.py`
- `app/runtime/context_builder.py`
- `app/agents/task_assembler.py`
- `app/agents/dispatcher.py`
- `app/subagents/base.py`
- `app/schemas/runtime.py`
- `app/schemas/subagent.py`
- `app/schemas/approval.py`
- `tests/test_main_flow_acceptance.py`
- `tests/test_approval_*`
- `tests/test_clarification_flow.py`
- `tests/test_final_compliance_check.py`

### 建议实现

第一步先写字段权威表，不立即大改嵌套结构：

```text
request_id / trace_id / session_key / thread_id -> request identity 权威字段
auth_context -> 身份上下文权威字段
principal -> 短期保留为 auth_context.principal 的展开缓存
entities -> routing/task 使用的 compact dict
entity_bag -> richer entity container
conversation_window -> 历史窗口，不再作为实体权威来源
subagent_result -> selected_skill_* 的权威来源
approval_id / approval_status / approval_required -> Graph 顶层审批摘要
ApprovalStore.approval_request -> 审批详情权威来源
pre_answer_verification_result -> 最终验证权威结果
answer -> 最终返回文本权威字段
graph_path -> debug 字段
```

第一期只清理低风险冗余：

```text
1. 后续节点不再直接依赖顶层 selected_skill_*，优先从 subagent_result 读取。
2. 合并或弱化 verification_results，只保留 pre_answer_verification_result 作为 Graph 路由权威。
3. Graph 顶层长期只保留 approval_id / approval_status / approval_required，审批详情以 ApprovalStore 为权威。
4. available_agents 仅作为 debug/trace 字段，不作为后续节点权威输入。
5. 明确 orchestrator_context 是派生上下文 snapshot，不是 request/query/entities 的权威来源。
```

暂时不要做：

```text
1. 不要一次性改成 request/understanding/routing/execution/response/debug 嵌套 state。
2. 不要删除 request_id、trace_id、session_key、thread_id、original_query、rewritten_query、intent、entities、assembled_task、subagent_result、answer、graph_path。
3. 不要改变 ChatResponse schema。
```

### 验收标准

- 有一份代码内或测试内可验证的 Graph state 字段权威说明。
- 第一阶段清理后 `/api/chat` 返回结构不变。
- Graph path 关键节点不变。
- clarification 分支仍经过 `pre_answer_verify`。
- approval pending / approved resume / rejected 流程不回归。
- `save_assistant_message` 保存的是最终 verify 后 answer。
- `compress_short_memory` 输入字段不变。
- 所有主链路契约测试、审批测试、verification 测试通过。
