from __future__ import annotations

"""Protocol for model-only LLM providers."""

from typing import Any, Optional, Protocol

from app.llm.schemas import LLMResponse


class LLMProvider(Protocol):
    """Provider boundary: call the model and normalize its response only."""

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
        ...

