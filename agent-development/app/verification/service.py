from __future__ import annotations

"""可组合的 Verification 服务。

Verification 处理需要可插拔 verifier 的运行时策略检查。当前主路径使用：

- `pre_tool`：工具执行前的可选策略检查；
- `pre_answer`：最终外发前验证，包括合规脱敏/patch。

Authorization 仍然独立且确定性地判断“能不能做”；Verification 判断工具或答案
是否满足外发/执行前策略。当前 patch/block 能力以注册 verifier 的真实行为为准。
"""

from app.verification.base import BaseVerifier
from app.verification.schemas import VerificationInput, VerificationResult


class VerificationService:
    """执行某一阶段的所有 verifier，并聚合最终动作。"""

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
                if result.action == "patch" and isinstance(result.patched_output, str):
                    current_input = current_input.model_copy(update={"answer": result.patched_output})
            except Exception as exc:  # fail closed
                results.append(
                    VerificationResult(
                        passed=False,
                        stage=current_input.stage,
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
