from __future__ import annotations

"""真实外部 API HTTP client 基类示例。"""

from dataclasses import dataclass
from typing import Any

import httpx


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
    """轻量 httpx client 示例，默认不被主流程启用。"""

    def __init__(
        self,
        *,
        base_url: str | None,
        api_token: str | None = None,
        timeout: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        # TODO: 替换真实 base_url、鉴权方式、字段映射、重试、熔断、审计与脱敏策略。
        self.base_url = (base_url or "").rstrip("/")
        self.api_token = api_token
        self.timeout = timeout
        self._client = client

    def build_headers(self, request_id: str | None = None, trace_id: str | None = None) -> dict[str, str]:
        """构造透传 request_id / trace_id 的 headers。"""
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
        """关闭内部 client。"""
        if self._client is not None:
            await self._client.aclose()

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
        client = self._client or httpx.AsyncClient(timeout=timeout or self.timeout)
        should_close = self._client is None
        try:
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
        finally:
            if should_close:
                await client.aclose()

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
