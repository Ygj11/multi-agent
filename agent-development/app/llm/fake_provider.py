from __future__ import annotations

"""默认启用的确定性 Fake LLM。"""

from typing import Any

from app.llm.provider import LLMProvider


class FakeLLMProvider(LLMProvider):
    """不依赖网络和 API key 的测试友好模型实现。"""

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> str:
        """根据关键词返回固定文本，保证测试可复现。"""
        text = " ".join(message.get("content", "") for message in messages)
        if "E102" in text:
            return "E102 通常表示签名校验失败，请检查 timestamp、密钥版本和字段排序。"
        return "这是 FakeLLMProvider 的确定性回复。"

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """把 chat 结果包装为简单 JSON 对象。"""
        content = await self.chat(messages=messages, tools=tools, timeout=timeout)
        return {"content": content}
