from __future__ import annotations

"""Verification dependency bootstrap.

这里构建的是通用运行时 VerificationService，当前注册两个 pre_answer verifier：

- DataPermissionVerifier：按字段可见性策略做数据权限脱敏；
- ComplianceVerifier：做最终答案合规检查和原始工具输出拦截。

注意它不是 TaskCompletionVerifierService。任务完成度 verify-repair loop 在
`app.verification.task_completion` 下独立装配，因为那套语义关注“Skill SOP 是否
执行完成”，不是“答案能否外发”。
"""

from app.llm.base import LLMProvider
from app.verification.service import VerificationService
from app.verification.verifiers.compliance_verifier import ComplianceVerifier
from app.verification.verifiers.data_permission_verifier import DataPermissionVerifier


def build_verification_service(llm_provider: LLMProvider) -> VerificationService:
    """构建最终外发/工具前策略校验服务。"""
    return VerificationService(
        verifiers=[
            DataPermissionVerifier(),
            ComplianceVerifier(llm_provider=llm_provider),
        ]
    )
