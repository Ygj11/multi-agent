# Integrations Directory

This package contains integration adapters and examples for future external
systems. These modules are not automatically part of the main runtime path just
because they live here.

Current main-path integrations are wired explicitly from `app/main.py`, for
example:

- Knowledge retrieval uses `app/knowledge/factory.py` to choose
  `DisabledKnowledgeService` or `KnowledgeAPIClient`.
- MCP tools are discovered through `app/mcp/client_manager.py` and registered in
  `ToolRegistry` during FastAPI lifespan startup when MCP is enabled.
- Tool execution goes through `app/tools/executor.py`.

Files in this directory may be reference adapters, future backend clients, or
thin HTTP clients. Before treating one as production-wired code, check for a
direct import from `app/main.py`, a service factory, or a test that exercises it
through the real application graph.
