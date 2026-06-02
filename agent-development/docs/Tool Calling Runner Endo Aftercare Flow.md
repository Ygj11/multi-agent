# Tool Calling Runner Endo Aftercare Flow

> 同步说明：当前更完整的端到端 trace 已写入 `docs/Endo Aftercare Full Request Debug Trace.md`。本文件只保留子 Agent 内部 `ToolCallingRunner.run(...) -> LLM + tools loop -> ToolExecutor.execute(...)` 这一段的参考价值。

与当前源码相比，需要注意：

1. 主流程最终出口已经改为 `pre_answer_verify -> VerificationService`，不再是 `final_compliance_check -> FinalComplianceChecker`。
2. 当前真实 `ChatRequest` 不是 `message/session_key`，而是 `tenant_id/channel/user_id/session_id/messages`，`session_key` 由 `RequestAdapter` 生成。
3. 示例请求中，当前规则 `EntityExtractor` 能抽出 `apply_seq=APPLY_POLICY_UPDATE_FAIL` 和 `policy_no=P001`，但静态运行没有抽出 `endorseType=退保`。如果 LLM 没有在 query rewrite / intent 阶段补出 `endorseType`，子 Agent 会在 required entity check 阶段返回 clarification，不会进入 tool loop。
4. 如果实体完整，`query_endo_task_record` 是读工具，会执行；`notice_policy_update` 当前是 `is_write=True`，会触发 `human_approval_required` 和 Graph 审批分支，不会直接执行。
5. 审批通过后，恢复链路通过 `ApprovalService -> AgentOrchestrator.resume_after_approval -> Graph.resume_approved_tool` 回到 Graph，而不是由 ApprovalService 独自接管完整 tool loop。

请以 `docs/Endo Aftercare Full Request Debug Trace.md` 为当前版本的完整、准确链路说明。
