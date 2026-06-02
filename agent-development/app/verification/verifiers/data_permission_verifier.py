from __future__ import annotations

"""Final-answer data permission verifier."""

import re
from typing import Any

from app.auth.principal import Principal
from app.verification.schemas import VerificationInput, VerificationResult


class DataPermissionVerifier:
    name = "data_permission"
    stages = ["pre_answer"]

    async def verify(self, input: VerificationInput) -> VerificationResult:
        principal = self._principal(input.principal)
        answer = input.answer or ""
        if not answer:
            return VerificationResult(passed=True, stage=input.stage, verifier_name=self.name)

        sanitized = answer
        redactions: list[dict[str, Any]] = []
        if principal is None or "policy.sensitive.read" not in set(principal.data_permissions):
            patterns = [
                ("phone_number", r"(?<!\d)1[3-9]\d{9}(?!\d)", "***PHONE***"),
                ("id_card", r"(?<!\d)\d{17}[\dXx](?!\d)", "***ID_CARD***"),
                ("bank_card", r"(?<!\d)\d{16,19}(?!\d)", "***BANK_CARD***"),
            ]
            for category, pattern, replacement in patterns:
                if re.search(pattern, sanitized):
                    sanitized = re.sub(pattern, replacement, sanitized)
                    redactions.append({"category": category, "reason": "missing_sensitive_data_permission"})

        if sanitized != answer:
            return VerificationResult(
                passed=True,
                stage=input.stage,
                verifier_name=self.name,
                severity="warning",
                action="patch",
                code="data_permission_redacted",
                patched_output=sanitized,
                redactions=redactions,
            )
        return VerificationResult(passed=True, stage=input.stage, verifier_name=self.name)

    @staticmethod
    def _principal(value: dict[str, Any] | None) -> Principal | None:
        if not isinstance(value, dict):
            return None
        try:
            return Principal(**value)
        except Exception:
            return None

