# Magic String Governance

本文档是“魔法字符串治理”的阶段 0 审计与实施设计。阶段 0 只做审计和方案设计，不修改业务代码。

本次治理的目标不是消灭所有字符串，也不是建立一个巨大 `constants.py`。治理对象是那些已经成为系统协议、有限状态、图路由、持久化值或跨模块共享值的字符串。

## 1. 当前结论

当前项目中确实存在大量协议字符串，主要集中在：

- `app/runtime/graph.py`：LangGraph 节点名、条件路由值、`graph_path` 写入值。
- `app/runtime/route_policy.py`：条件路由返回值和业务状态字符串比较。
- `app/runtime/node_contracts.py`：节点名、State 字段名、路由值的静态契约。
- `app/runtime/graph_state.py`：State 字段、owner、kind、persistence 等生命周期声明。
- `app/verification/task_completion/schemas.py`：任务完成度状态仍是 `Literal[...]`。
- `app/subagents/tool_calling_runner.py`：工具循环停止原因仍是 `Literal[...]` 和裸字符串。
- `app/schemas/approval.py`：审批状态仍是 `Literal[...]`，并被数据库持久化。
- `app/verification/schemas.py`：通用验证 stage/action/severity 仍是 `Literal[...]`。
- `app/tools/base.py` 与 `app/tools/contracts.py`：工具 scope/source/operation/risk/data classification 重复定义。
- `app/llm/model_config.py` 与多处 `llm_provider.chat(scene=...)`：LLM scene 以裸字符串散落。
- `app/observability/logger.py` 与各模块 `log_event("...")`：稳定日志 event 名称散落。
- `app/runtime/failure_codes.py` 与 `app/tools/error_codes.py`：已有常量化错误码，但尚未统一为描述型枚举。

治理优先级应从“影响路由和持久化的有限集合”开始，而不是先处理普通文案、Prompt、SQL、URL 或工具业务 payload 字段。

## 2. 审计方法

本次审计使用了三类方式：

1. 直接阅读主流程文件：`graph.py`、`route_policy.py`、`graph_state.py`、`node_contracts.py`。
2. 读取审批、验证、工具、子 Agent 相关 schema 和 handler。
3. 使用 AST 扫描重点目录中的字符串字面量，观察高频和跨模块共享字符串。

重点目录：

```text
app/runtime/
app/runtime/handlers/
app/verification/
app/tools/
app/subagents/
app/approval/
app/schemas/
app/observability/
app/llm/
```

## 3. 字符串分类审计

| 分类 | 代表字符串 | 主要位置 | 当前用途 | 有限集合 | 跨模块共享 | 持久化/协议风险 | 推荐治理 |
| --- | --- | --- | --- | --- | --- | --- | --- |
| LangGraph 节点名称 | `route_entry`、`load_session`、`query_rewrite`、`verify_task_completion` | `app/runtime/graph.py`、`node_contracts.py`、测试 | 注册节点、边定义、`graph_path`、节点日志 | 是 | 是 | `graph_path` 进入 checkpoint，测试依赖节点名 | 新增 `GraphNode(StrEnum)`，value 保持不变 |
| 条件路由返回值 | `resume`、`normal`、`clarify`、`continue`、`required`、`not_required`、`skip_completion`、`passed`、`retry`、`fallback` | `route_policy.py`、`graph.py`、`node_contracts.py` | LangGraph conditional edge 的机器值 | 是 | 是 | 路由值不直接入库，但测试和图边依赖 | 按语义拆成多个 Route enum |
| 任务完成度状态 | `PASS`、`CONTINUE`、`NEED_USER`、`HUMAN_HANDOFF`、`FAILED` | `verification/task_completion/schemas.py`、`service.py`、`task_completion_handler.py`、`route_policy.py` | Completion Verify 业务结果 | 是 | 是 | 进入 `task_completion_verification_result`、checkpoint projection、eval | 新增 `TaskCompletionStatus(StrEnum)` |
| 工具循环停止原因 | `final`、`error`、`max_iterations`、`human_approval_required`、`max_consecutive_tool_failures`、`max_same_tool_failures`、`max_duplicate_tool_calls` | `subagents/tool_calling_runner.py`、`subagents/base.py`、`approval_handler.py`、`task_completion/service.py` | ToolCallingRunner 停止原因 | 是 | 是 | 进入 subagent metadata、approval resume、verification context | 新增 `ToolStoppedReason(StrEnum)` |
| 审批状态 | `created`、`pending`、`approved`、`executing`、`rejected`、`expired`、`submit_failed`、`completed`、`failed`、`manual_intervention_required` | `schemas/approval.py`、`approval/service.py`、`approval/store.py` | 审批台账状态 | 是 | 是 | 数据库 `approval_requests.status`、callback response | 新增 `ApprovalStatus(StrEnum)`，保持原 value |
| 审批动作/事件 | `submitted`、`submit_failed`、`approved`、`rejected`、`completed_with_next_approval`、`result_callback_delivered`、`result_callback_failed` | `approval/service.py`、`approval/store.py` | approval_events.event_type | 是 | 局部为主 | 数据库 `approval_events.event_type` | 可新增 `ApprovalEventType(StrEnum)`，中优先级 |
| Verification stage/action | `pre_tool`、`pre_answer`、`allow`、`patch`、`block`、`manual`、`retry` | `verification/schemas.py`、`verification/service.py`、`verification_handler.py`、`tools/executor.py` | 通用验证阶段和动作 | 是 | 是 | `VerificationResult` 进入 State，影响路由 | 新增 `VerificationStage`、`VerificationAction`、`VerificationSeverity` |
| 工具 scope/source/operation | `public`、`private`、`mcp`、`local`、`read`、`write`、`notify`、`execute`、`search`、`delete`、`ddl` | `tools/base.py`、`tools/contracts.py`、`tools/registry.py`、`tools/executor.py` | 工具可见性、执行来源、审批/权限语义 | 是 | 是 | ToolDefinition/ToolContract/YAML/DB 日志 | 新增 `ToolScope`、`ToolSource`、`ToolOperation`，消除重复 Literal |
| 风险和数据分级 | `low`、`medium`、`high`、`public`、`internal`、`confidential`、`sensitive` | `tools/base.py`、`tools/contracts.py`、`agent_card.py` | 审批风险、数据治理信号 | 是 | 是 | AgentCard/ToolContract 机器值 | 新增 `RiskLevel`、`DataClassification`；注意 `public` 同时也是 ToolScope value |
| Agent 执行模式 | `initial`、`repair` | `graph.py`、`state_contracts.py`、`schemas/subagent.py`、`repair_task_builder.py` | 首次执行与修复执行控制 | 是 | 是 | checkpoint、resume_state、SubAgentTask | 新增 `ExecutionMode(StrEnum)` |
| Query rewrite 类型 | `direct`、`contextual_follow_up`、`clarification_reply`、`new_request`、`clarification_required` | `llm/output_schemas.py`、`query/query_rewrite_node.py`、`graph.py` | Query Rewrite 语义分类 | 是 | 是 | checkpoint `rewrite_type`，Prompt/Eval 依赖 | 新增 `RewriteType(StrEnum)`，中优先级 |
| LLM parse status | `success`、`json_parse_failed`、`schema_validation_failed` | `llm/output_schemas.py` | 严格 JSON 解析结果 | 是 | 中 | 决策 trace 与测试 | 新增 `LLMParseStatus(StrEnum)` |
| LLM scene | `query_rewrite`、`intent_recognition`、`agent_selection`、`skill_selection`、`subagent_reasoning`、`task_completion_verifier`、`final_compliance`、`summary` | `llm/model_config.py`、各 LLM 调用点 | 选择模型、Prompt scene、日志诊断 | 是 | 是 | 不直接入库，但影响模型选择 | 新增 `LLMScene(StrEnum)`，model_config key 使用 enum value |
| 日志 event | `request_received`、`response_returned`、`tool_execution_finished`、`task_completion_handoff`、`langgraph_node_enter`、`langgraph_node_exit` | `observability/logger.py` 调用方 | 结构化日志检索字段 | 是，部分是 | 是 | 未来日志云会按 event 检索，不应随意改 value | 新增 `GraphEvent` / `RuntimeEventName`，只治理稳定 event |
| 稳定错误码 | `llm_json_parse_failed`、`tool_not_found`、`permission_denied`、`mcp_tool_error` | `runtime/failure_codes.py`、`tools/error_codes.py`、多处 error 字段 | 失败分类、测试、ToolResult.error | 是 | 是 | API/日志/DB/tool observation 可能依赖 | 从常量文件平滑迁移到 `FailureCode`、`ToolErrorCode` |
| State 字段名 | `entities`、`entity_bag`、`approval_required`、`selected_skill_id`、`graph_path` | `graph_state.py`、`node_contracts.py`、`state_projector.py`、`graph.py` | LangGraph State 字段 | 是，但数量多 | 是 | checkpoint/resume/message metadata | 不机械常量化；通过 `AgentGraphState` 和 contract 校验治理 |
| 用户文案和 Prompt | “请补充...”、Prompt 正文、最终回答、安全话术 | handlers、prompts、verifiers | 给用户或 LLM 的自然语言 | 否 | 否 | 不应作为机器协议 | 保持字符串，不纳入本次枚举治理 |
| JSON Schema / SQL / URL / 工具 payload 字段 | `type`、`properties`、`required`、`policyNo`、SQL 文本、endpoint path | tools、storage、api clients | 外部协议或标准格式字段 | 通常不是本系统有限状态 | 跨外部系统 | 改名风险高 | 保持原样；只在需要时由 schema/adapter 管理 |

## 4. 当前重复和风险点

### 4.1 业务状态与图路由混在一起

`RoutePolicy.route_task_completion()` 当前读取：

```python
status = str(result.get("status") or "").upper()
```

然后把业务状态映射为路由字符串：

```text
PASS -> passed
CONTINUE -> continue
NEED_USER -> need_user
HUMAN_HANDOFF -> handoff
其他 -> failed
```

问题：

- `str(...).upper()` 会掩盖非法状态值。
- 业务状态 `"CONTINUE"` 和图路由 `"continue"` 语义接近但不是同一个概念。
- 非法结构没有明确日志。

治理目标：

- `TaskCompletionStatus` 表达业务结果。
- `TaskCompletionRoute` 表达图下一步。
- 解析失败或非法状态记录稳定日志 event，并安全降级到 `failed`。

### 4.2 节点名有多处来源

当前节点名同时出现在：

- `graph.add_node(...)`
- `graph.add_edge(...)`
- `graph.add_conditional_edges(...)`
- `self._append_path(state, "...")`
- `self._log_node_enter(state, "...")`
- `NODE_CONTRACTS`
- `tests/test_node_contracts.py`

问题：

- 重命名节点时容易漏改。
- `graph_path` 是 checkpoint/debug 事实，机器值必须稳定。

治理目标：

- `GraphNode` 是唯一节点名来源。
- `NODE_CONTRACTS` key 仍保持字符串 value，但由 `GraphNode.value` 生成。
- `graph_path` 中继续写入原始字符串 value。

### 4.3 `Literal[...]` 分散在多个领域

当前大量有限集合使用 `Literal[...]`：

```text
ApprovalStatus
VerificationAction
VerificationStage
TaskCompletionStatus
ToolScope
ToolSource
ToolOperation
RiskLevel
DataClassification
ToolCallingRunResult.stopped_reason
QueryRewriteLLMOutput.rewrite_type
```

`Literal` 可以做 Pydantic 校验，但没有：

- 统一 description；
- IDE 枚举补全；
- 可复用方法；
- 领域内统一导入位置。

治理目标：

- 将稳定、跨模块、有限集合迁移到 `DescribedStrEnum`。
- 保持 Pydantic 模型 JSON 序列化为原字符串。
- 保持历史 DB/checkpoint 字符串可通过 `Enum(raw_value)` 恢复。

### 4.4 工具错误码已有常量，但风格不统一

`app/tools/error_codes.py` 已经集中定义：

```text
TOOL_NOT_FOUND
TOOL_NOT_AVAILABLE_FOR_AGENT
MISSING_REQUIRED_ARGUMENT
HUMAN_APPROVAL_REQUIRED
...
```

`app/runtime/failure_codes.py` 也集中定义了 LLM、taxonomy、agent/skill fallback code。

问题：

- 它们是纯常量，没有描述。
- 调用方仍然有不少裸字符串，例如 `approval_store_not_configured`、`approval_not_found`、`approval_arguments_mismatch`。
- `missing_required_argument:*` 这类带参数错误码需要区分 code prefix 和 detail。

治理目标：

- 保留当前常量文件兼容一阶段；
- 新增枚举后逐步替换调用点；
- 对带 detail 的错误码定义 prefix enum，不强行把完整动态字符串枚举化。

## 5. 不治理范围

以下字符串不应在本轮治理中枚举化：

| 类型 | 示例 | 不治理原因 |
| --- | --- | --- |
| 用户展示文案 | “当前回复未通过最终验证...” | 自然语言，不是机器协议 |
| Prompt 正文 | `app/prompts/**` | 由 Prompt 管理，不应变成代码枚举 |
| LLM 输出文本 | answer、reason、summary | 动态内容 |
| SQL 语句 | `CREATE TABLE...`、`SELECT...` | 数据库协议文本 |
| URL / path | `/api/chat`、`/mcp/tools/call` | 外部 HTTP 协议 |
| JSON Schema 标准字段 | `type`、`properties`、`required` | 标准协议字段 |
| 业务接口字段 | `policyNo`、`applySeq`、`endorseType` | 外部接口入参名，不是本系统状态 |
| 单一局部字符串 | 只在一个私有方法里出现一次的错误详细描述 | 常量化收益低 |
| 动态错误详情 | `permission_denied:{reason}` | prefix 可治理，detail 保持动态 |
| MCP 工具注册名 | `mcp.workflow.query_refund_task` | 外部工具协议名，不能被内部枚举限制 |

## 6. 建议目录设计

推荐新增：

```text
app/schemas/enums/
├── __init__.py
├── base.py
├── graph.py
├── task_completion.py
├── approval.py
├── verification.py
├── tool.py
├── execution.py
├── llm.py
├── observability.py
└── errors.py
```

职责：

| 文件 | 职责 |
| --- | --- |
| `base.py` | `DescribedStrEnum` 基类和少量序列化辅助测试对象 |
| `graph.py` | `GraphNode` 和各类 LangGraph route enum |
| `task_completion.py` | `TaskCompletionStatus`、`TaskCompletionRoute` |
| `approval.py` | `ApprovalStatus`、`ApprovalCallbackStatus`、`ApprovalEventType` |
| `verification.py` | `VerificationStage`、`VerificationAction`、`VerificationSeverity` |
| `tool.py` | `ToolScope`、`ToolSource`、`ToolOperation`、`RiskLevel`、`DataClassification`、`ToolStoppedReason` |
| `execution.py` | `ExecutionMode` 等跨 runtime/subagent 的执行控制状态 |
| `llm.py` | `LLMScene`、`LLMParseStatus`、`LLMAttemptStatus` |
| `observability.py` | 稳定日志 event 名称 |
| `errors.py` | runtime/tool 稳定错误码枚举；可与旧常量文件共存一个阶段 |

为什么不放一个 `constants.py`：

- 不同领域的协议值有不同生命周期和持久化边界。
- 分文件可以让开发者在对应领域查找和补充 description。
- Pydantic schema 和路由函数可以导入明确领域枚举，而不是依赖巨大常量池。

## 7. 分阶段迁移计划

### 阶段 1：基础枚举能力

目标：

- 新增 `DescribedStrEnum`。
- 验证 `.value`、`.description`、Pydantic 序列化和历史 value 恢复。

建议新增文件：

```text
app/schemas/enums/__init__.py
app/schemas/enums/base.py
tests/test_described_str_enum.py
```

验收：

- `TaskExample(status=EnumValue).model_dump(mode="json")` 只输出机器值。
- description 不进入 `model_dump()` 和 `model_dump_json()`。
- `Enum("existing_value")` 可以恢复。

### 阶段 2：LangGraph 节点和路由

目标：

- 新增 `GraphNode`。
- 新增 route enum：
  - `EntryRoute`
  - `ClarificationRoute`
  - `ApprovalRequiredRoute`
  - `TaskCompletionRoute`
  - `AfterApprovalCreateRoute`
  - `VerificationRoute`
- 改造 `graph.py` 节点注册、边定义、`graph_path`、节点日志。
- 改造 `route_policy.py` 返回 enum。

建议修改文件：

```text
app/schemas/enums/graph.py
app/runtime/graph.py
app/runtime/route_policy.py
app/runtime/node_contracts.py
tests/test_node_contracts.py
tests/test_route_policy.py
tests/test_langgraph_flow.py
```

兼容要求：

- 节点 value 不变。
- 条件路由 value 不变。
- `graph_path` 仍是 list[str]，不是 enum 对象。

### 阶段 3：运行状态治理

目标：

- 将以下 `Literal[...]` 迁移为枚举：
  - `TaskCompletionStatus`
  - `ToolStoppedReason`
  - `ApprovalStatus`
  - `VerificationStage`
  - `VerificationAction`
  - `VerificationSeverity`
  - `ExecutionMode`
  - `ToolScope`
  - `ToolSource`
  - `ToolOperation`
  - `RiskLevel`
  - `DataClassification`

建议修改文件：

```text
app/verification/task_completion/schemas.py
app/subagents/tool_calling_runner.py
app/schemas/approval.py
app/verification/schemas.py
app/tools/base.py
app/tools/contracts.py
app/schemas/subagent.py
app/schemas/runtime.py
app/runtime/state_contracts.py
```

兼容要求：

- 所有 enum value 使用当前字符串。
- `model_dump(mode="json")` 与改造前保持一致。
- 数据库已有值可以通过 enum 恢复。

### 阶段 4：State 类型治理

目标：

- 不做 State key 常量化。
- 强化 `AgentGraphState` 字段注释和类型。
- 路由函数不再接受裸 `dict[str, Any]`，优先使用 `AgentGraphState`。
- 复杂嵌套结果读取时用对应 Pydantic model validate，非法结构安全降级并记录日志。

建议修改文件：

```text
app/runtime/graph_state.py
app/runtime/route_policy.py
app/runtime/state_projector.py
app/runtime/handlers/task_completion_handler.py
app/runtime/handlers/verification_handler.py
```

注意：

- `AgentGraphState` 仍是 TypedDict，保证 LangGraph 和 checkpoint JSON 兼容。
- 写入 State 的 Pydantic 模型继续使用 `model_dump(mode="json")`。

### 阶段 5：日志、错误码和 LLM Scene

目标：

- 新增 `LLMScene`，替换 `scene="..."`。
- 新增稳定日志 event enum，只治理高价值事件。
- 将 `runtime/failure_codes.py` 和 `tools/error_codes.py` 平滑迁移到 enum，旧常量先保留并指向 enum value。

建议修改文件：

```text
app/schemas/enums/llm.py
app/schemas/enums/observability.py
app/schemas/enums/errors.py
app/llm/model_config.py
app/query/query_rewrite_node.py
app/query/intent_recognition_node.py
app/agents/llm_router.py
app/skills/reranker.py
app/subagents/tool_calling_runner.py
app/verification/task_completion/service.py
app/verification/verifiers/compliance_verifier.py
app/observability/logger.py
app/runtime/failure_codes.py
app/tools/error_codes.py
```

不建议一次性治理所有 `log_event()` message。只治理 `event` 机器名。

### 阶段 6：全量扫描和收尾

目标：

- 重新扫描重点目录。
- 输出已治理字符串清单、保留字符串清单和保留原因。
- 增加新增代码规范。

建议新增：

```text
docs/design/MAGIC_STRING_GOVERNANCE_RESULT.md
```

或在本文件末尾追加迁移结果。

## 8. 重点文件修改目的

| 文件 | 修改目的 |
| --- | --- |
| `app/schemas/enums/base.py` | 提供带 description 的 `StrEnum` 基类 |
| `app/schemas/enums/graph.py` | 统一 Graph 节点名和条件路由值 |
| `app/schemas/enums/task_completion.py` | 统一任务完成度业务状态和路由状态 |
| `app/schemas/enums/approval.py` | 统一审批状态、callback 状态、审批事件类型 |
| `app/schemas/enums/verification.py` | 统一通用 Verification stage/action/severity |
| `app/schemas/enums/tool.py` | 统一工具 scope/source/operation/risk/stopped reason |
| `app/schemas/enums/execution.py` | 统一 `initial` / `repair` 执行模式 |
| `app/schemas/enums/llm.py` | 统一 LLM scene 和 parse status |
| `app/schemas/enums/observability.py` | 统一稳定日志 event |
| `app/schemas/enums/errors.py` | 统一稳定错误码 |
| `app/runtime/graph.py` | 消除节点名和路由值重复书写 |
| `app/runtime/route_policy.py` | 去掉裸字符串比较和返回，安全降级记录日志 |
| `app/runtime/node_contracts.py` | 契约由 enum value 生成，保持测试可读 |
| `app/runtime/graph_state.py` | 补强核心字段类型和用途，不做 key 常量化 |
| `app/verification/task_completion/schemas.py` | 将 `TaskCompletionStatus` 从 Literal 改为 enum |
| `app/subagents/tool_calling_runner.py` | 将 `stopped_reason` 从 Literal 改为 enum |
| `app/schemas/approval.py` | 将审批状态从 Literal 改为 enum |
| `app/verification/schemas.py` | 将通用验证 stage/action/severity 改为 enum |
| `app/tools/base.py` | 将工具协议值改为 enum，并作为 ToolDefinition 字段类型 |
| `app/tools/contracts.py` | 复用工具领域 enum，避免重复 Literal |
| `app/llm/model_config.py` | scene model map 使用 `LLMScene.value` 作为 key |

## 9. 风险点

| 风险 | 说明 | 缓解方式 |
| --- | --- | --- |
| LangGraph API 对 enum 类型兼容性 | `StrEnum` 是 `str` 子类，但部分 API 可能期望原生 `str` | 节点注册和边界可统一使用 helper 转 `.value` |
| Checkpoint 历史数据 | 旧数据保存的是字符串 | enum value 保持不变，读取时用 `Enum(raw)` |
| SQLite 审批状态 | `approval_requests.status` 已持久化 | `ApprovalStatus` value 必须完全等于旧值 |
| 测试快照 | 多个测试直接断言字符串 | 测试继续断言 value，不断言 enum repr |
| Pydantic 序列化 | enum 可能序列化为对象或 enum repr | 使用 `StrEnum`，并增加 `model_dump(mode="json")` 测试 |
| 重复定义过渡期 | 旧常量与 enum 并存可能混乱 | 旧常量只作为兼容 alias，逐步替换调用点 |
| 过度治理 | 把文案、Prompt、JSON Schema 字段也抽枚举 | 明确“不治理范围”，review 时阻止 |
| 错误码带 detail | `missing_required_argument:apply_seq` 不是有限集合 | 只治理 prefix，detail 保持动态 |
| 工具业务字段 | `policyNo` 等字段是外部接口协议 | 不纳入 magic string enum，保持 adapter/schema 管理 |

## 10. 迁移顺序

推荐顺序：

1. `DescribedStrEnum` 基类与基础测试。
2. `GraphNode` 和 route enum，因为它们覆盖 MainGraph 最核心路径。
3. `TaskCompletionStatus` 与 `TaskCompletionRoute`，先解决路由中 `str(...).upper()` 问题。
4. `VerificationAction` 和 `ApprovalStatus`，因为它们影响审批和最终返回。
5. `ToolStoppedReason`、`ExecutionMode`、`ToolScope`、`ToolSource`。
6. `LLMScene`、`LLMParseStatus`。
7. 稳定日志 event 和错误码。
8. 全量扫描和剩余字符串说明。

不建议先治理 State key。State key 数量多、兼容面大，收益主要来自 TypedDict 和 contract，而不是常量化。

## 11. 测试清单

### 基础枚举测试

- `DescribedStrEnum.value` 正确。
- `DescribedStrEnum.description` 可读。
- description 不进入 `model_dump()`。
- description 不进入 `model_dump_json()`。
- `Enum(existing_value)` 可以恢复历史字符串。
- 枚举值与改造前机器值完全一致。

### Graph 和路由测试

- `tests/test_node_contracts.py`：节点契约与实际 graph 节点一致。
- `tests/test_route_policy.py`：每个 route policy 返回 value 不变。
- `tests/test_langgraph_flow.py`：主图流转不变。
- `graph_path` 中节点名称不变。
- 非法 `task_completion_verification_result` 安全降级到 `failed`，并记录日志。

### 状态和持久化测试

- `tests/test_graph_state_authority.py`
- `tests/test_checkpoint_projection.py`
- `tests/test_approval_full_flow.py`
- `tests/test_approval_chain_resume.py`
- `tests/test_approval_callback_approved.py`
- `tests/test_approval_result_callback.py`

### Tool 和 SubAgent 测试

- `tests/test_tool_calling_runner.py`
- `tests/test_tool_execution_pipeline.py`
- `tests/test_tool_executor_authorization.py`
- `tests/test_tool_executor_mcp.py`
- `tests/test_tool_registry_visibility.py`
- `tests/test_tool_registry_mcp_visibility.py`
- `tests/test_endo_aftercare_tool_calling_loop.py`

### Verification 和 Repair 测试

- `tests/test_final_compliance_check.py`
- `tests/test_task_completion_verify_repair_loop.py`
- `tests/test_tool_evidence_requirement.py`
- `tests/test_field_visibility_policy.py`

### LLM / Prompt / Eval 测试

- `tests/test_llm_model_config.py`
- `tests/test_llm_strict_schema.py`
- `tests/test_prompt_manifest.py`
- `tests/test_evaluation_cases_load.py`
- `tests/test_agent_eval_runner.py`

## 12. 后续新增代码规范

新增字符串时按以下问题判断：

1. 这个字符串是否是有限集合中的一个值？
2. 是否跨模块共享？
3. 是否写入 State、Checkpoint、DB、日志检索字段或 API？
4. 是否参与条件路由或业务判断？
5. 是否需要 IDE 自动补全和 description？

如果答案大多为“是”，应新增或复用枚举。

如果字符串是用户文案、Prompt、SQL、URL、外部接口字段、动态错误详情或局部一次性文本，应保持普通字符串。

## 13. 建议新增文件

```text
app/schemas/enums/__init__.py
app/schemas/enums/base.py
app/schemas/enums/graph.py
app/schemas/enums/task_completion.py
app/schemas/enums/approval.py
app/schemas/enums/verification.py
app/schemas/enums/tool.py
app/schemas/enums/execution.py
app/schemas/enums/llm.py
app/schemas/enums/observability.py
tests/test_described_str_enum.py
tests/test_enum_machine_values.py
```

## 14. 建议修改文件

```text
app/runtime/graph.py
app/runtime/route_policy.py
app/runtime/node_contracts.py
app/runtime/graph_state.py
app/runtime/state_contracts.py
app/runtime/state_projector.py
app/runtime/handlers/task_completion_handler.py
app/runtime/handlers/verification_handler.py
app/runtime/handlers/approval_handler.py
app/verification/task_completion/schemas.py
app/verification/task_completion/service.py
app/verification/task_completion/repair_plan_sanitizer.py
app/verification/schemas.py
app/verification/service.py
app/subagents/tool_calling_runner.py
app/subagents/base.py
app/schemas/approval.py
app/schemas/subagent.py
app/schemas/runtime.py
app/schemas/agent_card.py
app/tools/base.py
app/tools/contracts.py
app/tools/registry.py
app/tools/executor.py
app/tools/execution_pipeline.py
app/tools/guards/approval_guard.py
app/tools/guards/argument_guard.py
app/tools/guards/availability_guard.py
app/llm/output_schemas.py
app/llm/model_config.py
app/runtime/failure_codes.py
app/tools/error_codes.py
app/observability/logger.py
```

## 15. 预计不应该改造的字符串类型

- 用户请求、LLM 生成答案、reason、summary。
- Prompt 模板正文。
- API URL、MCP endpoint path、SQL。
- JSON Schema 标准字段。
- POS / workflow / insurance 外部接口字段。
- AgentCard、Skill、Tool 的业务 ID 和工具名。
- YAML 中现有业务值本身；代码可以用 enum 校验，但不能改 YAML value。
- 带动态 detail 的错误字符串整体。

## 16. 阶段 0 验收结论

阶段 0 已完成当前源码范围内的审计和设计。下一步应先实现阶段 1 基础枚举能力，再进入 Graph 节点和路由治理。

在用户确认前，不应直接进入阶段 1。

## 17. 阶段 1～6 实施结果

本次已按阶段完成首轮治理，原则是“稳定协议值强类型化，动态文本保持普通字符串”。

### 17.1 已完成

- 阶段 1：新增 `DescribedStrEnum`，验证 value、description、Pydantic dump/json 兼容性。
- 阶段 2：新增 `GraphNode` 和条件路由枚举；`graph.py`、`node_contracts.py`、`route_policy.py` 使用统一节点/路由来源。
- 阶段 3：新增任务完成状态、审批状态、Verification action/stage/severity、工具 scope/source/operation/risk/stopped_reason 等运行协议枚举。
- 阶段 4：`route_task_completion()` 改为通过 `TaskCompletionVerificationResult` 严格恢复；非法或大小写错误状态不再被 `upper()` 静默修复。
- 阶段 5：新增 `LLMScene`、LLM 结构化解析状态、稳定日志 `RuntimeEvent` 和工具错误码枚举；核心 LLM 调用、模型选择和日志事件已接入。
- 阶段 6：完成残留扫描；保留的字符串主要是 YAML/Prompt/用户文案/动态错误详情/外部协议字段。

### 17.2 保留字符串说明

- `AgentGraphState` 的字段名没有抽成常量，继续通过 `AgentGraphState` 类型和 `GRAPH_STATE_FIELD_AUTHORITY` 管理边界。
- `PromptEval` 的 `suite.scene` 仍来自 YAML，用字符串作为输入；内部判断已改用 `LLMScene` 机器值比较。
- `decision_trace["source"]`、`clarification_source`、message metadata 中的阶段名暂时保留字符串，因为它们是审计标签，不参与核心路由。
- `Graph path` 持久化的仍是原节点名字符串；代码来源改为 `GraphNode`，机器值不变。
- 用户展示话术、Prompt 正文、SQL、URL、工具名、Agent/Skill ID、外部接口字段不做枚举化。

### 17.3 已验证

已新增并通过：

```text
tests/test_described_str_enum.py
tests/test_enum_machine_values.py
```

关键回归覆盖：

```text
route policy
node contracts
tool executor / MCP
tool calling runner
approval full flow
final compliance verification
LLM model config
strict LLM schema
prompt manifest
agent eval runner/report
LangGraph flow
```

### 17.4 后续新增代码规范

新增稳定状态或路由时，应优先放入对应领域枚举，保持机器值与外部协议值一致。
新增动态文案、Prompt、用户答案、SQL、URL、工具参数时，不应为了“零字符串”创建枚举。
