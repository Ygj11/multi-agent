from __future__ import annotations

"""Main-agent final outbound compliance check."""

import re

from app.llm.base import LLMProvider
from app.schemas.compliance import ComplianceViolation, FinalComplianceResult


class FinalComplianceChecker:
    """Rule-based outbound sanitizer used before saving/returning answers."""

    _fallback = "当前回复包含不适合直接外发的信息，我已拦截原始内容。可以继续提供业务现象、request_id 或错误码，我会在脱敏后重新分析。"

    def __init__(self, llm_provider: LLMProvider | None = None) -> None:
        self.llm_provider = llm_provider

    async def check(self, answer: str) -> FinalComplianceResult:
        if self.llm_provider is not None:
            await self.llm_provider.chat(
                messages=[
                    {"role": "system", "content": "Check final outbound compliance. Do not use tools."},
                    {"role": "user", "content": answer or ""},
                ],
                tools=None,
                scene="final_compliance",
            )
        sanitized = answer or ""
        violations: list[ComplianceViolation] = []

        patterns = [
            ("phone", "high", r"(?<!\d)1[3-9]\d{9}(?!\d)", "***PHONE***"),
            ("id_card", "high", r"(?<!\d)\d{17}[\dXx](?!\d)", "***ID_CARD***"),
            ("bank_card", "high", r"(?<!\d)\d{16,19}(?!\d)", "***BANK_CARD***"),
            ("credential", "high", r"(?i)\b(secret|token|password|api[_-]?key|authorization)\s*[:=]\s*\S+", r"\1=***"),
        ]
        for category, severity, pattern, replacement in patterns:
            if re.search(pattern, sanitized):
                violations.append(
                    ComplianceViolation(category=category, severity=severity, message=f"{category} was redacted")
                )
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
            violations.append(
                ComplianceViolation(
                    category="internal_log_field",
                    severity="medium",
                    message="Internal log fields were removed from outbound answer",
                )
            )
            for field in internal_fields:
                sanitized = re.sub(rf"{field}\s*=\s*[^，。,\s]+", f"{field}=***", sanitized)
                sanitized = re.sub(rf"'{field}'\s*:\s*[^,}}]+", f"'{field}': '***'", sanitized)
                sanitized = re.sub(rf'"{field}"\s*:\s*[^,}}]+', f'"{field}": "***"', sanitized)

        if any(keyword in sanitized for keyword in ("病史", "医疗记录", "诊断", "医保", "健康告知")):
            violations.append(
                ComplianceViolation(
                    category="health_privacy",
                    severity="medium",
                    message="Health privacy content requires minimum necessary disclosure",
                )
            )

        raw_tool_markers = ("RAW_TOOL_RESULT", "raw_tool_result", "tool_result_json", "工具原始返回")
        raw_tool_blocked = any(marker in sanitized for marker in raw_tool_markers)
        if raw_tool_blocked:
            violations.append(
                ComplianceViolation(
                    category="raw_tool_output",
                    severity="high",
                    message="Raw tool output must not be exposed",
                )
            )

        risk_level = "high" if any(item.severity == "high" for item in violations) else "medium" if violations else "low"
        return FinalComplianceResult(
            passed=not raw_tool_blocked,
            sanitized_answer=sanitized,
            violations=violations,
            risk_level=risk_level,
            retry_required=raw_tool_blocked,
            fallback_answer=self._fallback,
        )
