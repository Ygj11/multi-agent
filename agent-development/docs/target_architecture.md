# Target Architecture

The target architecture is the architecture shown in `Architectural Design.png`: a main Agent coordinates task-level orchestration and multiple sub agents execute specialized tasks.

## Main Agent Responsibilities

The main Agent is responsible for:

- query rewrite and intent/entity recognition
- dynamic AgentCard discovery
- AgentCard-based sub-agent selection
- task context assembly
- sub-agent dispatch
- receiving `SubAgentResult`
- final compliance check before responding
- retry or fallback when compliance fails

## Sub Agent Responsibilities

Each sub agent owns task execution:

- read its AgentCard from the task envelope
- use the common BaseSubAgent template
- select and load a Skill through `ContextBuilder`
- see only its card-authorized tools
- call tools through `ToolExecutor`
- return a structured `SubAgentResult`

## Memory And Context

The orchestrator context uses:

- short summary
- recent N turns
- extracted entities
- AgentCard candidate information
- lightweight knowledge hints

Sub agents can perform deeper retrieval through public tools such as `rag_search_tool` and `get_knowledge` when their AgentCard allows public tools.

## MCP Client Tools

The platform is an MCP client / consumer. MCP server capabilities are discovered during FastAPI lifespan startup through `MCPClientManager.initialize()`, cached in `MCPCapabilityRegistry`, and registered into `ToolRegistry` as external tools with `source="mcp"`.
The old local fake connector and MCP wrapper implementation has been removed from application code; tests use `tests/fakes/FakeMCPClient` when they need a mock MCP server.

MCP tools are not discovered dynamically by the LLM. The LLM only receives the tool schemas returned by `ToolRegistry.list_tools_for_agent(agent_card)`, which combines local private tools, allowed public tools, and AgentCard-authorized MCP tools.

AgentCards authorize MCP tools with:

- `mcp_tools`: exact registered tool names such as `mcp.workflow.query_refund_task`
- `mcp_tool_scopes`: namespace prefixes such as `mcp.workflow`

`ToolExecutor` remains the only execution path. It dispatches `source="local"` tools to local callables and `source="mcp"` tools to `MCPClientManager.call_tool(...)`, then writes `tool_execution_logs` for both success and failure.

## Storage

The MVP uses SQLite for:

- messages
- short_term_memory
- graph_checkpoints
- tool_execution_logs

Future checkpointer and persistence backends remain replaceable behind the current abstractions.
