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

`ToolCallingRunner` never calls tool functions or MCP clients directly; it only appends observations and continues the LLM loop.
