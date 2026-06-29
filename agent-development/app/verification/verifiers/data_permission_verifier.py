from __future__ import annotations

"""最终答案数据权限 verifier。

场景：Graph 的 `pre_answer_verify` 节点在答案返回用户前调用。

职责：
- 读取 FieldVisibilityPolicy；
- 根据 principal.roles / scopes / data_permissions 判断敏感类别是否可见；
- 不可见时按策略脱敏或记录 warning。

它不决定“工具能不能执行”。工具执行权限仍由 ToolExecutor 中的
AuthorizationService / ResourceAccessService 完成。
"""

import re
from typing import Any

from app.auth.principal import Principal
from app.schemas.enums.verification import VerificationAction, VerificationSeverity, VerificationStage
from app.verification.policies.field_visibility_policy import FieldVisibilityPolicy, FieldVisibilityRule
from app.verification.schemas import VerificationInput, VerificationResult


class DataPermissionVerifier:
    """按字段可见性策略过滤最终答案。"""

    name = "data_permission"
    stages = [VerificationStage.PRE_ANSWER]

    def __init__(self, policy: FieldVisibilityPolicy | None = None) -> None:
        self.policy = policy or FieldVisibilityPolicy.load()

    async def verify(self, input: VerificationInput) -> VerificationResult:
        principal = self._principal(input.principal)
        answer = input.answer or ""
        if not answer:
            return VerificationResult(passed=True, stage=input.stage, verifier_name=self.name)

        sanitized = answer
        redactions: list[dict[str, Any]] = []
        for rule in self.policy.redaction_rules():
            if re.search(str(rule.pattern), sanitized) and not self._can_view(principal, rule.category):
                sanitized = self._redact_pattern(
                    sanitized,
                    rule=rule,
                    principal=principal,
                )
                redactions.append({"category": rule.category, "reason": "missing_sensitive_data_permission"})

        for rule in self.policy.keyword_rules():
            if any(keyword in sanitized for keyword in rule.keywords) and not self._can_view(principal, rule.category):
                redactions.append(
                    {
                        "category": rule.category,
                        "reason": "missing_sensitive_data_permission",
                        "message": f"{rule.category} content requires minimum necessary disclosure",
                    }
                )

        if sanitized != answer:
            return VerificationResult(
                passed=True,
                stage=input.stage,
                verifier_name=self.name,
                severity=VerificationSeverity.WARNING,
                action=VerificationAction.PATCH,
                code="data_permission_redacted",
                patched_output=sanitized,
                redactions=redactions,
            )
        return VerificationResult(
            passed=True,
            stage=input.stage,
            verifier_name=self.name,
            severity=VerificationSeverity.WARNING if redactions else VerificationSeverity.INFO,
            redactions=redactions,
        )

    @staticmethod
    def _principal(value: dict[str, Any] | None) -> Principal | None:
        if not isinstance(value, dict):
            return None
        try:
            return Principal(**value)
        except Exception:
            return None

    def _can_view(self, principal: Principal | None, category: str) -> bool:
        if principal is None:
            return False
        granted = set(principal.data_permissions) | set(principal.scopes)
        return self.policy.can_view(category=category, roles=set(principal.roles), permissions=granted)

    def _redact_pattern(
        self,
        text: str,
        *,
        rule: FieldVisibilityRule,
        principal: Principal | None,
    ) -> str:
        if not rule.preserve_if_category_allowed:
            return re.sub(str(rule.pattern), str(rule.mask), text)

        preserved_rule = self.policy.rule(rule.preserve_if_category_allowed)

        def replace(match: re.Match[str]) -> str:
            value = match.group(0)
            if (
                preserved_rule
                and preserved_rule.pattern
                and re.fullmatch(preserved_rule.pattern, value)
                and self._can_view(principal, preserved_rule.category)
            ):
                return value
            return str(rule.mask)

        return re.sub(str(rule.pattern), replace, text)
