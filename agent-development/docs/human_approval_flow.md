# Human Approval Flow

人工审批审批的是高风险工具执行请求，不审批自然语言回答本身。当前触发条件是工具定义 `is_write=true`，代表写入、修改、删除、提交等可能改变外部状态的操作。

## 审批对象

审批对象由以下字段组成：

- `agent_name`
- `tool_name`
- `arguments`
- `operation_type`
- `risk_level`
- `reason`
- `request_id`
- `trace_id`
- `session_key`

这些字段会写入 SQLite `approval_requests`，并随请求提交给外部审批系统。

## /api/chat 不阻塞

当 LLM 在子 Agent loop 中调用写工具时：

```text
ToolCallingRunner
-> ToolExecutor.execute
-> is_write=true
-> ToolResult(error="human_approval_required")
-> SubAgentResult.needs_human_approval=true
-> AgentGraphFactory.create_approval_request
-> ApprovalSystemClient.submit_approval_request
-> /api/chat 返回 pending
```

`/api/chat` 不等待人工审批完成。返回示例：

```json
{
  "request_id": "req_xxx",
  "session_key": "tenant:web:u1:s1",
  "original_query": "policy_no: P123456 update status to cancelled",
  "rewritten_query": "policy_no: P123456 update status to cancelled",
  "intent": "policy_query",
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

当前 `APPROVAL_SYSTEM_URL` 可以指向 mock URL。后续接真实审批系统时，主要替换 URL、认证签名和网络策略，不需要把审批逻辑塞进 LLMProvider。

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

## Callback

外部审批系统通过 `POST /api/approval/callback` 回调：

```json
{
  "approval_id": "approval_xxx",
  "external_approval_id": "ext_001",
  "status": "approved",
  "approver": "manager",
  "comment": "ok",
  "decided_at": "2026-05-24T12:00:00Z"
}
```

approved 后：

```text
ApprovalService.handle_callback
-> status=approved
-> ToolExecutor.execute_approved_tool
-> append role=tool observation
-> ToolCallingRunner.run resumes
-> final_compliance_check
-> save assistant message
-> compress_short_memory
-> approval_requests.status=completed
```

rejected 后：

```text
ApprovalService.handle_callback
-> status=rejected
-> 不执行 pending tool
-> final answer: 审批未通过，相关操作未执行。
-> final_compliance_check
-> save assistant message
-> compress_short_memory
-> approval_requests.status=rejected
```

Callback 是幂等的：`completed` 或 `rejected` 的审批再次回调时，不会重复执行工具。

## 查询结果

前端可以通过 `GET /api/approval/{approval_id}` 查询：

```json
{
  "approval_id": "approval_xxx",
  "status": "completed",
  "final_answer": "Policy status update completed after approval.",
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
- `arguments` 与审批时一致
- 工具仍然对当前 AgentCard 可见

普通 `ToolCallingRunner` 不能通过 `execute` 绕过审批执行写工具，因为 `execute` 看到 `is_write=true` 只会返回 `human_approval_required`。

最终返回用户的内容仍必须经过 `final_compliance_check`。
