from pathlib import Path

import pytest

from app.agents.card_loader import AgentCardLoader
from app.auth.authorization_service import AuthorizationService
from app.auth.principal import Principal
from app.tools.agent_tools import register_agent_private_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


def _registry() -> ToolRegistry:
    registry = ToolRegistry()
    register_agent_private_tools(registry)
    return registry


def _card(name: str):
    return AgentCardLoader(Path("app/agents/cards")).get_agent_card(name)


@pytest.mark.asyncio
async def test_pipeline_checks_required_arguments_before_write_approval():
    executor = ToolExecutor(_registry())

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card("troubleshooting_agent"),
        tool_name="notice_policy_update",
        arguments={"apply_seq": "APPLY123", "policyNo": "P001"},
    )

    assert result.success is False
    assert result.error == "missing_required_argument:endorseType"
    assert result.needs_human_approval is False


@pytest.mark.asyncio
async def test_pipeline_checks_authorization_before_write_approval():
    registry = _registry()
    registry.get_definition("notice_policy_update").required_scopes = ["policy:write"]
    executor = ToolExecutor(registry=registry, authorization_service=AuthorizationService())
    principal = Principal(tenant_id="tenant", subject="user-1", scopes=["policy:read:basic"])

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card("troubleshooting_agent"),
        tool_name="notice_policy_update",
        arguments={"apply_seq": "APPLY123", "policyNo": "P001", "endorseType": "001028"},
        principal=principal,
    )

    assert result.success is False
    assert result.error == "permission_denied:missing_required_scope"
    assert result.needs_human_approval is False


@pytest.mark.asyncio
async def test_pipeline_routes_write_tool_to_human_approval_after_guards_pass():
    executor = ToolExecutor(_registry())

    result = await executor.execute(
        agent_name="troubleshooting_agent",
        agent_card=_card("troubleshooting_agent"),
        tool_name="notice_policy_update",
        arguments={"apply_seq": "APPLY123", "policyNo": "P001", "endorseType": "001028"},
        request_id="req-1",
        trace_id="trace-1",
        session_key="tenant:web:user:s",
    )

    assert result.success is False
    assert result.error == "human_approval_required"
    assert result.needs_human_approval is True
    assert result.approval_payload["tool_name"] == "notice_policy_update"
    assert result.pending_tool_call["arguments"] == {"apply_seq": "APPLY123", "policyNo": "P001", "endorseType": "001028"}
