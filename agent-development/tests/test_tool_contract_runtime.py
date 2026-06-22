import asyncio

import pytest

from app.schemas.agent_card import AgentCard
from app.tools.contracts import ToolContract, ToolContractCatalog
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


def _registry_with_contract(tool_name: str, tool, contract: ToolContract) -> ToolRegistry:
    registry = ToolRegistry(contract_catalog=ToolContractCatalog(version="1.0.0", tools={tool_name: contract}))
    registry.register_public(tool_name, tool)
    return registry


async def _slow_tool(**kwargs):
    await asyncio.sleep(0.1)
    return {"success": True}


async def _dict_tool(**kwargs):
    return {"success": True}


async def _raising_tool(**kwargs):
    raise RuntimeError("downstream exploded")


async def _write_tool(**kwargs):
    return {"success": True}


async def _read_tool(**kwargs):
    return {"success": True}


def _card(public_tools_allowed: bool = True) -> AgentCard:
    return AgentCard(
        agent_name="agent_a",
        display_name="Agent A",
        description="test",
        capabilities=["test"],
        supported_intents=["test"],
        required_entities=[],
        output_schema="SubAgentResult",
        private_tools=[],
        public_tools_allowed=public_tools_allowed,
        skills=["agent_a.default"],
        enabled=True,
        version="1",
    )


@pytest.mark.asyncio
async def test_tool_timeout_returns_stable_error_code():
    registry = _registry_with_contract(
        "slow_tool",
        _slow_tool,
        ToolContract(tool_name="slow_tool", timeout_ms=10, result_schema="AnyDictResult"),
    )
    executor = ToolExecutor(registry)

    result = await executor.execute(agent_name="agent_a", agent_card=_card(), tool_name="slow_tool", arguments={})

    assert result.success is False
    assert result.error == "tool_timeout"


@pytest.mark.asyncio
async def test_tool_result_schema_validation_failure_returns_stable_error_code():
    registry = _registry_with_contract(
        "bad_result_tool",
        _dict_tool,
        ToolContract(tool_name="bad_result_tool", timeout_ms=1000, result_schema="TextResult"),
    )
    executor = ToolExecutor(registry)

    result = await executor.execute(agent_name="agent_a", agent_card=_card(), tool_name="bad_result_tool", arguments={})

    assert result.success is False
    assert result.error == "tool_result_schema_invalid"
    assert "detail" in result.result


@pytest.mark.asyncio
async def test_tool_exception_returns_stable_error_code_with_detail():
    registry = _registry_with_contract(
        "raising_tool",
        _raising_tool,
        ToolContract(tool_name="raising_tool", timeout_ms=1000, result_schema="AnyDictResult"),
    )
    executor = ToolExecutor(registry)

    result = await executor.execute(agent_name="agent_a", agent_card=_card(), tool_name="raising_tool", arguments={})

    assert result.success is False
    assert result.error == "tool_execution_exception"
    assert result.result == {"detail": "downstream exploded"}


@pytest.mark.asyncio
async def test_write_tool_without_policy_still_requires_approval():
    registry = ToolRegistry()
    registry.register_public("write_tool", _write_tool, is_write=True)
    executor = ToolExecutor(registry)

    result = await executor.execute(agent_name="agent_a", agent_card=_card(), tool_name="write_tool", arguments={})

    assert result.success is False
    assert result.error == "human_approval_required"
    assert result.needs_human_approval is True


@pytest.mark.asyncio
async def test_read_tool_does_not_require_approval_by_default():
    registry = _registry_with_contract(
        "read_tool",
        _read_tool,
        ToolContract(tool_name="read_tool", timeout_ms=1000, result_schema="AnyDictResult"),
    )
    executor = ToolExecutor(registry)

    result = await executor.execute(agent_name="agent_a", agent_card=_card(), tool_name="read_tool", arguments={})

    assert result.success is True
    assert result.needs_human_approval is False


@pytest.mark.asyncio
async def test_approval_policy_id_forces_approval_and_enters_payload():
    registry = _registry_with_contract(
        "policy_read_tool",
        _read_tool,
        ToolContract(
            tool_name="policy_read_tool",
            timeout_ms=1000,
            result_schema="AnyDictResult",
            approval_policy_id="manual_review_policy",
        ),
    )
    executor = ToolExecutor(registry)

    result = await executor.execute(agent_name="agent_a", agent_card=_card(), tool_name="policy_read_tool", arguments={})

    assert result.success is False
    assert result.error == "human_approval_required"
    assert result.approval_payload["approval_policy_id"] == "manual_review_policy"

