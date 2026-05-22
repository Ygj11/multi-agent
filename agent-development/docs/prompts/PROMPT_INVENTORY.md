# Prompt Inventory

The MVP currently keeps prompts lightweight and rule-first. MCP Client integration does not introduce MCP-specific prompts.

| Area | Prompt Usage | Notes |
| --- | --- | --- |
| Query rewrite | Rule-first, optional LLM scene `query_rewrite` | Uses unified `LLMProvider.chat` when enabled. |
| Intent recognition | Rule-first, optional LLM scene `intent_recognition` | Does not select tools. |
| Agent selection | Rule-first AgentCard scoring, optional LLM scene `agent_selection` | Does not execute tools. |
| Sub agent reasoning | `ToolCallingRunner` with current AgentCard-visible tools | Local and MCP tools share function schema format. |
| Final compliance | Rule-first sanitizer, optional LLM scene `final_compliance` | No tools. |

MCP tools are discovered by `MCPClientManager`, authorized by AgentCard, and executed only by `ToolExecutor`.

