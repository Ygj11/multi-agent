from __future__ import annotations

"""Client for the external human approval system."""

import httpx

from app.config.settings import Settings, get_settings
from app.schemas.approval import ApprovalRequest, ApprovalSubmitResult


class ApprovalSystemClient:
    """Submits approval requests to an external approval system."""

    def __init__(self, settings: Settings | None = None, client: httpx.AsyncClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client

    async def submit_approval_request(self, request: ApprovalRequest) -> ApprovalSubmitResult:
        """Submit one approval request and normalize the external response."""
        if not self.settings.enable_external_approval:
            return ApprovalSubmitResult(
                accepted=True,
                external_approval_id=f"local_{request.approval_id}",
                status="pending",
                raw_response={"external_approval_disabled": True},
            )

        payload = {
            "approval_id": request.approval_id,
            "request_id": request.request_id,
            "trace_id": request.trace_id,
            "session_key": request.session_key,
            "tenant_id": request.tenant_id,
            "subject": request.subject,
            "user_id": request.user_id,
            "org_id": request.org_id,
            "agent_name": request.agent_name,
            "tool_name": request.tool_name,
            "operation_type": request.operation_type,
            "risk_level": request.risk_level,
            "resource_type": request.resource_type,
            "resource_id": request.resource_id,
            "arguments": request.arguments,
            "reason": request.reason,
            "callback_url": request.callback_url or self.settings.approval_callback_url,
            "created_at": request.created_at,
        }
        try:
            if self.client is not None:
                response = await self.client.post(str(self.settings.approval_system_url), json=payload)
            else:
                async with httpx.AsyncClient(timeout=self.settings.approval_system_timeout) as client:
                    response = await client.post(str(self.settings.approval_system_url), json=payload)
            response.raise_for_status()
            data = response.json()
            return ApprovalSubmitResult(
                accepted=bool(data.get("accepted")),
                external_approval_id=data.get("external_approval_id"),
                status=data.get("status") or "pending",
                raw_response=data if isinstance(data, dict) else {"raw": data},
            )
        except Exception as exc:
            return ApprovalSubmitResult(accepted=False, status="submit_failed", error=str(exc))
