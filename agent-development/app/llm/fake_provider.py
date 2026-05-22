from __future__ import annotations

"""Deterministic test LLM provider."""

from typing import Any, Optional

from app.llm.schemas import LLMResponse


class FakeLLMProvider:
    """Network-free provider useful in isolated unit tests."""

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        *,
        scene: str | None = None,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
        request_id: str | None = None,
    ) -> LLMResponse:
        text = " ".join(str(message.get("content", "")) for message in messages)
        content = "E102 通常表示签名校验失败，请检查 timestamp、密钥版本和字段排序。" if "E102" in text else "这是 FakeLLMProvider 的确定性回复。"
        return LLMResponse(
            content=content,
            tool_calls=[],
            has_tool_calls=False,
            finish_reason="stop",
            model=model or "fake",
            request_id=request_id,
            latency_ms=0,
        )

    async def chat_json(
        self,
        messages: list[dict[str, Any]],
        tools: Optional[list[dict[str, Any]]] = None,
        **kwargs: Any,
    ) -> dict[str, Any]:
        response = await self.chat(messages=messages, tools=tools, **kwargs)
        return {"content": response.content}

