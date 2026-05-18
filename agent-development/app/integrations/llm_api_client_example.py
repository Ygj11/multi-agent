from __future__ import annotations

"""未来真实 LLM API client 示例。"""

from typing import Any

from app.integrations.base_http_client import BaseIntegrationHTTPClient


class LLMAPIClientExample:
    """未来可作为真实 LLM Provider 底层 client 示例，默认不启用。"""

    def __init__(self, http_client: BaseIntegrationHTTPClient) -> None:
        self.http = http_client

    async def chat(self, messages: list[dict[str, Any]], request_id: str | None = None, trace_id: str | None = None) -> str:
        # TODO: 替换真实模型地址、鉴权、模型参数、token 预算和输出脱敏。
        data = await self.http.post_json("/llm/chat", payload={"messages": messages}, request_id=request_id, trace_id=trace_id)
        return str(data.get("content", ""))

    async def chat_json(self, messages: list[dict[str, Any]], request_id: str | None = None, trace_id: str | None = None) -> dict[str, Any]:
        # TODO: 未来补充 JSON schema 约束和模型异常降级。
        return await self.http.post_json("/llm/chat-json", payload={"messages": messages}, request_id=request_id, trace_id=trace_id)

