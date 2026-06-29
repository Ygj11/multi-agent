"""任务完成度验收与修复循环组件。

这一层是 runtime verify-repair loop，发生在子 Agent 执行后、最终外发验证前。
它判断的是：

- 选中的 Skill SOP 是否已被足够执行；
- 工具结果、EvidenceStore 和状态探针是否能证明任务完成；
- 如果未完成，是否需要 RepairPlan、用户补充信息或人工接管。

它不替代 `app.verification.service.VerificationService`。后者负责 pre_tool /
pre_answer 安全策略；本包负责 task completion 业务完成度。
"""
