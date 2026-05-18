from __future__ import annotations

"""受控 HTTP / MCP HTTP 工具。

这些工具提供给子 Agent 使用，但默认必须被 PolicyGate 拒绝。只有显式开启
ENABLE_HTTP_TOOLS=true 且目标 host 在白名单中时，才允许经过 ToolBroker 执行。
"""

import json
from typing import Any
from urllib.parse import urljoin

import httpx

from app.observability.logger import log_event, preview_text


class HTTPRequestTool:
    """通用受控 HTTP 请求工具，支持 GET / POST 和 URL 参数。"""

    allowed_methods = {"GET", "POST"}

    def __init__(self, timeout: float = 5.0, client: httpx.AsyncClient | None = None) -> None:
        """注入 timeout 和可选测试 client。"""
        self.timeout = timeout
        self._client = client

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
        """执行受控 HTTP 调用，并返回可审计的结构化结果。"""
        normalized_method = method.upper()
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
        """将 httpx 响应转换成轻量结构，避免把大响应直接塞进工具结果。"""
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
    """通过 HTTP 网关调用 MCP tool 的受控工具。"""

    def __init__(self, timeout: float = 5.0, client: httpx.AsyncClient | None = None) -> None:
        """注入 timeout 和可选测试 client。"""
        self.timeout = timeout
        self.http_request = HTTPRequestTool(timeout=timeout, client=client)

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
        """按约定 MCP HTTP endpoint 调用外部工具。"""
        url = urljoin(base_url.rstrip("/") + "/", endpoint_path.lstrip("/"))
        return await self.http_request(
            method="POST",
            url=url,
            json_body={"tool_name": tool_name, "arguments": arguments or {}},
            timeout=timeout,
        )
