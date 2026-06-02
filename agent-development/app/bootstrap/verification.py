from __future__ import annotations

"""Verification dependency bootstrap."""

from app.llm.base import LLMProvider
from app.verification.service import VerificationService
from app.verification.verifiers.compliance_verifier import ComplianceVerifier
from app.verification.verifiers.data_permission_verifier import DataPermissionVerifier


def build_verification_service(llm_provider: LLMProvider) -> VerificationService:
    return VerificationService(
        verifiers=[
            DataPermissionVerifier(),
            ComplianceVerifier(llm_provider=llm_provider),
        ]
    )
