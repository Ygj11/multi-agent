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


async def _echo_tool(request_id: str | None = None):
    return {"request_id": request_id, "status": "active"}


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
            "messages": [{"role": "user", "content": "REQ_001 为什么返回 E102？"}],
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
        agent_name="troubleshooting_agent",
        name="query_internal_log_secure",
        tool=_echo_tool,
        description="Query internal log.",
        parameters={
            "type": "object",
            "properties": {"request_id": {"type": "string"}},
            "required": ["request_id"],
        },
        required_scopes=["troubleshooting:read"],
        resource_type="request",
        resource_id_arg="request_id",
    )
    executor = ToolExecutor(registry, authorization_service=AuthorizationService())

    denied = await executor.execute(
        agent_name="troubleshooting_agent",
        tool_name="query_internal_log_secure",
        arguments={"request_id": "REQ_001"},
    )
    assert denied.success is False
    assert denied.error == "permission_denied:principal_required"

    allowed = await executor.execute(
        agent_name="troubleshooting_agent",
        tool_name="query_internal_log_secure",
        arguments={"request_id": "REQ_001"},
        principal=Principal(tenant_id="t1", subject="u1", user_id="u1", scopes=["troubleshooting:read"]),
    )
    assert allowed.success is True


def test_tool_registry_filters_llm_tools_by_principal_scope():
    registry = ToolRegistry()
    registry.register_private(
        agent_name="troubleshooting_agent",
        name="query_internal_log_secure",
        tool=_echo_tool,
        description="Query internal log.",
        parameters={"type": "object", "properties": {}, "required": []},
        required_scopes=["troubleshooting:read"],
    )
    from app.schemas.agent_card import AgentCard

    card = AgentCard(
        agent_name="troubleshooting_agent",
        display_name="Troubleshooting",
        description="Troubleshooting",
        capabilities=["troubleshooting"],
        supported_intents=["troubleshooting"],
        output_schema="text",
        private_tools=["query_internal_log_secure"],
        version="1",
    )

    assert registry.list_tools_for_agent(card, authorization_service=AuthorizationService()) == []
    schemas = registry.list_tools_for_agent(
        card,
        principal=Principal(tenant_id="t1", subject="u1", scopes=["troubleshooting:read"]),
        authorization_service=AuthorizationService(),
    )
    assert [item["function"]["name"] for item in schemas] == ["query_internal_log_secure"]


def test_agent_access_policy_schema_enforces_principal_boundaries():
    from app.schemas.agent_card import AgentAccessPolicy, AgentCard

    card = AgentCard(
        agent_name="secure_agent",
        display_name="Secure",
        description="Secure agent",
        capabilities=["secure"],
        supported_intents=["secure_query"],
        output_schema="text",
        access_policy=AgentAccessPolicy(
            required_roles=["manager"],
            required_scopes=["secure:read"],
            required_data_permissions=["secure.sensitive.read"],
            allowed_org_types=["headquarter"],
            allowed_org_ids=["org-1"],
            denied_org_ids=["org-9"],
        ),
        version="1",
    )
    service = AuthorizationService()

    denied_without_principal = service.check_agent_access(principal=None, agent_card=card)
    assert denied_without_principal.allowed is False
    assert denied_without_principal.reason == "principal_required"

    denied_scope = service.check_agent_access(
        principal=Principal(
            tenant_id="t1",
            subject="u1",
            roles=["manager"],
            scopes=[],
            data_permissions=["secure.sensitive.read"],
            org_id="org-1",
            attributes={"org_type": "headquarter"},
        ),
        agent_card=card,
    )
    assert denied_scope.allowed is False
    assert denied_scope.reason == "missing_required_scope"
    assert denied_scope.missing_scopes == ["secure:read"]

    denied_data_permission = service.check_agent_access(
        principal=Principal(
            tenant_id="t1",
            subject="u1",
            roles=["manager"],
            scopes=["secure:read"],
            data_permissions=[],
            org_id="org-1",
            attributes={"org_type": "headquarter"},
        ),
        agent_card=card,
    )
    assert denied_data_permission.allowed is False
    assert denied_data_permission.reason == "missing_required_data_permission"
    assert denied_data_permission.missing_data_permissions == ["secure.sensitive.read"]

    denied_org = service.check_agent_access(
        principal=Principal(
            tenant_id="t1",
            subject="u1",
            roles=["manager"],
            scopes=["secure:read"],
            data_permissions=["secure.sensitive.read"],
            org_id="org-9",
            attributes={"org_type": "headquarter"},
        ),
        agent_card=card,
    )
    assert denied_org.allowed is False
    assert denied_org.reason == "org_id_denied"

    allowed = service.check_agent_access(
        principal=Principal(
            tenant_id="t1",
            subject="u1",
            roles=["manager"],
            scopes=["secure:read"],
            data_permissions=["secure.sensitive.read"],
            org_id="org-1",
            attributes={"org_type": "headquarter"},
        ),
        agent_card=card,
    )
    assert allowed.allowed is True


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
