from app.mcp.capability_registry import MCPCapabilityRegistry
from app.mcp.schemas import MCPToolCapability


def _tool(server: str, name: str) -> MCPToolCapability:
    return MCPToolCapability(
        server_name=server,
        original_tool_name=name,
        registered_tool_name=f"mcp.{server}.{name}",
        description=f"{name} desc",
        input_schema={"type": "object", "properties": {}},
    )


def test_upsert_list_get_and_list_by_server():
    registry = MCPCapabilityRegistry()
    registry.upsert_tools("workflow", [_tool("workflow", "query_refund_task")])

    assert len(registry.list_tools()) == 1
    assert registry.get_tool("mcp.workflow.query_refund_task").original_tool_name == "query_refund_task"
    assert registry.list_tools_by_server("workflow")[0].registered_tool_name == "mcp.workflow.query_refund_task"
    assert registry.get_server_statuses()[0].available is True


def test_refresh_replaces_old_tools():
    registry = MCPCapabilityRegistry()
    registry.upsert_tools("workflow", [_tool("workflow", "old_tool")])
    registry.upsert_tools("workflow", [_tool("workflow", "new_tool")])

    assert registry.get_tool("mcp.workflow.old_tool") is None
    assert registry.get_tool("mcp.workflow.new_tool") is not None
    assert registry.get_server_statuses()[0].tool_count == 1


def test_mark_server_unavailable_keeps_status():
    registry = MCPCapabilityRegistry()
    registry.upsert_tools("workflow", [_tool("workflow", "query_refund_task")])
    registry.mark_server_unavailable("workflow", "boom")

    status = registry.get_server_statuses()[0]
    assert status.available is False
    assert status.last_error == "boom"
    assert status.tool_count == 1

