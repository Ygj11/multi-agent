from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.adapters.request_adapter import RequestAdapter
from app.auth.authorization_service import AuthorizationService
from app.auth.principal import Principal
from app.schemas.message import ChatMessage, ChatRequest
from app.tools.executor import ToolExecutor
from app.tools.registry import ToolRegistry
from app.verification.schemas import VerificationInput
from app.verification.service import VerificationService
from app.verification.verifiers.data_permission_verifier import DataPermissionVerifier


async def _echo_tool(policy_no: str | None = None):
    return {"policy_no": policy_no, "status": "active"}


def test_chat_uses_header_principal_for_session_key(app_factory):
    app = app_factory()
    client = TestClient(app)

    response = client.post(
        "/api/chat",
        headers={
            "x-tenant-id": "tenant_header",
            "x-user-id": "user_header",
            "x-user-scopes": "policy:read,troubleshooting:read",
        },
        json={
            "tenant_id": "tenant_header",
            "channel": "web",
            "user_id": "body_user",
            "session_id": "s001",
            "messages": [{"role": "user", "content": "查询保单状态"}],
        },
    )

    assert response.status_code == 200
    assert response.json()["session_key"] == "tenant_header:web:user_header:s001"


def test_request_adapter_rejects_body_identity_override_when_fallback_disabled(monkeypatch):
    monkeypatch.setenv("ALLOW_REQUEST_BODY_IDENTITY_FALLBACK", "false")
    request = ChatRequest(
        tenant_id="t1",
        channel="web",
        user_id="body_user",
        session_id="s1",
        messages=[ChatMessage(role="user", content="hello")],
    )
    principal = Principal(tenant_id="t1", subject="header_user", user_id="header_user")

    with pytest.raises(PermissionError):
        RequestAdapter().adapt(request, principal=principal)


@pytest.mark.asyncio
async def test_tool_executor_enforces_required_scope():
    registry = ToolRegistry()
    registry.register_private(
        agent_name="policy_query_agent",
        name="query_policy_info_secure",
        tool=_echo_tool,
        description="Query policy info.",
        parameters={
            "type": "object",
            "properties": {"policy_no": {"type": "string"}},
            "required": ["policy_no"],
        },
        required_scopes=["policy:read"],
        resource_type="policy",
        resource_id_arg="policy_no",
    )
    executor = ToolExecutor(registry, authorization_service=AuthorizationService())

    denied = await executor.execute(
        agent_name="policy_query_agent",
        tool_name="query_policy_info_secure",
        arguments={"policy_no": "P001"},
    )
    assert denied.success is False
    assert denied.error == "permission_denied:principal_required"

    allowed = await executor.execute(
        agent_name="policy_query_agent",
        tool_name="query_policy_info_secure",
        arguments={"policy_no": "P001"},
        principal=Principal(tenant_id="t1", subject="u1", user_id="u1", scopes=["policy:read"]),
    )
    assert allowed.success is True


def test_tool_registry_filters_llm_tools_by_principal_scope():
    registry = ToolRegistry()
    registry.register_private(
        agent_name="policy_query_agent",
        name="query_policy_info_secure",
        tool=_echo_tool,
        description="Query policy info.",
        parameters={"type": "object", "properties": {}, "required": []},
        required_scopes=["policy:read"],
    )
    from app.schemas.agent_card import AgentCard

    card = AgentCard(
        agent_name="policy_query_agent",
        display_name="Policy",
        description="Policy query",
        capabilities=["policy"],
        supported_intents=["policy_query"],
        output_schema="text",
        private_tools=["query_policy_info_secure"],
        version="1",
    )

    assert registry.list_tools_for_agent(card, authorization_service=AuthorizationService()) == []
    schemas = registry.list_tools_for_agent(
        card,
        principal=Principal(tenant_id="t1", subject="u1", scopes=["policy:read"]),
        authorization_service=AuthorizationService(),
    )
    assert [item["function"]["name"] for item in schemas] == ["query_policy_info_secure"]


@pytest.mark.asyncio
async def test_pre_answer_data_permission_verifier_redacts_without_sensitive_permission():
    service = VerificationService([DataPermissionVerifier()])
    result = await service.verify(
        VerificationInput(
            stage="pre_answer",
            answer="客户手机号 13812345678，身份证 110101199001011234",
            principal=Principal(tenant_id="t1", subject="u1", user_id="u1").model_dump(),
        )
    )

    assert result.action == "patch"
    assert "***PHONE***" in result.patched_output
    assert "***ID_CARD***" in result.patched_output


@pytest.mark.asyncio
async def test_pre_answer_data_permission_verifier_allows_sensitive_permission():
    service = VerificationService([DataPermissionVerifier()])
    result = await service.verify(
        VerificationInput(
            stage="pre_answer",
            answer="客户手机号 13812345678",
            principal=Principal(
                tenant_id="t1",
                subject="u1",
                user_id="u1",
                data_permissions=["policy.sensitive.read"],
            ).model_dump(),
        )
    )

    assert result.action == "allow"
