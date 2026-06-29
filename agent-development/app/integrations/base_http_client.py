from __future__ import annotations

"""真实外部 API 的共享 HTTP 传输层。"""

from dataclasses import dataclass
from typing import Any

import httpx

from app.runtime.async_client_lifecycle import AsyncClientLifecycle


SENSITIVE_KEYS = {"secret", "token", "password", "api_key", "authorization"}


class IntegrationAPIError(RuntimeError):
    """外部 API 调用失败。"""


@dataclass(frozen=True)
class IntegrationHTTPResponse:
    """通用 HTTP 传输层返回的结构化响应，保留 JSON 或文本回退内容。"""

    url: str
    status_code: int
    body: Any


class BaseIntegrationHTTPClient:
    """为一个长期领域 Client 复用 httpx 连接池。

    该传输层不在请求间修改共享 client 的全局 headers/cookies；用户级身份、
    request_id 和 trace_id 都通过单次请求参数传入，避免并发请求串身份。

    共享 HTTP 传输层，负责连接池复用、请求级 headers、JSON 请求、基础脱敏和关闭生命周期。
    使用者：PosAPIClient、TroubleshootingAPIClient、KnowledgeAPIClient 以及示例 Client
    """

    def __init__(
        self,
        *,
        base_url: str | None,
        api_token: str | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
        owns_client: bool = False,
    ) -> None:
        # TODO: 替换真实 base_url、鉴权方式、字段映射、重试、熔断、审计与脱敏策略。
        self.base_url = (base_url or "").rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self._client_lifecycle = AsyncClientLifecycle(
            factory=lambda: httpx.AsyncClient(timeout=self.timeout),
            close_client=lambda value: value.aclose(),
            client=client,
            owns_client=owns_client,
        )

    def build_headers(self, request_id: str | None = None, trace_id: str | None = None) -> dict[str, str]:
        """为单次请求构造 headers，不修改共享 AsyncClient 状态。"""
        headers = {"Content-Type": "application/json"}
        if self.api_token:
            headers["Authorization"] = f"Bearer {self.api_token}"
        if request_id:
            headers["X-Request-Id"] = request_id
        if trace_id:
            headers["X-Trace-Id"] = trace_id
        return headers

    async def get_json(
        self,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """GET JSON 示例。"""
        response = await self.request_json(
            "GET",
            path,
            params=params,
            request_id=request_id,
            trace_id=trace_id,
            timeout=timeout,
        )
        return self._require_object_body(response.body)

    async def post_json(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """POST JSON 示例。"""
        response = await self.request_json(
            "POST",
            path,
            json_payload=payload or {},
            request_id=request_id,
            trace_id=trace_id,
            timeout=timeout,
        )
        return self._require_object_body(response.body)

    async def post_json_response(
        self,
        path: str,
        *,
        payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        timeout: float | None = None,
    ) -> IntegrationHTTPResponse:
        """POST JSON，并返回状态码、最终 URL 与 JSON 响应体。"""
        return await self.request_json(
            "POST",
            path,
            json_payload=payload or {},
            request_id=request_id,
            trace_id=trace_id,
            timeout=timeout,
        )

    async def close(self) -> None:
        """关闭自有连接池；外部注入的共享 client 仍由外部 Owner 关闭。"""
        await self._client_lifecycle.close()

    async def request_json(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_payload: dict[str, Any] | None = None,
        request_id: str | None = None,
        trace_id: str | None = None,
        timeout: float | None = None,
    ) -> IntegrationHTTPResponse:
        """统一执行 JSON 请求，并保留响应元数据给领域 Client 使用。"""
        if not self.base_url:
            raise IntegrationAPIError("Integration base_url is not configured; real API calls are disabled by default.")
        url = path if path.startswith(("http://", "https://")) else f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with self._client_lifecycle.lease() as client:
                response = await client.request(
                    method,
                    url,
                    params=params,
                    json=json_payload,
                    headers=self.build_headers(request_id=request_id, trace_id=trace_id),
                    timeout=timeout or self.timeout,
                )
            response.raise_for_status()
            try:
                data: Any = response.json()
            except ValueError:
                data = {"text": response.text}
            return IntegrationHTTPResponse(
                url=str(response.url),
                status_code=response.status_code,
                body=data,
            )
        except httpx.HTTPError as exc:
            safe_payload = self.mask_sensitive(json_payload or params or {})
            raise IntegrationAPIError(f"Integration API request failed: {exc}; payload={safe_payload}") from exc

    async def _get_client(self) -> httpx.AsyncClient:
        """仅供测试断言当前 client；生产请求通过 lease() 借用。"""
        return await self._client_lifecycle.get_client_for_testing()

    @staticmethod
    def _require_object_body(body: Any) -> dict[str, Any]:
        if not isinstance(body, dict):
            raise IntegrationAPIError("Integration API returned non-object JSON")
        return body

    @classmethod
    def mask_sensitive(cls, value: Any) -> Any:
        """递归脱敏常见敏感字段。"""
        if isinstance(value, dict):
            return {
                key: "***" if str(key).lower() in SENSITIVE_KEYS else cls.mask_sensitive(item)
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [cls.mask_sensitive(item) for item in value]
        return value
