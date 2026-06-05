from __future__ import annotations

"""POS API client for real-time preservation queries."""

from time import perf_counter
from typing import Any
from urllib.parse import urljoin

import httpx

from app.observability.logger import log_event, preview_text


class PosAPIClient:
    """Thin async HTTP client for POS preservation APIs."""

    def __init__(self, *, base_url: str | None, timeout: float = 10.0, enabled: bool = True) -> None:
        self.base_url = (base_url or "").rstrip("/")
        self.timeout = timeout
        self.enabled = enabled

    async def post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        """POST JSON to one POS endpoint and return a normalized result dict."""
        started = perf_counter()
        url = self._url(path)
        if not self.enabled:
            return self._result(
                success=False,
                path=path,
                url=url,
                payload=payload,
                error="pos_api_disabled",
                started=started,
            )
        if not url:
            return self._result(
                success=False,
                path=path,
                url=url,
                payload=payload,
                error="pos_api_base_url_missing",
                started=started,
            )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(url, json=payload)
            response.raise_for_status()
            try:
                body: Any = response.json()
            except ValueError:
                body = {"text": response.text}
            return self._result(
                success=True,
                path=path,
                url=url,
                payload=payload,
                response=body,
                status_code=response.status_code,
                started=started,
            )
        except Exception as exc:
            return self._result(
                success=False,
                path=path,
                url=url,
                payload=payload,
                error=str(exc),
                started=started,
            )

    def _url(self, path: str) -> str:
        if path.startswith(("http://", "https://")):
            return path
        if not self.base_url:
            return ""
        return urljoin(f"{self.base_url}/", path.lstrip("/"))

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
