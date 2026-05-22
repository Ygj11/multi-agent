# Main Flow Code Walkthrough

This walkthrough reflects the current architecture after the MCP Client migration.

## Runtime Chain

```text
/api/chat
-> RequestAdapter
-> AgentOrchestrator
-> LangGraph
   -> load_session
   -> save_user_message
   -> query_rewrite
   -> intent_recognition
   -> build_orchestrator_context
   -> discover_agents
   -> select_agent
   -> assemble_task
   -> dispatch_agent
   -> final_compliance_check
   -> save_assistant_message
   -> compress_short_memory
   -> finalize_response
-> ResponseAdapter
```

## Tool Execution

Sub agents use `ToolCallingRunner`. The runner sends only the current AgentCard-visible tool schemas to the LLM. Tool calls always go through `ToolExecutor`.

```text
ToolExecutor
-> source=local: local callable
-> source=mcp: MCPClientManager.call_tool(...)
-> tool_execution_logs
```

## MCP Boundary

The project is an MCP client / consumer. MCP capabilities are discovered at startup:

```text
MCPClientManager.initialize()
-> MCP server initialize/list_tools
-> MCPCapabilityRegistry
-> ToolRegistry.register_mcp_tools(...)
```

The old fake connector and wrapper path has been removed. Tests that need MCP behavior use test-only fakes under `tests/fakes/`.

