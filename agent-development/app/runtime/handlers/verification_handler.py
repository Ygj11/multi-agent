from __future__ import annotations

"""Pre-answer verification handler for the main graph."""

from typing import Any

from app.auth.principal import principal_dict_from_auth_context
from app.schemas.enums.verification import VerificationAction, VerificationStage
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
        """
        Graph 生成 answer
        → pre_answer_verify 节点
        → VerificationService
           → DataPermissionVerifier   判断“这个用户能不能看这些字段”，
                app.verification.policies.field_visibility_policy 是
                DataPermissionVerifier 的策略配置模型，不是 verifier。
                读取 policies/field_visibility_policy.yaml
                → 定义哪些字段类别敏感
                → 定义匹配正则
                → 定义无权限时怎么 mask
                → 定义哪些 permission / role 可以看明文
           → ComplianceVerifier    判断“这个答案整体能不能外发”
        → patch/block/allow 后再返回用户
        """
        answer = state.get("answer", "")
        if self.verification_service is not None:
            verification = await self.verification_service.verify(
                VerificationInput(
                    stage=VerificationStage.PRE_ANSWER,
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
                stage=VerificationStage.PRE_ANSWER,
                verifier_name="verification_service_not_configured",
                action=VerificationAction.ALLOW,
            )

        if verification.action is VerificationAction.PATCH and isinstance(verification.patched_output, str):
            answer = verification.patched_output
        elif verification.action in {VerificationAction.BLOCK, VerificationAction.MANUAL}:
            answer = "当前回复未通过最终验证，已拦截可能不适合外发的内容。"

        pre_answer_result = verification.model_dump()
        return {
            "pre_answer_verification_result": pre_answer_result,
            "answer": answer,
        }
