# Tool System

The current tool layer has one registry and one executor.
The old local fake MCP connector and wrapper tools have been removed. MCP tools now enter the system only through `MCPClientManager` discovery and `ToolRegistry.register_mcp_tools(...)`.

## ToolRegistry

`ToolRegistry` stores three tool sources:

- local public tools, visible only when `AgentCard.public_tools_allowed=true`
- local private tools, visible only to the owning AgentCard
- MCP tools, visible only through `AgentCard.mcp_tools` or `AgentCard.mcp_tool_scopes`

`list_tools_for_agent(agent_card)` returns OpenAI-compatible function schemas for exactly the current agent's visible tools. It never returns all system tools.

## ToolExecutor

`ToolExecutor` is the only execution path for tools.

```text
ToolExecutor.execute(...)
-> AgentCard visibility check
-> if is_write=true: return human_approval_required, do not execute
-> source=local: call local callable
-> source=mcp: MCPClientManager.call_tool(...)
-> normalize success/error
-> write tool_execution_logs
```

Unauthorized calls return:

```text
success=false
error=tool_not_available_for_agent
```

MCP errors are normalized as:

```text
mcp_server_unavailable
mcp_tool_timeout
mcp_tool_error
```

## Human Approval For Write Tools

Write-side tools are registered with `is_write=true`. They include operations that create, update, delete, modify, submit, or otherwise change business state. The LLM can see only AgentCard-authorized tool schemas, but even if it calls a visible write tool, `ToolExecutor.execute` does not run it immediately.

Instead it returns:

```text
success=false
allowed=false
error=human_approval_required
needs_human_approval=true
approval_payload={agent_name, tool_name, arguments, operation_type, risk_level, ...}
pending_tool_call={name, arguments, ...}
```

`ToolCallingRunner` treats this as a pause point, not a normal recoverable tool error. It stops the loop and returns the pending messages/tools to the graph. `AgentGraphFactory` then creates an `approval_requests` row, submits the approval to `APPROVAL_SYSTEM_URL`, and returns pending from `/api/chat`.

The external approval system calls `POST /api/approval/callback` later:

- `approved`: `ApprovalService` calls `ToolExecutor.execute_approved_tool`, appends the tool result as a `role=tool` observation, and continues the LLM loop.
- `rejected`: the pending tool is not executed.

`execute_approved_tool` validates `approval_id`, status, agent, tool name, and canonicalized arguments before execution. This prevents a caller from approving one operation and executing another.

All final answers after approved or rejected callbacks still pass through `final_compliance_check`.

`ToolCallingRunner` never calls tool functions or MCP clients directly; it only appends observations and continues the LLM loop.
