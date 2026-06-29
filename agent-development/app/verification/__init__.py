"""运行时 Verification 边界。

本包包含两类容易混淆但职责不同的校验：

1. 通用 VerificationService
   - 入口：`service.py`
   - Schema：`schemas.py`
   - 内置 verifier：`verifiers/`
   - 主要阶段：`pre_tool`、`pre_answer`
   - 目的：工具执行前策略检查、最终答案外发前合规/数据权限检查。

2. Skill-aware Task Completion Verify-Repair
   - 入口：`task_completion/service.py`
   - Schema：`task_completion/schemas.py`
   - 目的：子 Agent 执行后，结合选中 Skill SOP、工具证据和状态探针判断任务是否完成。

Authorization 不在这里：权限服务位于 `app.auth`，负责确定性判断“谁能不能访问
工具/资源”。Verification 负责“这次工具或答案是否满足执行前/外发前策略”。
"""
