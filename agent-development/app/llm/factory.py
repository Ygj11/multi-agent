from __future__ import annotations

"""LLM provider factory."""

from app.config.settings import Settings
from app.llm.base import LLMProvider
from app.llm.internal_provider import InternalLLMProvider
from app.llm.opensdk_provider import OpenSDKLLMProvider


def build_llm_provider(settings: Settings) -> LLMProvider:
    """Build one provider for application-wide dependency injection."""
    if settings.enable_opensdk_llm:
        return OpenSDKLLMProvider(settings)
    return InternalLLMProvider(settings)

