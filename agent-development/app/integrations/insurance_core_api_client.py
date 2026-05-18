from __future__ import annotations

"""未来保险核心系统 API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class InsuranceCoreAPIClient:
    """未来接保险核心系统的只读/校验能力示例，默认不启用。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def get_policy(self, policy_no: str, request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 未来接真实保险核心系统前必须增加鉴权、审批、脱敏、审计和只读限制。
        return await self.http.get_json(f"/core/policies/{policy_no}", request_id=request_id, trace_id=trace_id)

    async def get_product(self, product_code: str, request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 增加产品版本、生效时间、渠道权限过滤。
        return await self.http.get_json(f"/core/products/{product_code}", request_id=request_id, trace_id=trace_id)

    async def validate_proposal(self, payload: dict[str, Any], request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 真实校验前必须确认非生产写操作、幂等、审批和完整审计。
        return await self.http.post_json("/core/proposals/validate", payload=payload, request_id=request_id, trace_id=trace_id)

