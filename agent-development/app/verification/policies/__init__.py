"""Verification 依赖的策略配置。

这里放的是 verifier 运行时读取的 policy / catalog / YAML loader，不放真正执行
校验的 verifier。当前关系是：

field_visibility_policy.yaml
        ↓
FieldVisibilityPolicy
        ↓
DataPermissionVerifier
        ↓
VerificationService(pre_answer)

因此 `FieldVisibilityPolicy` 属于 DataPermissionVerifier 的策略依赖，而不是
`verifiers/` 下那种拥有 stages 和 verify() 的可执行校验器。
"""
