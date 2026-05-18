from __future__ import annotations

"""OpenAI-compatible LLM Provider。

该实现完整保留真实模型调用能力，但默认不启用，确保本地测试不依赖 API key。
"""

import json
from typing import Any

from app.config.settings import Settings, get_settings
from app.llm.provider import LLMProvider

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - exercised only when optional package is absent
    AsyncOpenAI = None  # type: ignore[assignment]


class OpenAICompatibleLLMProvider(LLMProvider):
    """通过 openai SDK 调用兼容 Chat Completions 的模型服务。"""

    def __init__(self, settings: Settings | None = None) -> None:
        """按 ENABLE_REAL_LLM 决定是否初始化真实客户端。"""
        self.settings = settings or get_settings()
        if not self.settings.enable_real_llm:
            self.client = None
            return
        if AsyncOpenAI is None:
            raise RuntimeError("ENABLE_REAL_LLM=true but the openai package is not installed")
        if not self.settings.openai_api_key:
            raise RuntimeError("ENABLE_REAL_LLM=true but OPENAI_API_KEY is not configured")

        self.client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            timeout=self.settings.openai_timeout,
        )

    async def chat(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> str:
        """调用真实模型并返回文本内容。"""
        if self.client is None:
            raise RuntimeError("Real LLM is disabled. Set ENABLE_REAL_LLM=true to enable it.")
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,
                timeout=timeout or self.settings.openai_timeout,
            )
            message = response.choices[0].message
            return message.content or ""
        except Exception as exc:  # pragma: no cover - requires real API
            raise RuntimeError(f"OpenAI-compatible chat call failed: {exc}") from exc

    async def chat_json(
        self,
        messages: list[dict[str, str]],
        tools: list[dict[str, Any]] | None = None,
        timeout: float | None = None,
    ) -> dict[str, Any]:
        """调用真实模型并要求返回 JSON object。"""
        if self.client is None:
            raise RuntimeError("Real LLM is disabled. Set ENABLE_REAL_LLM=true to enable it.")
        try:
            response = await self.client.chat.completions.create(
                model=self.settings.openai_model,
                messages=messages,  # type: ignore[arg-type]
                tools=tools,
                timeout=timeout or self.settings.openai_timeout,
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content or "{}"
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise ValueError("model returned JSON that is not an object")
            return parsed
        except json.JSONDecodeError as exc:  # pragma: no cover - requires real API
            raise RuntimeError(f"OpenAI-compatible chat_json returned invalid JSON: {exc}") from exc
        except Exception as exc:  # pragma: no cover - requires real API
            raise RuntimeError(f"OpenAI-compatible chat_json call failed: {exc}") from exc
