from __future__ import annotations

"""Verifier protocol."""

from typing import Protocol

from app.schemas.enums.verification import VerificationStage
from app.verification.schemas import VerificationInput, VerificationResult


class BaseVerifier(Protocol):
    name: str
    stages: list[VerificationStage]

    async def verify(self, input: VerificationInput) -> VerificationResult:
        ...
