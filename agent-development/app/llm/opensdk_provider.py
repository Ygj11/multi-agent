from __future__ import annotations

"""OpenAI-compatible SDK provider."""

from time import perf_counter
from typing import Any, Optional

from app.config.settings import Settings, get_settings
from app.llm.model_config import get_llm_model
from app.llm.schemas import LLMResponse
from app.observability.logger import log_event, preview_text

try:
    from openai import AsyncOpenAI
except ImportError:  # pragma: no cover - optional dependency path
    AsyncOpenAI = None  # type: ignore[assignment]


class OpenSDKLLMProvider:
    """Calls an OpenAI-compatible endpoint through the SDK."""

    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = None
        if not self.settings.enable_opensdk_llm and not self.settings.enable_real_llm:
            return
        if AsyncOpenAI is None:
            raise RuntimeError("ENABLE_OPENSDK_LLM=true but the openai package is not installed")
        if not self.settings.openai_api_key:
            raise RuntimeError("ENABLE_OPENSDK_LLM=true but OPENAI_API_KEY is not configured")
        self.client = AsyncOpenAI(
            api_key=self.settings.openai_api_key,
            base_url=self.settings.openai_base_url,
            timeout=self.settings.openai_timeout,
        )

    def get_llm_model(self, scene: str | None = None, explicit_model: str | None = None) -> str:
        if explicit_model:
            return explicit_model
        if scene:
            scene_model = get_llm_model(self.settings, scene=scene, explicit_model=None)
            if scene_model != self.settings.internal_llm_model:
                return scene_model
        return self.settings.openai_model

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
        trace_id: str | None = None,
        session_key: str | None = None,
    ) -> LLMResponse:
        started = perf_counter()
        actual_model = self.get_llm_model(scene=scene, explicit_model=model)
        if self.client is None:
            return LLMResponse(
                content=None,
                finish_reason="error",
                error="opensdk_llm_disabled",
                model=actual_model,
                request_id=request_id,
                latency_ms=0,
            )
        kwargs: dict[str, Any] = {
            "model": actual_model,
            "messages": messages,
            "temperature": self.settings.internal_llm_temperature if temperature is None else temperature,
            "max_tokens": self.settings.internal_llm_max_tokens if max_tokens is None else max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
        try:
            response = await self.client.chat.completions.create(**kwargs)
            choice = response.choices[0]
            message = choice.message
            tool_calls = [call.model_dump() for call in (message.tool_calls or [])]
            result = LLMResponse(
                content=message.content,
                tool_calls=tool_calls,
                has_tool_calls=bool(tool_calls),
                reasoning_content=getattr(message, "reasoning_content", None),
                finish_reason=choice.finish_reason or "stop",
                raw_response=response.model_dump(),
                model=actual_model,
                request_id=request_id,
                latency_ms=int((perf_counter() - started) * 1000),
            )
        except Exception as exc:  # pragma: no cover - requires real SDK call
            result = LLMResponse(
                content=None,
                finish_reason="error",
                error=str(exc),
                model=actual_model,
                request_id=request_id,
                latency_ms=int((perf_counter() - started) * 1000),
            )
        log_event(
            "llm_chat_finished",
            request_id=request_id,
            trace_id=trace_id,
            session_key=session_key,
            node="opensdk_llm_provider",
            message="OpenSDK LLM chat finished",
            data={
                "scene": scene,
                "model": result.model,
                "latency_ms": result.latency_ms,
                "finish_reason": result.finish_reason,
                "error": result.error,
                "content_preview": preview_text(result.content or ""),
                "tool_call_count": len(result.tool_calls),
            },
        )
        return result
