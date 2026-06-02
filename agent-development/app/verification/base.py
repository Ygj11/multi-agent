from __future__ import annotations

"""Verifier protocol."""

from typing import Protocol

from app.verification.schemas import VerificationInput, VerificationResult


class BaseVerifier(Protocol):
    name: str
    stages: list[str]

    async def verify(self, input: VerificationInput) -> VerificationResult:
        ...

