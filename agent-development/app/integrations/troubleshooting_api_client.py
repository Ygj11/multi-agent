from __future__ import annotations

"""Real troubleshooting API client used by TROUBLESHOOTING_TOOL_MODE=real."""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class TroubleshootingAPIClient:
    """HTTP boundary for workflow, log, and endorsement aftercare APIs."""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def close(self) -> None:
        """释放排障 API 的 HTTP 连接池。"""
        await self.http.close()

    async def query_task_status(self, request_id: str | None) -> dict[str, Any]:
        return await self.http.get_json(f"/workflow/tasks/{request_id}/status")

    async def query_node_status(self, request_id: str | None, node_name: str | None) -> dict[str, Any]:
        return await self.http.get_json(f"/workflow/tasks/{request_id}/nodes/{node_name or ''}")

    async def query_internal_log(self, request_id: str | None = None, query: str | None = None) -> dict[str, Any]:
        return await self.http.get_json(
            "/logs/internal",
            params={"request_id": request_id, "query": query},
        )

    async def query_endo_task_record(self, apply_seq: str | None) -> dict[str, Any]:
        return await self.http.get_json(f"/endo/tasks/{apply_seq}/records")

    async def notice_policy_update(
        self,
        *,
        apply_seq: str | None,
        policyNo: str | None,
        endorseType: str | None,
    ) -> dict[str, Any]:
        return await self.http.post_json(
            "/endo/notice/policy-update",
            payload={"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
        )

    async def notice_customer_update(
        self,
        *,
        apply_seq: str | None,
        policyNo: str | None,
        endorseType: str | None,
    ) -> dict[str, Any]:
        return await self.http.post_json(
            "/endo/notice/customer-update",
            payload={"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
        )

    async def notice_period_update(
        self,
        *,
        apply_seq: str | None,
        policyNo: str | None,
        endorseType: str | None,
    ) -> dict[str, Any]:
        return await self.http.post_json(
            "/endo/notice/period-update",
            payload={"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
        )

    async def policy_suspend_or_recovery(
        self,
        *,
        handleType: str | None,
        premHandleFlag: str | None,
        reqList: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        return await self.http.post_json(
            "/policy/suspendOrRecovery",
            payload={"handleType": handleType, "premHandleFlag": premHandleFlag, "reqList": reqList or []},
        )

    async def notice_finance(
        self,
        *,
        apply_seq: str | None,
        policyNo: str | None,
        endorseType: str | None,
    ) -> dict[str, Any]:
        return await self.http.post_json(
            "/endo/notice/finance",
            payload={"apply_seq": apply_seq, "policyNo": policyNo, "endorseType": endorseType},
        )
