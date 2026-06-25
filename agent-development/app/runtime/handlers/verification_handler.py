from __future__ import annotations

"""Pre-answer verification handler for the main graph."""

from typing import Any

from app.auth.principal import principal_dict_from_auth_context
from app.verification.schemas import VerificationInput, VerificationResult
from app.verification.service import VerificationService


class VerificationHandler:
    """在主 Graph 返回用户前统一执行 pre_answer verification。

    澄清话术、审批等待话术和普通业务答案都会经过这里。若 verifier 返回 patch
    则替换答案；block/manual 会使用固定安全话术，当前不做复杂语义重写。
    """

    def __init__(self, verification_service: VerificationService | None = None) -> None:
        self.verification_service = verification_service

    async def pre_answer_verify(self, state: dict[str, Any]) -> dict[str, Any]:
        answer = state.get("answer", "")
        if self.verification_service is not None:
            verification = await self.verification_service.verify(
                VerificationInput(
                    stage="pre_answer",
                    request_id=state.get("request_id"),
                    trace_id=state.get("trace_id"),
                    session_key=state.get("session_key"),
                    auth_context=state.get("auth_context") or {},
                    principal=principal_dict_from_auth_context(state.get("auth_context")),
                    agent_name=state.get("selected_agent"),
                    answer=answer,
                    evidence=(state.get("subagent_result") or {}).get("evidence", [])
                    if isinstance(state.get("subagent_result"), dict)
                    else [],
                )
            )
        else:
            verification = VerificationResult(
                passed=True,
                stage="pre_answer",
                verifier_name="verification_service_not_configured",
                action="allow",
            )

        if verification.action == "patch" and isinstance(verification.patched_output, str):
            answer = verification.patched_output
        elif verification.action in {"block", "manual"}:
            answer = "当前回复未通过最终验证，已拦截可能不适合外发的内容。"

        pre_answer_result = verification.model_dump()
        return {
            "pre_answer_verification_result": pre_answer_result,
            "answer": answer,
        }

    @staticmethod
    def route(state: dict[str, Any]) -> str:
        result = VerificationResult(**state["pre_answer_verification_result"])
        if result.action in {"allow", "patch"} and result.passed:
            return "passed"
        if result.action == "retry" and state.get("retry_count", 0) < 1:
            return "retry"
        return "fallback"
