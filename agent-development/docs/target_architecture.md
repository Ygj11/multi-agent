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
- branching into human approval when a sub agent reports `needs_human_approval=true`
- creating and submitting approval requests for write-side tools
- final compliance check before responding
- retry or fallback when compliance fails

## Sub Agent Responsibilities

Each sub agent owns task execution:

- read its AgentCard from the task envelope
- use the common BaseSubAgent template
- select and load a Skill through `ContextBuilder`
- see only its card-authorized tools
- call tools through `ToolExecutor`
- stop and return `needs_human_approval=true` when a write-side tool requires approval
- return a structured `SubAgentResult`

## Human Approval

High-risk tools are tool executions, not model messages. The approval object is:

- `agent_name`
- `tool_name`
- `arguments`
- `operation_type`
- `risk_level`

The main graph does not block `/api/chat` while waiting for a human. When `ToolExecutor` detects `is_write=true`, it returns `human_approval_required` with a pending tool call. `ToolCallingRunner` stops, `BaseSubAgent` returns `SubAgentResult.needs_human_approval=true`, and `AgentGraphFactory` enters:

```text
check_human_approval_required
-> create_approval_request
-> submit_approval_request
-> pause_for_approval
-> final_compliance_check
-> save_assistant_message
```

`ApprovalSystemClient` submits the approval request to `APPROVAL_SYSTEM_URL` with `APPROVAL_CALLBACK_URL`. The URL can point to a mock approval system in the MVP.

The external system resumes the flow by calling `POST /api/approval/callback`:

- `approved`: `ApprovalService` calls `ToolExecutor.execute_approved_tool`, appends the tool observation, continues `ToolCallingRunner`, runs final compliance, saves the assistant message, compresses memory, and marks the approval `completed`.
- `rejected`: the pending tool is not executed. The system returns and saves a rejection answer after final compliance.

`GET /api/approval/{approval_id}` exposes the current approval status and final result for frontend polling.

## Memory And Context

The orchestrator context uses:

- short summary
- recent N turns
- extracted entities
- AgentCard candidate information
- lightweight knowledge hints

Sub agents can perform deeper retrieval through public tools such as `rag_search_tool` and `get_knowledge` when their AgentCard allows public tools.

## Entity Understanding And Routing

The current implementation uses a three-layer entity and routing design:

- Generic entity extraction lives in `app/query/entity_extractor.py` and reads configurable patterns from `app/query/entity_patterns.yaml`.
- Runtime entity state is dynamic: `app/schemas/entities.py::EntityBag` stores arbitrary entity types as `dict[str, list[EntityMention]]`. `ConversationWindow` does not grow business-specific top-level fields such as `last_policy_no` or `last_claim_no`.
- AgentCards declare coarse routing needs with `required_entities` and `optional_entities` in `app/agents/cards/*.yaml`.
- Skills declare fine-grained execution requirements with `required_entities` and `optional_entities` in `app/skills/*/*/SKILL.md`.

Routing is hybrid rather than pure rules or pure LLM. `AgentCardLoader.match_candidates` performs deterministic Top-K recall using intent, sub_intent, entities, capabilities, descriptions, and examples. `AgentSelectionNode` directly selects the rule winner when it is clearly ahead. When scores are close, intent confidence is low, or the query is a complex follow-up, `LLMAgentRouter` re-ranks only the Top-K AgentCard summaries. It does not receive all tool schemas, all Skill bodies, or private agent prompts.

If QueryRewrite, IntentRecognition, AgentSelection, or Skill required entity checking needs clarification, the graph returns a clarification answer through `final_compliance_check` instead of dispatching a sub agent or calling tools prematurely.

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
- approval_requests
- approval_events

Future checkpointer and persistence backends remain replaceable behind the current abstractions.
