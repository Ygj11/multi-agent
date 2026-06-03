# Human Approval Flow

人工审批审批的是“高风险工具执行请求”，不是自然语言回答本身。当前触发条件是工具定义 `is_write=true`，表示该工具可能写入、修改、删除、提交或改变外部业务状态。

## 审批对象

审批单保存到 SQLite `approval_requests`，核心对象包括：

- `approval_id`
- `session_key`
- `request_id`
- `trace_id`
- `thread_id`
- `agent_name`
- `tool_name`
- `operation_type`
- `risk_level`
- `arguments`
- `reason`
- `pending_state`
- `resume_state`
- `pending_messages`
- `pending_tools`
- `pending_tool_call`
- `parent_approval_id`
- `root_approval_id`
- `approval_depth`
- `next_approval_id`

`approval_events` 保存审批状态变化事件。

## /api/chat 不阻塞等待人工

当 LLM 在子 Agent tool loop 中调用写工具时：

```text
ToolCallingRunner
-> ToolExecutor.execute
-> ToolExecutionPipeline.approval_guard
-> ToolResult(error="human_approval_required")
-> ToolCallingRunner stops
-> SubAgentResult.needs_human_approval=true
-> Graph.check_human_approval_required
-> Graph.create_approval_request
-> Graph.submit_approval_request
-> Graph.pause_for_approval
-> Graph.pre_answer_verify
-> /api/chat returns pending
```

`/api/chat` 不同步等待人工审批完成。pending 响应示例：

```json
{
  "request_id": "req_xxx",
  "session_key": "tenant:web:u1:s1",
  "original_query": "保全任务完成后保单未更新，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001",
  "rewritten_query": "保全任务完成后保单未更新，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001",
  "intent": "troubleshooting",
  "answer": "该操作需要人工审批，审批请求已提交，approval_id=approval_xxx。当前操作尚未执行。",
  "approval_required": true,
  "approval_id": "approval_xxx",
  "approval_status": "pending"
}
```

## 外部审批系统

配置项：

- `APPROVAL_SYSTEM_URL`
- `APPROVAL_CALLBACK_URL`
- `APPROVAL_SYSTEM_TIMEOUT`
- `ENABLE_EXTERNAL_APPROVAL`

`ApprovalSystemClient` 向外部审批系统提交 payload。当前 URL 可以是 mock；接真实审批系统时主要替换 URL、认证、签名和网络策略。

提交 payload 至少包含：

- `approval_id`
- `request_id`
- `trace_id`
- `session_key`
- `agent_name`
- `tool_name`
- `operation_type`
- `risk_level`
- `arguments`
- `reason`
- `callback_url`
- `created_at`

提交失败时，审批状态为 `submit_failed`，原工具不执行。

## Callback

外部审批系统通过 `POST /api/approval/callback` 回调：

```json
{
  "approval_id": "approval_xxx",
  "external_approval_id": "ext_001",
  "status": "approved",
  "approver": "manager",
  "comment": "ok",
  "decided_at": "2026-06-03T12:00:00Z"
}
```

### Approved

当前 approved 恢复路径不是由 `ApprovalService` 独自跑完整 tool loop，而是回到 Graph：

```text
ApprovalService.handle_callback
-> update approval status approved/executing
-> AgentOrchestrator.resume_after_approval
-> route_entry(resume)
-> resume_approved_tool
-> ToolExecutor.execute_approved_tool
-> append role=tool observation
-> ToolCallingRunner.run continues
-> check_human_approval_required
```

如果恢复后的 LLM 又调用第二个 `is_write=true` 工具：

```text
ToolExecutor returns human_approval_required
-> check_human_approval_required
-> create_approval_request creates approval_2
-> approval_1.status = completed
-> approval_1.next_approval_id = approval_2
-> approval_2.parent_approval_id = approval_1
-> /api/chat-like pending result saved for approval_2
```

这样第二个写工具不会被执行，也不会被当成第一个审批的普通错误。

### Rejected

```text
ApprovalService.handle_callback
-> status=rejected
-> do not execute pending tool
-> rejection answer
-> pre_answer_verify
-> save_assistant_message
-> compress_short_memory
-> approval_requests.status=rejected
```

## 查询结果

前端可通过 `GET /api/approval/{approval_id}` 轮询：

```json
{
  "approval_id": "approval_xxx",
  "status": "completed",
  "final_answer": "操作已在审批通过后完成。",
  "error": null,
  "created_at": "...",
  "updated_at": "...",
  "decided_at": "..."
}
```

## 安全校验

`ToolExecutor.execute_approved_tool` 执行前必须校验：

- `approval_id` 存在
- `status == approved`
- `agent_name` 一致
- `tool_name` 一致
- canonicalized `arguments` 一致
- 工具仍对当前 AgentCard 可见
- required arguments 完整
- tool access/resource access 仍通过
- `VerificationService(stage="pre_tool")` 仍通过

审批 callback 幂等：已 `completed` / `rejected` 的审批不会重复执行工具。写工具还通过 `ToolExecutionLogStore.find_success_by_approval` 做 approved tool 执行幂等保护。

所有最终返回用户内容仍必须经过 `pre_answer_verify -> VerificationService`。
