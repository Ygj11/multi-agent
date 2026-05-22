# MCP Client Integration

This project is an MCP client / consumer. It does not expose an MCP server.
The previous local fake connector and wrapper implementation has been removed from `app/`; tests use `tests/fakes/FakeMCPClient` when a mock MCP server is needed.

## Startup Flow

```text
FastAPI lifespan startup
-> MCPClientManager.initialize()
-> each enabled MCP server initialize + list_tools
-> MCPCapabilityRegistry caches capabilities and server statuses
-> ToolRegistry.register_mcp_tools(...)
-> runtime agents can see only AgentCard-authorized MCP tools
```

MCP server initialization is best-effort. A failed server is marked unavailable and the app still starts.

## Runtime Flow

```text
User query
-> main Agent selects sub agent
-> BaseSubAgent loads AgentCard
-> ToolRegistry.list_tools_for_agent(agent_card)
-> local private tools + allowed public tools + allowed MCP tools
-> LLM.chat(messages, tools)
-> ToolCallingRunner receives tool_call
-> ToolExecutor checks AgentCard visibility
-> source=local: call local function
-> source=mcp: MCPClientManager.call_tool(...)
-> tool_execution_logs
-> final_compliance_check
```

`LLMProvider` and `ToolCallingRunner` do not know MCP protocol details. MCP routing belongs to `ToolExecutor`.

## Configuration

```powershell
$env:ENABLE_MCP_CLIENT="true"
$env:MCP_SERVERS_JSON='[
  {
    "server_name": "workflow",
    "enabled": true,
    "transport": "http",
    "url": "http://127.0.0.1:9001/mcp",
    "timeout": 30,
    "tool_name_prefix": "mcp.workflow"
  }
]'
```

HTTP/SSE-style JSON-RPC transport is supported in this MVP. Stdio transport is reserved for a later phase.

## AgentCard Authorization

AgentCards control MCP visibility with:

```yaml
mcp_tools:
  - mcp.workflow.query_refund_task
mcp_tool_scopes:
  - mcp.workflow
```

Exact `mcp_tools` allow only named MCP tools. `mcp_tool_scopes` allow tools under a namespace. Unlisted MCP tools are hidden from the LLM and rejected again by `ToolExecutor`.

## Refresh

Startup discovery is implemented. Background refresh is a TODO: refresh failure should keep the last known good tool cache and mark the server status unavailable.

Production MCP capabilities are discovered from configured MCP servers through `MCPClientManager`; test doubles live only under `tests/fakes/`.
