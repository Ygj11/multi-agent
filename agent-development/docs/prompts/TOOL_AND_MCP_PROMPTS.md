# Tool And MCP Prompts

The current MCP integration does not use prompts. MCP tools are discovered from upstream MCP servers by `MCPClientManager` and registered into `ToolRegistry`.

The LLM sees only normalized tool schemas returned by `ToolRegistry.list_tools_for_agent(agent_card)`. It does not discover MCP tools on demand and does not call MCP directly.

Tool execution is always:

```text
ToolCallingRunner
-> ToolExecutor
-> source=local or source=mcp
```

Test-only MCP fakes live under `tests/fakes/`.

