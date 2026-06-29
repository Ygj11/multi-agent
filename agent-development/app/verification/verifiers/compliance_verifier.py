from __future__ import annotations

"""最终答案合规 verifier。

场景：Graph 的 `pre_answer_verify` 节点在答案返回用户前调用。

职责：
- 调用 final_compliance prompt，让 LLM provider 有机会参与外发合规判断；
- 用确定性规则脱敏 credential / token / 内部日志字段；
- 阻断原始工具输出直出，例如 RAW_TOOL_RESULT、tool_result_json。

它不判断用户有没有资源权限；资源和 scope 权限由 AuthorizationService 处理。
"""

import re

from app.llm.base import LLMProvider
from app.prompts.loader import PromptLoader, default_prompt_loader
from app.verification.schemas import VerificationInput, VerificationResult


class ComplianceVerifier:
    """检查最终答案是否可以外发。"""

    name = "compliance"
    stages = ["pre_answer"]

    def __init__(
        self,
        llm_provider: LLMProvider | None = None,
        prompt_loader: PromptLoader | None = None,
    ) -> None:
        self.llm_provider = llm_provider
        self.prompt_loader = prompt_loader or default_prompt_loader

    async def verify(self, input: VerificationInput) -> VerificationResult:
        answer = input.answer or ""
        if self.llm_provider is not None:
            await self.llm_provider.chat(
                messages=[
                    {"role": "system", "content": self.prompt_loader.render("verification/final_compliance_system.md")},
                    {"role": "user", "content": answer},
                ],
                tools=None,
                scene="final_compliance",
                request_id=input.request_id,
                trace_id=input.trace_id,
                session_key=input.session_key,
            )

        sanitized = answer
        redactions: list[dict] = []
        patterns = [
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
