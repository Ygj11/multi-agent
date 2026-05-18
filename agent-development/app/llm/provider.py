from __future__ import annotations

"""LLM Provider 抽象接口。"""

from abc import ABC, abstractmethod
from typing import Any


class LLMProvider(ABC):
    """统一不同模型后端的最小接口。"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> str:
        """返回纯文本模型回复。"""
        raise NotImplementedError

    @abstractmethod
    async def chat_json(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """返回 JSON 对象格式的模型回复。"""
        raise NotImplementedError
