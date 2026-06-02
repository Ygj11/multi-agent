from __future__ import annotations

"""Pre-answer compliance verifier."""

import re

from app.llm.base import LLMProvider
from app.verification.schemas import VerificationInput, VerificationResult


class ComplianceVerifier:
    name = "compliance"
    stages = ["pre_answer"]

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def verify(self, input: VerificationInput) -> VerificationResult:
        answer = input.answer or ""
        if self.llm_provider is not None:
            await self.llm_provider.chat(
                messages=[
                    {"role": "system", "content": "Check final outbound compliance. Do not use tools."},
                    {"role": "user", "content": answer},
                ],
                tools=None,
                scene="final_compliance",
            )

        sanitized = answer
        redactions: list[dict] = []
        patterns = [
            ("phone", "high", r"(?<!\d)1[3-9]\d{9}(?!\d)", "***PHONE***"),
            ("id_card", "high", r"(?<!\d)\d{17}[\dXx](?!\d)", "***ID_CARD***"),
            ("bank_card", "high", r"(?<!\d)\d{16,19}(?!\d)", "***BANK_CARD***"),
            ("credential", "high", r"(?i)\b(secret|token|password|api[_-]?key|authorization)\s*[:=]\s*\S+", r"\1=***"),
        ]
        for category, severity, pattern, replacement in patterns:
            if re.search(pattern, sanitized):
                redactions.append({"category": category, "severity": severity, "message": f"{category} was redacted"})
                sanitized = re.sub(pattern, replacement, sanitized)

        internal_fields = (
            "server_sign",
            "partner_sign",
            "raw_payload",
            "authorization",
            "stack_trace",
            "traceback",
            "base_string_fields",
        )
        if any(field in sanitized for field in internal_fields):
            redactions.append(
                {
                    "category": "internal_log_field",
                    "severity": "medium",
                    "message": "Internal log fields were removed from outbound answer",
                }
            )
            for field in internal_fields:
                sanitized = re.sub(rf"{field}\s*=\s*[^，。；\s]+", f"{field}=***", sanitized)
                sanitized = re.sub(rf"'{field}'\s*:\s*[^,}}]+", f"'{field}': '***'", sanitized)
                sanitized = re.sub(rf'"{field}"\s*:\s*[^,}}]+', f'"{field}": "***"', sanitized)

        if any(keyword in sanitized for keyword in ("病史", "医疗记录", "诊断", "医保", "健康告知")):
            redactions.append(
                {
                    "category": "health_privacy",
                    "severity": "medium",
                    "message": "Health privacy content requires minimum necessary disclosure",
                }
            )

        raw_tool_markers = ("RAW_TOOL_RESULT", "raw_tool_result", "tool_result_json", "工具原始返回")
        raw_tool_blocked = any(marker in sanitized for marker in raw_tool_markers)
        if raw_tool_blocked:
            redactions.append(
                {
                    "category": "raw_tool_output",
                    "severity": "high",
                    "message": "Raw tool output must not be exposed",
                }
            )

        if raw_tool_blocked:
            return VerificationResult(
                passed=False,
                stage=input.stage,
                verifier_name=self.name,
                severity="blocking",
                action="retry",
                code="compliance_violation",
                reason="; ".join(item["message"] for item in redactions),
                patched_output=sanitized,
                redactions=redactions,
            )
        if sanitized != answer:
            return VerificationResult(
                passed=True,
                stage=input.stage,
                verifier_name=self.name,
                severity="warning",
                action="patch",
                patched_output=sanitized,
                redactions=redactions,
            )
        return VerificationResult(
            passed=True,
            stage=input.stage,
            verifier_name=self.name,
            severity="warning" if redactions else "info",
            action="allow",
            redactions=redactions,
        )
