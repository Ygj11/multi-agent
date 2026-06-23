# MainGraph 节点、状态与分支修改

适用场景：新增/删除/重排 LangGraph 节点，修改条件分支，增加 Graph state 字段，调整澄清、审批、验证或消息落库流转。

## 当前节点总览

注册和边定义都在 `app/runtime/graph.py:AgentGraphFactory.build()`：

| 阶段 | 节点 | 主要实现位置 |
| --- | --- | --- |
| 入口 | `route_entry` | `RoutePolicy.route_entry()` |
| 恢复 | `resume_approved_tool` | `ApprovalGraphHandler` |
| 会话 | `load_session`, `save_user_message` | `SessionManager`, `MessageCommitHandler` |
| 理解 | `query_rewrite`, `intent_recognition` | Query 节点实现 |
| 路由 | `build_orchestrator_context`, `select_agent`, `dispatch_agent` | ContextBuilder、AgentSelectionNode、DispatchAgentNode |
| 澄清 | `build_clarification_answer` | `ClarificationHandler` |
| 审批 | `check_human_approval_required`, `create_approval_request`, `submit_approval_request`, `pause_for_approval` | `ApprovalGraphHandler` |
| 出口验证 | `pre_answer_verify`, `regenerate_compliant_answer`, `fallback_answer` | `VerificationHandler` |
| 提交 | `save_assistant_message`, `compress_short_memory`, `finalize_response` | message/memory handler 与 graph method |

条件边统一由 `app/runtime/route_policy.py` 给出：入口恢复、澄清、审批、创建审批后的流向、Verification allow/retry/fallback。不要把复杂条件散在 `add_conditional_edges()` lambda 中。

## 1. 新增节点的完整步骤

1. 在 `app/runtime/graph.py` 为 `AgentGraphFactory` 增加显式依赖或复用已有 service；不要从 `AppContainer` 拉取服务。
2. 在 `build()` 中 `graph.add_node("node_name", self.node_method)`；节点名称是运行时 trace/测试契约，改名必须全链路同步。
3. 实现 async node method，输入只读 `AgentGraphState`，返回增量 `dict`。调用 `_log_node_enter/_log_node_exit` 并 append `graph_path`。
4. 使用 `add_edge` 或 `add_conditional_edges` 接入节点；新条件应先放进 `RoutePolicy` 并为所有返回值声明 destination map。
5. 需要持久化/恢复时，检查 `StateProjector`、checkpoint schema、message metadata sanitizer 和 approval resume payload 是否允许该字段。
6. 补节点 contract、路由和端到端测试。

## 2. 修改 State 字段前先分类

| 字段类型 | 应放哪里 | 注意事项 |
| --- | --- | --- |
| 请求主状态 | `app/runtime/graph_state.py:AgentGraphState` | 只放下游节点确实需要的结构化字段。 |
| 运行期上下文 | `OrchestratorContext` / `SubAgentContext` schema | 从 Graph state 派生，不把所有调试数据放进去。 |
| 最终 snapshot | `app/runtime/state_projector.py`、checkpoint schema/store | 只持久化允许字段；不要把 ToolCallingRunner messages 等大对象塞入。 |
| assistant message metadata | `MessageCommitHandler` + `app/session/message_metadata_sanitizer.py` | 保留业务摘要，排除内部 trace/大字段。 |
| 审批恢复数据 | `AgentResumeState` / ApprovalStore | 只保留恢复所需最小信息，不能依赖 transient graph cache。 |

实体是例外中的强约束：任何节点改变实体都必须使用 `build_entity_state_updates(EntityBag)`；详见 [01-query-rewrite-and-entities.md](01-query-rewrite-and-entities.md)。

## 3. 常见改动应该落在哪

| 想改什么 | 正确入口 | 不应直接改 |
| --- | --- | --- |
| 查询改写后直接澄清 | `QueryRewriteNode` 输出 `need_clarification`，Graph 复用 `clarification_route` | 不要在 Graph 重复判断实体规则。 |
| Intent 低置信澄清 | `IntentRecognitionNode` | 不要在 `select_agent` 再做 Intent fallback。 |
| Agent 无权访问 | `select_agent` 的 access check / `AuthorizationService` | 不要让 dispatch 后才拒绝。 |
| 新的审批分支 | `ApprovalGraphHandler`、`RoutePolicy`、ApprovalService | 不要把 pending 结果当最终执行成功。 |
| 新的最终校验 | VerificationService/verifier/VerificationHandler | 不要在每个 subagent 末尾手写过滤。 |
| 改消息或摘要时机 | MessageCommitHandler、MemoryCommitHandler | 不要在 ToolCallingRunner 直接写消息库。 |

## 4. 修改节点顺序的风险检查

当前关键顺序不能随意颠倒：

```text
load_session -> save_user_message -> query_rewrite -> intent_recognition
query_rewrite -> build_orchestrator_context -> select_agent -> dispatch_agent
dispatch_agent/resume -> approval -> pre_answer_verify -> save_assistant_message
```

例如，把 `save_user_message` 放到 Query Rewrite 后会使当前轮历史与现有多轮行为不同；把 Verification 放到落库后会让未通过答案进入会话记忆。

## 测试

```bash
uv run pytest tests/test_route_policy.py tests/test_node_contracts.py -q
uv run pytest tests/test_langgraph_flow.py tests/test_clarification_flow.py -q
uv run pytest tests/test_graph_state_authority.py tests/test_graph_state_no_top_level_cache.py tests/test_runtime_state_slimming.py -q
uv run pytest tests/test_message_metadata_boundary.py tests/test_checkpoint_projection.py -q
```
