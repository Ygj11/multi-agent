# Tool System

当前工具系统只有一条主执行路径：

```text
LLM tool_call
-> ToolCallingRunner
-> ToolExecutor
-> ToolExecutionPipeline guards
-> local callable 或 MCPClientManager.call_tool
```

旧 ToolBroker / PolicyGate 主路径已经删除。

## ToolRegistry

`app/tools/registry.py::ToolRegistry` 保存三类工具：

- public local tools：只有 `AgentCard.public_tools_allowed=true` 时可见。
- private local tools：必须属于当前 AgentCard 的 `private_tools`。
- MCP tools：通过 `AgentCard.mcp_tools` 或 `mcp_tool_scopes` 授权可见。

最终传给 LLM 的工具 schema 是 OpenAI function-calling 风格：

```json
{
  "type": "function",
  "function": {
    "name": "query_policy_status",
    "description": "Query policy status by policy number.",
    "parameters": {
      "type": "object",
      "properties": {
        "policy_no": {
          "type": "string",
          "description": "Policy number."
        }
      },
      "required": ["policy_no"]
    }
  }
}
```

LLM 不直接看到这些内部字段：

- `scope`
- `source`
- `is_write`
- `enabled`
- `agent_name`
- `server_name`
- `original_name`
- `callable`
- `metadata`

## ToolExecutor

`ToolExecutor.execute(...)` 只负责普通工具调用。内部交给 `ToolExecutionPipeline`，守卫顺序是：

```text
tool exists
-> AgentCard visibility
-> required argument check
-> AuthorizationService / ResourceAccessService
-> VerificationService(pre_tool)
-> approval guard for is_write=true
-> execute local or MCP tool
-> write tool_execution_logs
-> optionally save Evidence
```

常见错误：

```text
tool_not_found
tool_not_available_for_agent
missing_required_argument:<arg>
permission_denied:<reason>
verification_failed:<reason>
human_approval_required
mcp_server_unavailable
mcp_tool_timeout
mcp_tool_error
```

## ToolCallingRunner

`app/subagents/tool_calling_runner.py::ToolCallingRunner.run` 负责完整 LLM + tool observation loop。

当前具备以下安全控制：

- `max_iterations`
- `max_consecutive_tool_failures`
- `max_same_tool_failures`
- `max_duplicate_tool_calls`

每轮流程：

```text
LLMProvider.chat(messages, tools, scene="subagent_reasoning")
-> if tool_calls:
     normalize_tool_call
     ToolExecutor.execute
     append role=tool observation
     continue
-> else:
     return final answer
```

写工具触发审批时，runner 不把它当普通失败喂回 LLM，而是立即停止并返回：

```text
stopped_reason="human_approval_required"
needs_human_approval=true
approval_payload
pending_tool_call
messages
tools
```

## Human Approval For Write Tools

写工具注册时设置 `is_write=true`。例如保全任务完成后异常处理中的：

- `notice_policy_update`
- `notice_customer_update`
- `notice_period_update`
- `policy_suspendOrRecovery`
- `notice_finance`

普通 `execute(...)` 遇到写工具时不执行真实 callable，只返回 `human_approval_required`。

approved callback 后走：

```text
ApprovalService.handle_callback
-> AgentOrchestrator.resume_after_approval
-> Graph.resume_approved_tool
-> ToolExecutor.execute_approved_tool
```

`execute_approved_tool` 会校验 approval 与 pending tool call 一致，并通过 `ToolExecutionLogStore` 做 approval idempotency，防止重复 callback 重复执行写工具。

## MCP Tools

MCP 是外部工具来源，不是 LLM 直接发现工具。

```text
FastAPI lifespan startup
-> MCPClientManager.initialize()
-> MCP server list_tools
-> MCPCapabilityRegistry
-> ToolRegistry.register_mcp_tools()
```

LLM 仍只看到标准 function schema。执行时，`ToolDefinition.source == "mcp"` 的工具由 `ToolExecutor` 分发到 `MCPClientManager.call_tool(...)`。

## Knowledge Tools

知识检索工具是 public tools：

- `rag_search_tool`

历史 alias `get_knowledge` 已删除；新逻辑应统一使用 `rag_search_tool`。

当 `ENABLE_KNOWLEDGE_API=false` 时，`DisabledKnowledgeService` 返回空 chunks，不使用内置 mock knowledge。启用外部知识库后，`KnowledgeAPIClient` 调用外部 API，并通过 `KnowledgeChunkPostProcessor` 归一化为内部 `KnowledgeChunk`。

## Audit / Evidence

- `ToolExecutionLogStore`：工具执行事实流水，写 `tool_execution_logs`。
- `ApprovalStore`：审批业务状态与事件，写 `approval_requests`、`approval_events`。
- `EvidenceStore`：可供回答和验证引用的证据索引。

这三者职责不同，不互相替代。

## Final Outbound Boundary

所有工具链路产出的最终回答，都会回到主图的：

```text
pre_answer_verify
-> VerificationService(stage="pre_answer")
```

它会统一运行 `DataPermissionVerifier` 和 `ComplianceVerifier`，必要时 patch/retry/fallback，然后再保存 assistant message 并返回用户。
