from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest

from app.agents.card_loader import AgentCardLoader
from app.agents.selection import AgentSelectionNode
from app.auth.principal import AuthContext, Principal
from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.integrations.clients import IntegrationClients
from app.integrations.pos_api_client import PosAPIClient
from app.llm.schemas import LLMResponse
from app.query.intent_recognition_node import IntentRecognitionNode
from app.schemas.entities import ConversationWindow, EntityBag
from app.skills.catalog import SkillCatalog
from app.subagents.tool_calling_runner import ToolCallingRunner
from app.tools.agent_tools import register_agent_private_tools
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry


CARDS_ROOT = Path("app/agents/cards")
SKILLS_ROOT = Path("app/skills")


class FakePosAPIClient:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls.append({"path": path, "payload": payload})
        return {
            "success": True,
            "path": path,
            "request_payload": payload,
            "response": {"mock": True},
        }


class SequencedLLM:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    async def chat(self, messages, tools=None, **kwargs):
        self.calls.append({"messages": list(messages), "tools": tools, "kwargs": kwargs})
        return self.responses.pop(0)


def _pos_registry(fake_client: FakePosAPIClient | None = None) -> ToolRegistry:
    registry = ToolRegistry()
    register_agent_private_tools(
        registry,
        pos_tool_mode="real",
        integration_clients=IntegrationClients(pos=fake_client or FakePosAPIClient()),
    )
    return registry


def _pos_card():
    return AgentCardLoader(CARDS_ROOT).get_agent_card("pos_query_agent")


def _window(entities: dict | None = None) -> dict:
    bag = EntityBag.from_compact_dict(entities or {}, source="current_query", confidence=0.9)
    return ConversationWindow(session_key="test-session", entity_bag=bag).model_dump()


def _assert_function_schema(schema: dict[str, Any], *, required: set[str]) -> None:
    assert schema["type"] == "function"
    function = schema["function"]
    assert function["name"]
    assert function["description"]
    parameters = function["parameters"]
    assert parameters["type"] == "object"
    assert isinstance(parameters["properties"], dict)
    assert set(parameters["required"]) == required
    for internal_key in {"scope", "source", "is_write", "agent_name", "metadata", "callable"}:
        assert internal_key not in schema
        assert internal_key not in function


def test_pos_query_agent_card_and_skill_catalog_validate():
    card = _pos_card()

    assert card.display_name == "保全实时查询智能体"
    assert card.required_entities == []
    assert "pos_query_agent.realtime_query" in card.skills
    assert card.public_tools_allowed is False
    for tool_name in {
        "pos_query_available_items",
        "pos_calc_surrender_premium",
        "pos_query_policy_standard",
        "pos_query_approval_text",
        "pos_submit_verify",
    }:
        assert tool_name in card.private_tools

    AgentCardLoader(CARDS_ROOT).validate_with_skill_catalog(SkillCatalog(SKILLS_ROOT))


def test_pos_query_private_tools_have_openai_schema_and_are_read_only():
    registry = _pos_registry()
    expected_required = {
        "pos_query_available_items": {"policyNo", "customerNo"},
        "pos_calc_surrender_premium": {"applyDate", "policyNo", "surDate"},
        "pos_query_policy_standard": {"policyNo"},
        "pos_query_approval_text": {"applySeq"},
        "pos_submit_verify": {"policyNo", "acceptDate"},
    }

    for tool_name, required in expected_required.items():
        definition = registry.get_definition(tool_name)
        assert definition is not None
        assert definition.agent_name == "pos_query_agent"
        assert definition.operation == "read"
        assert definition.is_write is False
        schema = registry.get_tool_schema(tool_name)
        assert schema is not None
        _assert_function_schema(schema, required=required)


def test_pos_query_agent_visible_tools_are_private_only():
    registry = _pos_registry()
    card = _pos_card()

    tool_names = registry.list_available_tools_for_agent(card.agent_name, card)

    assert set(tool_names) == set(card.private_tools)
    assert "rag_search_tool" not in tool_names
    assert all(registry.get_tool_schema(name)["type"] == "function" for name in tool_names)


@pytest.mark.asyncio
async def test_pos_query_approval_text_maps_operator_from_auth_context():
    fake_client = FakePosAPIClient()
    registry = _pos_registry(fake_client)
    executor = ToolExecutor(registry)
    card = _pos_card()
    principal = Principal(tenant_id="tenant-a", subject="subject-a", user_id="HEADER_USER")
    auth_context = AuthContext(principal=principal).model_dump()

    result = await executor.execute(
        agent_name="pos_query_agent",
        tool_name="pos_query_approval_text",
        arguments={"applySeq": "930010412672222", "operatorId": "LLM_USER"},
        agent_card=card,
        request_id="REQ_POS_001",
        session_key="session-pos",
        principal=principal.model_dump(),
        auth_context=auth_context,
    )

    assert result.success is True
    assert fake_client.calls[0]["path"] == "/epos/task/report/queryPreserveChangeDetail"
    assert fake_client.calls[0]["payload"]["applySeq"] == "930010412672222"
    assert fake_client.calls[0]["payload"]["operatorId"] == "HEADER_USER"


@pytest.mark.asyncio
async def test_pos_available_items_tool_payload_mapping():
    fake_client = FakePosAPIClient()
    registry = _pos_registry(fake_client)
    executor = ToolExecutor(registry)
    card = _pos_card()

    result = await executor.execute(
        agent_name="pos_query_agent",
        tool_name="pos_query_available_items",
        arguments={"policyNo": "P001", "customerNo": "C001"},
        agent_card=card,
        request_id="REQ_POS_002",
        session_key="session-pos",
    )

    assert result.success is True
    payload = fake_client.calls[0]["payload"]
    assert fake_client.calls[0]["path"] == "/process/api/i/endotItemType/list"
    assert payload["policyNo"] == "P001"
    assert payload["currentLoginUserInfo"]["customerNo"] == "C001"
    assert payload["src"] == 16


@pytest.mark.asyncio
async def test_pos_intent_rule_fallback_for_approval_text():
    node = IntentRecognitionNode(llm_provider=None)

    result = await node.recognize(
        original_query="帮我做保全批文查询，受理号 930010412672222",
        rewritten_query="帮我做保全批文查询，受理号 930010412672222",
        entities={"apply_seq": "930010412672222"},
        rewrite_type="new_request",
        conversation_window=_window({"apply_seq": "930010412672222"}),
        agent_card_summaries=[card.model_dump() for card in AgentCardLoader(CARDS_ROOT).list_available_agents()],
    )

    assert result.intent == "pos_query"
    assert result.sub_intent == "pos_approval_text_query"
    assert "entities" not in result.model_dump()


@pytest.mark.asyncio
async def test_pos_agent_selection_prefers_pos_query_agent():
    node = AgentSelectionNode(AgentCardLoader(CARDS_ROOT), llm_provider=None)

    result = await node.select(
        intent="pos_query",
        sub_intent="pos_surrender_premium_calc",
        intent_confidence=0.9,
        entities={"policy_no": "9200230000453437"},
        query="退保试算详情，保单号 9200230000453437",
    )

    assert result.selected_agent == "pos_query_agent"


@pytest.mark.asyncio
async def test_pos_tool_missing_required_argument_is_controlled():
    registry = _pos_registry()
    executor = ToolExecutor(registry)
    card = _pos_card()

    result = await executor.execute(
        agent_name="pos_query_agent",
        tool_name="pos_submit_verify",
        arguments={"policyNo": "P001"},
        agent_card=card,
        request_id="REQ_POS_MISSING",
        session_key="session-pos",
    )

    assert result.success is False
    assert result.error == "missing_required_argument:acceptDate"


@pytest.mark.asyncio
async def test_pos_query_agent_tool_loop_executes_read_tool_and_returns_final_answer():
    fake_client = FakePosAPIClient()
    registry = _pos_registry(fake_client)
    executor = ToolExecutor(registry)
    llm = SequencedLLM(
        [
            LLMResponse(
                content=None,
                tool_calls=[
                    {
                        "name": "pos_query_available_items",
                        "arguments": {"policyNo": "P001", "customerNo": "C001"},
                    }
                ],
                has_tool_calls=True,
            ),
            LLMResponse(content="P001 当前可做保全项查询完成。", has_tool_calls=False),
        ]
    )
    runner = ToolCallingRunner(llm_provider=llm, tool_executor=executor)
    card = _pos_card()

    result = await runner.run(
        agent_name="pos_query_agent",
        agent_card=card,
        messages=[{"role": "user", "content": "查询 P001 可以做哪些保全项，客户号 C001"}],
        tools=registry.list_tools_for_agent(card),
        session_key="session-pos",
        request_id="REQ_POS_LOOP",
    )

    assert result.stopped_reason == "final"
    assert result.final_answer == "P001 当前可做保全项查询完成。"
    assert fake_client.calls[0]["path"] == "/process/api/i/endotItemType/list"
    assert result.tool_calls[0]["name"] == "pos_query_available_items"
    assert llm.calls[0]["tools"][0]["type"] == "function"


@pytest.mark.asyncio
async def test_pos_api_client_missing_base_url_returns_controlled_result():
    client = PosAPIClient(BaseIntegrationHTTPClient(base_url=None))

    result = await client.post("/process/api/i/endotItemType/list", {"policyNo": "P001"})

    assert result["success"] is False
    assert result["error"] == "pos_api_base_url_missing"


@pytest.mark.asyncio
async def test_pos_api_client_uses_shared_http_transport():
    async def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://pos.example.test/process/api/i/endotItemType/list"
        assert request.headers["Content-Type"] == "application/json"
        return httpx.Response(200, json={"available_items": []})

    http_client = BaseIntegrationHTTPClient(
        base_url="https://pos.example.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = PosAPIClient(http_client)

    result = await client.post("/process/api/i/endotItemType/list", {"policyNo": "P001"})

    assert result["success"] is True
    assert result["status_code"] == 200
    assert result["url"] == "https://pos.example.test/process/api/i/endotItemType/list"
    assert result["response"] == {"available_items": []}
    await http_client.close()


@pytest.mark.asyncio
async def test_pos_api_client_preserves_non_json_response_as_text():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="upstream plain text")

    http_client = BaseIntegrationHTTPClient(
        base_url="https://pos.example.test",
        client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    client = PosAPIClient(http_client)

    result = await client.post("/process/api/i/endotItemType/list", {"policyNo": "P001"})

    assert result["success"] is True
    assert result["response"] == {"text": "upstream plain text"}
    await http_client.close()
