from __future__ import annotations

"""Restricted HTTP / MCP-over-HTTP tools."""

import json
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.observability.logger import log_event, preview_text


class HTTPRequestTool:
    """Controlled HTTP request tool with built-in enable switch and host allowlist."""

    allowed_methods = {"GET", "POST"}

    def __init__(
        self,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
        *,
        enabled: bool = False,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self.timeout = timeout
        self._client = client
        self.enabled = enabled
        self.allowed_hosts = set(allowed_hosts)

    async def __call__(
        self,
        *,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        normalized_method = method.upper()
        if not self.enabled:
            return {"success": False, "error": "http_tools_disabled"}
        if normalized_method not in self.allowed_methods:
            return {"success": False, "error": f"method_not_allowed:{normalized_method}"}
        host = urlparse(url).hostname or ""
        if host not in self.allowed_hosts:
            return {"success": False, "error": f"host not allowlisted: {host}"}

        effective_timeout = min(float(timeout or self.timeout), self.timeout)
        log_event(
            "http_tool_call_started",
            node="http_request_tool",
            message="HTTP tool call started",
            data={"method": normalized_method, "url": url, "params_preview": params or {}},
        )
        client = self._client or httpx.AsyncClient(timeout=effective_timeout)
        should_close = self._client is None
        try:
            response = await client.request(
                normalized_method,
                url,
                params=params,
                json=json_body,
                headers=headers,
                timeout=effective_timeout,
            )
            result = self._response_to_result(response)
            log_event(
                "http_tool_call_finished",
                node="http_request_tool",
                message="HTTP tool call finished",
                data={
                    "method": normalized_method,
                    "url": url,
                    "status_code": response.status_code,
                    "result_preview": preview_text(str(result.get("body_json") or result.get("body_text"))),
                },
            )
            return result
        except httpx.HTTPError as exc:
            log_event(
                "http_tool_call_finished",
                level="ERROR",
                node="http_request_tool",
                message="HTTP tool call failed",
                data={"method": normalized_method, "url": url, "error": str(exc)},
            )
            return {"success": False, "error": str(exc), "status_code": None}
        finally:
            if should_close:
                await client.aclose()

    @staticmethod
    def _response_to_result(response: httpx.Response) -> dict[str, Any]:
        content_type = response.headers.get("content-type", "")
        result: dict[str, Any] = {
            "success": 200 <= response.status_code < 400,
            "status_code": response.status_code,
            "content_type": content_type,
        }
        try:
            result["body_json"] = response.json()
        except json.JSONDecodeError:
            result["body_text"] = response.text[:2000]
        return result


class MCPHTTPCallTool:
    """Call an MCP HTTP gateway through the restricted HTTP request tool."""

    def __init__(
        self,
        timeout: float = 5.0,
        client: httpx.AsyncClient | None = None,
        *,
        enabled: bool = False,
        allowed_hosts: tuple[str, ...] = (),
    ) -> None:
        self.timeout = timeout
        self.http_request = HTTPRequestTool(
            timeout=timeout,
            client=client,
            enabled=enabled,
            allowed_hosts=allowed_hosts,
        )

    async def __call__(
        self,
        *,
        base_url: str,
        tool_name: str,
        arguments: dict[str, Any] | None = None,
        endpoint_path: str = "/mcp/tools/call",
        timeout: float | None = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        url = urljoin(base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))
        return await self.http_request(
            method="POST",
            url=url,
            json_body={"tool_name": tool_name, "arguments": arguments or {}},
            timeout=timeout,
        )
