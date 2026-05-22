from __future__ import annotations

"""Backward-compatible OpenAI-compatible provider name.

New code should import `OpenSDKLLMProvider` from `app.llm.opensdk_provider`.
"""

from app.llm.opensdk_provider import OpenSDKLLMProvider


class OpenAICompatibleLLMProvider(OpenSDKLLMProvider):
    """Compatibility alias kept for legacy tests/imports."""

