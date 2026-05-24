import json

import httpx
import pytest

from app.approval.client import ApprovalSystemClient
from app.config.settings import Settings
from app.schemas.approval import ApprovalRequest


@pytest.mark.asyncio
async def test_approval_system_client_posts_payload_and_returns_pending():
    captured = {}

    async def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["payload"] = json.loads(request.content.decode())
        return httpx.Response(
            200,
            json={"accepted": True, "external_approval_id": "ext_1", "status": "pending"},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = ApprovalSystemClient(
            settings=Settings(
                approval_system_url="http://approval.local/requests",
                approval_callback_url="http://app.local/api/approval/callback",
            ),
            client=http_client,
        )
        result = await client.submit_approval_request(
            ApprovalRequest(
                approval_id="approval_1",
                session_key="s",
                request_id="r",
                trace_id="t",
                agent_name="agent_a",
                tool_name="write_tool",
                operation_type="update",
                risk_level="high",
                arguments={"value": "x"},
                reason="test",
                callback_url="http://app.local/api/approval/callback",
            )
        )

    assert captured["url"] == "http://approval.local/requests"
    assert captured["payload"]["approval_id"] == "approval_1"
    assert captured["payload"]["callback_url"] == "http://app.local/api/approval/callback"
    assert result.accepted is True
    assert result.external_approval_id == "ext_1"
    assert result.status == "pending"


@pytest.mark.asyncio
async def test_approval_system_client_marks_submit_failed_on_http_error():
    async def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, json={"accepted": False})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = ApprovalSystemClient(
            settings=Settings(approval_system_url="http://approval.local/requests"),
            client=http_client,
        )
        result = await client.submit_approval_request(
            ApprovalRequest(
                approval_id="approval_1",
                agent_name="agent_a",
                tool_name="write_tool",
                arguments={"value": "x"},
                reason="test",
            )
        )

    assert result.accepted is False
    assert result.status == "submit_failed"
    assert result.error
