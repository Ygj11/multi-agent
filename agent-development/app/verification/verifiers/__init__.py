"""通用 VerificationService 的内置 verifier。

这里的 verifier 都通过 `VerificationService.verify()` 调用，并声明自己支持的
stages。当前已注册的是最终答案外发前的
DataPermissionVerifier 和 ComplianceVerifier。
"""
