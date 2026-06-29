# 审批、Verification、Evidence 与恢复

适用场景：新增写工具、调整审批条件、修改审批 callback/恢复、增加数据权限或合规校验、改变 evidence 或最终回答处理。

## 审批真实链路

```text
ToolExecutor / ToolApprovalGuard
  -> ToolResult(human_approval_required)
  -> ToolCallingRunner stops
  -> MainGraph ApprovalGraphHandler
  -> ApprovalService + ApprovalStore
  -> POST /api/approval/callback
  -> AgentOrchestrator.resume_after_approval()
  -> ToolExecutor.execute_approved_tool()
  -> ToolCallingRunner resumes
```

当前不是 LangGraph 原生 `interrupt()`；恢复依赖 ApprovalStore 的 resume state。任何审批改动都必须同时考虑“创建 pending”“approved 后执行”“rejected”“重复 callback”“审批链深度限制”。

## 1. 让工具需要审批

先在 [05-local-tool-and-contract.md](05-local-tool-and-contract.md) 完成工具注册，然后确认：

- `ToolDefinition.is_write=True`，或 operation 为 `write` / `notify`；
- 如需要契约级审批，`app/tools/tool_contracts.yaml` 设置 `approval_policy_id`；
- 风险级别、required scopes、resource 信息与外部 API 的真实含义一致；
- mock 模式和 real 模式的写属性不能误导测试或用户。

审批 guard 位于 `app/tools/guards/approval_guard.py`；主图审批节点与恢复逻辑位于 `app/runtime/handlers/approval_handler.py`；服务层在 `app/approval/service.py`，持久化在 `app/approval/store.py`。

不要在 tool handler 内自行“先调用外部写接口再创建审批”。审批必须发生在真正执行前。

## 2. 修改审批协议或回调

| 变更 | 需要检查的文件 |
| --- | --- |
| approval request 字段、状态、回调 request/response | `app/schemas/approval.py`、`app/approval/store.py`、`app/approval/service.py`、`app/main.py` callback route |
| 外部审批系统调用 | `app/approval/client.py`、`.env` 的 approval settings |
| resume state 结构 | `app/schemas/approval.py`、ApprovalStore、`ApprovalGraphHandler`、`AgentOrchestrator` |
| 已批准工具执行防重 | `ToolExecutor.execute_approved_tool()` 与 tool execution logs |
| 审批分支与 pending 答案 | `app/runtime/graph.py`、`RoutePolicy`、approval handler |

审批恢复时必须再次校验：approval 存在、工具名/agent/arguments 与已审批 payload 一致、工具仍可见、required 参数、授权、pre-tool verification。不能因为“审批通过”就跳过工具安全边界。

## 3. 新增或修改 Verification

| 文件 | 职责 |
| --- | --- |
| `app/verification/base.py` / `schemas.py` | verifier 协议和输入输出。 |
| `app/verification/verifiers/*.py` | 具体数据权限、合规等规则。 |
| `app/bootstrap/verification.py` | 注册默认 verifier。 |
| `app/verification/service.py` | 按 stage 聚合 verifier。 |
| `app/runtime/handlers/verification_handler.py` | MainGraph 的 pre-answer 行为、patch/retry/fallback。 |
| `app/tools/guards/verification_guard.py` | 工具前 hook；当前是否实际生效取决于注册的 stage。 |
| `app/verification/policies/field_visibility_policy.yaml` | 字段级可见性策略。 |

区分：Authorization 决定“是否可调用 Agent/Tool”；Verification 决定“参数或最终输出是否可外发”。新增校验不要把这两个职责混在一个 verifier 中。

## 4. Evidence 与日志

`ToolExecutor._log()` 会写 structured log、`ToolExecutionLogStore`，并尝试用 `EvidenceBuilder` 写 Evidence。新增工具结果或变更输出时应确认：

- tool result 可以安全持久化；敏感字段需要由 field visibility/输出策略评估；
- evidence summary 不应包含 credentials 或无界原始 payload；
- 失败写 evidence 时不应影响工具主执行结果，当前就是 best effort。

## 测试

```bash
uv run pytest tests/test_approval_full_flow.py tests/test_approval_idempotency.py -q
uv run pytest tests/test_approval_callback_approved.py tests/test_approval_callback_rejected.py tests/test_approval_chain_resume.py -q
uv run pytest tests/test_field_visibility_policy.py tests/test_final_compliance_check.py -q
uv run pytest tests/test_evidence_store.py tests/test_troubleshooting_evidence.py -q
```
