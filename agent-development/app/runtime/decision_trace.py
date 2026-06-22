from __future__ import annotations

"""Small helpers for observable runtime decisions."""

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class LLMAttempt:
    """Normalized status for one optional LLM attempt."""

    llm_status: str
    fallback_reason: str | None = None
    detail: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def trace(self, *, source: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "source": source,
            "llm_status": self.llm_status,
        }
        if self.fallback_reason:
            payload["fallback_reason"] = self.fallback_reason
        if self.detail:
            payload["detail"] = self.detail
        payload.update(self.extra)
        return payload


def fallback_trace(
    *,
    source: str,
    fallback_reason: str,
    llm_status: str | None = None,
    detail: str | None = None,
    **extra: Any,
) -> dict[str, Any]:
    """Build a compact decision trace for a fallback path."""
    payload: dict[str, Any] = {
        "source": source,
        "fallback_used": True,
        "fallback_reason": fallback_reason,
    }
    if llm_status is not None:
        payload["llm_status"] = llm_status
    if detail:
        payload["detail"] = detail
    payload.update(extra)
    return payload

