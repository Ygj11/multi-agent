from __future__ import annotations

"""POS API client for real-time preservation queries."""

from time import perf_counter
from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient
from app.observability.logger import log_event, preview_text


class PosAPIClient:
    """POS 领域 Client，复用统一 HTTP 传输层并保留 POS 结果契约。
    POS_TOOL_MODE=real 时由 AppContainer 构建，再被 POS tool handlers 使用
    """

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def close(self) -> None:
        """释放 POS HTTP 连接池。"""
        await self.http.close()

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to one POS endpoint and return a normalized result dict."""
        started = perf_counter()
        if not self.http.base_url:
            return self._result(
                success=False,
                path=path,
                url="",
                payload=payload,
                error="pos_api_base_url_missing",
                started=started,
            )
        try:
            response = await self.http.post_json_response(path, payload=payload)
            return self._result(
                success=True,
                path=path,
                url=response.url,
                payload=payload,
                response=response.body,
                status_code=response.status_code,
                started=started,
            )
        except Exception as exc:
            return self._result(
                success=False,
                path=path,
                url=self._url(path),
                payload=payload,
                error=str(exc),
                started=started,
            )

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not self.http.base_url:
            return ""
        return f"{self.http.base_url}/{path.lstrip('/')}"

    @staticmethod
    def _result(
        *,
        success: bool,
        path: str,
        url: str,
        payload: dict[str, Any],
        started: float,
        response: Any | None = None,
        status_code: int | None = None,
        error: str | None = None,
    ) -> dict[str, Any]:
        duration_ms = max(0, int((perf_counter() - started) * 1000))
        result = {
            "success": success,
            "path": path,
            "url": url,
            "request_payload": payload,
            "response": response,
            "status_code": status_code,
            "error": error,
            "duration_ms": duration_ms,
        }
        log_event(
            "pos_api_call_finished",
            node="pos_api_client",
            message="POS API call finished",
            data={
                "path": path,
                "url": url,
                "success": success,
                "status_code": status_code,
                "error": error,
                "duration_ms": duration_ms,
                "response_preview": preview_text(str(response)) if response is not None else None,
            },
        )
        return result
