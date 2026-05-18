from __future__ import annotations

"""Fake MCP Connector。

用于第三阶段本地验证 MCP 工具边界，不连接真实 MCP Server。
"""

from typing import Any

from app.mcp.connector import MCPConnector
from app.observability.logger import log_event


class FakeMCPConnector(MCPConnector):
    """提供 fake partner trace 工具的 MCPConnector 实现。"""

    tool_name = "partner_trace.get_request_detail"

    async def list_tools(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """返回 fake MCP 工具描述。"""
        log_event(
            "mcp_list_tools",
            node="fake_mcp_connector",
            message="MCP tools listed",
            data={"tool_name": self.tool_name},
        )
        return [
            {
                "name": self.tool_name,
                "description": "查询合作方渠道侧请求 trace 明细",
                "input_schema": {"request_id": "string"},
            }
        ]

    async def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """按 tool_name 调用 fake MCP 工具。"""
        log_event(
            "mcp_call_started",
            node="fake_mcp_connector",
            message="MCP call started",
            data={"tool_name": tool_name, "request_id": arguments.get("request_id")},
        )
        if tool_name != self.tool_name:
            result = {"success": False, "error": f"unknown MCP tool: {tool_name}"}
            log_event(
                "mcp_call_finished",
                level="WARNING",
                node="fake_mcp_connector",
                message="MCP call failed",
                data={"tool_name": tool_name, "found": False, "summary_preview": result["error"]},
            )
            return result
        request_id = str(arguments.get("request_id", ""))
        result = self._get_request_detail(request_id)
        log_event(
            "mcp_call_finished",
            node="fake_mcp_connector",
            message="MCP call finished",
            data={
                "tool_name": tool_name,
                "request_id": request_id,
                "found": result.get("found"),
                "summary_preview": result.get("summary") or result.get("message"),
            },
        )
        return result

    @staticmethod
    def _get_request_detail(request_id: str) -> dict[str, Any]:
        """返回渠道侧 trace mock 数据。"""
        traces = {
            "REQ_001": {
                "found": True,
                "request_id": "REQ_001",
                "partner": "XX_CHANNEL",
                "trace_source": "partner_trace",
                "partner_signature_rule_version": "v1",
                "expected_signature_rule_version": "v2",
                "timestamp_included_in_sign": False,
                "base_string_fields": ["appId", "nonce", "body"],
                "missing_fields": ["timestamp"],
                "summary": "渠道侧 trace 显示仍使用旧版 v1 签名规则，签名原文未包含 timestamp。",
            },
            "REQ_002": {
                "found": True,
                "request_id": "REQ_002",
                "partner": "XX_CHANNEL",
                "trace_source": "partner_trace",
                "partner_signature_rule_version": "v2",
                "expected_signature_rule_version": "v2",
                "timestamp_included_in_sign": True,
                "timestamp_status": "expired",
                "summary": "渠道侧 trace 显示 timestamp 已过期，疑似渠道侧时间窗口或重放策略异常。",
            },
        }
        return traces.get(
            request_id,
            {
                "found": False,
                "request_id": request_id,
                "message": "未查询到该 requestId 的渠道侧 trace",
            },
        )
