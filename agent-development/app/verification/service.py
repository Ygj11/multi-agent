from __future__ import annotations

"""Composable verification service."""

from app.verification.base import BaseVerifier
from app.verification.schemas import VerificationInput, VerificationResult


class VerificationService:
    def __init__(self, verifiers: list[BaseVerifier] | None = None) -> None:
        self.verifiers = verifiers or []

    def register(self, verifier: BaseVerifier) -> None:
        self.verifiers.append(verifier)

    async def verify_all(self, input: VerificationInput) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        for verifier in self.verifiers:
            if input.stage not in verifier.stages:
                continue
            try:
                results.append(await verifier.verify(input))
            except Exception as exc:  # fail closed
                results.append(
                    VerificationResult(
                        passed=False,
                        stage=input.stage,
                        verifier_name=getattr(verifier, "name", verifier.__class__.__name__),
                        severity="blocking",
                        action="block",
                        code="verifier_exception",
                        reason=str(exc),
                    )
                )
        return results

    def aggregate(self, input: VerificationInput, results: list[VerificationResult]) -> VerificationResult:
        if not results:
            return VerificationResult(passed=True, stage=input.stage, verifier_name="aggregate")
        for result in results:
            if result.action in {"block", "manual"} or result.severity == "blocking":
                return result
        patched = None
        redactions: list[dict] = []
        for result in results:
            redactions.extend(result.redactions)
            if result.action == "patch" and result.patched_output is not None:
                patched = result.patched_output
        if patched is not None:
            return VerificationResult(
                passed=True,
                stage=input.stage,
                verifier_name="aggregate",
                action="patch",
                patched_output=patched,
                redactions=redactions,
            )
        return VerificationResult(passed=True, stage=input.stage, verifier_name="aggregate", redactions=redactions)

    async def verify(self, input: VerificationInput) -> VerificationResult:
        return self.aggregate(input, await self.verify_all(input))

