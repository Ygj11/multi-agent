from __future__ import annotations

"""可组合的通用 Verification 服务。

Verification 处理需要可插拔 verifier 的运行时策略检查。当前主路径使用：

- `pre_tool`：工具执行前的可选策略检查；
- `pre_answer`：最终外发前验证，包括合规脱敏/patch。

Authorization 仍然独立且确定性地判断“能不能做”；Verification 判断工具或答案
是否满足外发/执行前策略。当前 patch/block 能力以注册 verifier 的真实行为为准。

这不是 task completion verify-repair loop。任务完成度验收需要读取 Skill SOP、
工具证据和状态探针，因此放在 `app.verification.task_completion`，使用独立 schema。
"""

from app.verification.base import BaseVerifier
from app.schemas.enums.verification import VerificationAction, VerificationSeverity
from app.verification.schemas import VerificationInput, VerificationResult


class VerificationService:
    """执行某一阶段的所有 verifier，并聚合最终动作。

    聚合规则有意保持简单：
    - 任一 verifier 返回 block/manual 或 blocking severity，整体立即阻断；
    - verifier 返回 patch 时，把 patched_output 作为后续 verifier 的输入；
    - 没有 verifier 支持当前 stage 时默认 allow。

    这样可以让 DataPermissionVerifier 先脱敏，ComplianceVerifier 再基于脱敏结果
    检查最终答案，而不是每个节点各自实现一套外发安全逻辑。
    """

    def __init__(self, verifiers: list[BaseVerifier] | None = None) -> None:
        self.verifiers = verifiers or []

    def register(self, verifier: BaseVerifier) -> None:
        self.verifiers.append(verifier)

    async def verify_all(self, input: VerificationInput) -> list[VerificationResult]:
        results: list[VerificationResult] = []
        current_input = input
        for verifier in self.verifiers:
            if current_input.stage not in verifier.stages:
                continue
            try:
                result = await verifier.verify(current_input)
                results.append(result)
                if result.action is VerificationAction.PATCH and isinstance(result.patched_output, str):
                    current_input = current_input.model_copy(update={"answer": result.patched_output})
            except Exception as exc:  # fail closed
                results.append(
                    VerificationResult(
                        passed=False,
                        stage=current_input.stage,
                        verifier_name=getattr(verifier, "name", verifier.__class__.__name__),
                        severity=VerificationSeverity.BLOCKING,
                        action=VerificationAction.BLOCK,
                        code="verifier_exception",
                        reason=str(exc),
                    )
                )
        return results

    def aggregate(self, input: VerificationInput, results: list[VerificationResult]) -> VerificationResult:
        if not results:
            return VerificationResult(passed=True, stage=input.stage, verifier_name="aggregate")
        for result in results:
            if result.action in {VerificationAction.BLOCK, VerificationAction.MANUAL} or result.severity is VerificationSeverity.BLOCKING:
                return result
        patched = None
        redactions: list[dict] = []
        for result in results:
            redactions.extend(result.redactions)
            if result.action is VerificationAction.PATCH and result.patched_output is not None:
                patched = result.patched_output
        if patched is not None:
            return VerificationResult(
                passed=True,
                stage=input.stage,
                verifier_name="aggregate",
                action=VerificationAction.PATCH,
                patched_output=patched,
                redactions=redactions,
            )
        return VerificationResult(passed=True, stage=input.stage, verifier_name="aggregate", redactions=redactions)

    async def verify(self, input: VerificationInput) -> VerificationResult:
        return self.aggregate(input, await self.verify_all(input))
