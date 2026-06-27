# TASK: Skill-aware Verify-Repair Loop

## 0. 任务定位

本任务建设任务完成度验收与有限修复循环：

```text
原任务子 Agent 执行
→ 收集证据
→ Skill-aware Completion Verifier 验收
→ 如需继续，生成 RepairPlan
→ 回到原 selected_agent + 原 selected_skill_id 继续执行
→ 再次验收
→ 最终进入现有 pre_answer_verify
```

本任务不替换现有 `pre_answer_verify`。Completion Verify 判断“任务是否完成”，现有 Compliance Verify 判断“答案能否外发”。

## 1. 当前实现结论

### 1.1 当前真实主链路

来自 `app/runtime/graph.py`：

```text
route_entry
→ load_session / resume_approved_tool
→ save_user_message
→ query_rewrite
→ intent_recognition
→ build_orchestrator_context
→ select_agent
→ dispatch_agent
→ check_human_approval_required
→ create_approval_request / submit_approval_request / pause_for_approval
→ pre_answer_verify
→ save_assistant_message
→ compress_short_memory
→ finalize_response
```

当前 `dispatch_agent` 后没有任务完成度验收。

### 1.2 当前可复用组件

| 组件 | 文件 | 可复用方式 |
| --- | --- | --- |
| Graph 编排 | `app/runtime/graph.py` | 新增 completion/repair 节点和 route |
| RoutePolicy | `app/runtime/route_policy.py` | 新增 task completion route |
| State authority | `app/runtime/graph_state.py` | 新增字段 owner/kind/persistence |
| Node contracts | `app/runtime/node_contracts.py` | 新增节点契约并修正旧契约漂移 |
| State projector | `app/runtime/state_projector.py` | 投影 selected skill、repair summary、evidence refs |
| SubAgentTask | `app/schemas/subagent.py` | 增加 repair 显式输入 |
| ContextBuilder | `app/runtime/context_builder.py` | repair 模式构建子 Agent 上下文 |
| SkillContextResolver | `app/runtime/context/skill_context_resolver.py` | 支持 pinned skill |
| SkillCatalog/Loader | `app/skills/catalog.py`, `app/skills/loader.py` | 按 selected_skill_id 重载完整 Skill |
| ToolCallingRunner | `app/subagents/tool_calling_runner.py` | 继续执行工具循环，不改安全边界 |
| ToolExecutor | `app/tools/executor.py` | 继续做权限、参数、审批、验证和执行 |
| Approval | `app/runtime/handlers/approval_handler.py`, `app/approval/service.py` | repair 中写工具仍走现有审批 |
| Evidence | `app/evidence/` | 保存和引用工具证据 |
| Prompt manifest | `app/prompts/manifest.yaml` | 新增 task completion verifier scene |

### 1.3 当前冲突点

1. `selected_skill_id` 当前藏在 `subagent_result`，但 Repair pinning 需要把它作为受控运行字段。
2. `tests/test_graph_state_authority.py` 当前明确要求顶层 state 不出现 `selected_skill_id`。本任务需要重新定义：`selected_skill_id` 不再是 cache，而是 repair 控制字段。
3. `node_contracts.py` 当前 `intent_recognition` outputs 里仍包含 `entities`，但真实节点已不更新实体。Phase 1 应同步修正。
4. 当前 Approval resume state 已保存 selected skill 信息，但 repair history 和 completion result 尚未进入 resume。

## 2. 总体目标

1. 新增独立 task completion verification schema 和 service。
2. Verifier 读取完整 `SKILL.md`，但不执行工具。
3. Verifier 输出结构化 `RepairPlan`。
4. Repair 必须回到原 `selected_agent` 和原 `selected_skill_id`。
5. Repair 是继续执行，不是从头重跑。
6. Repair 中所有工具调用继续经过 `ToolExecutor` 和审批链。
7. 审批 pending 时不进入 Completion Verify。
8. 最终回答仍必须经过现有 `pre_answer_verify`。
9. 修复轮次有限，默认 `max_repair_rounds=2`。
10. 大字段通过 Evidence ID 或摘要引用，不写入 checkpoint。

## 3. 禁止事项

- 不新增 TaskContract。
- 不让 Verifier 执行业务工具。
- 不让 Verifier 绕过 ToolExecutor。
- 不让 Repair 重新选择 Agent。
- 不让 Repair 重新选择 Skill。
- 不把 Completion Verify 和 Compliance Verify 合并。
- 不让审批 pending 答案进入 Completion Verify。
- 不把完整 Skill 文本写入 Graph State 或 checkpoint。
- 不把完整敏感工具结果写入 checkpoint。
- 不无限 Repair。

## 4. 目标数据模型

### 4.1 新增文件

```text
app/verification/task_completion/schemas.py
```

### 4.2 主要模型

```text
TaskCompletionStatus = PASS | CONTINUE | NEED_USER | HUMAN_HANDOFF | FAILED

RepairPlan:
  reason
  completed_items
  missing_items
  next_steps
  do_not_repeat
  reuse_evidence_ids
  expected_new_evidence
  target_agent
  selected_skill_id
  confidence
  fingerprint

TaskCompletionVerificationResult:
  status
  completed
  summary
  completed_items
  missing_items
  repair_plan
  confidence
  reasoning_summary
  evidence_ids
  verifier_name
  llm_status
  fallback_reason

VerificationEvidence:
  evidence_id
  source_type
  source_name
  summary
  status
  tool_name
  tool_arguments_summary
  result_summary
  metadata
```

### 4.3 LLM 输出 schema

新增到 `app/llm/output_schemas.py`：

```text
TaskCompletionLLMOutput
```

严格禁止 extra 字段。解析失败进入格式修复或 fail closed。

## 5. Graph State 设计

### 5.1 新增字段

| 字段 | owner | source | kind | persistence |
| --- | --- | --- | --- | --- |
| `selected_skill_id` | `skill_pin` | `dispatch_agent / dispatch_repair_agent` | `checkpoint` | `checkpoint_snapshot` |
| `selected_skill_version` | `skill_pin` | `collect_verification_evidence` | `checkpoint` | `checkpoint_snapshot` |
| `task_completion_verification_result` | `completion_verification` | `verify_task_completion` | `runtime` | `none` |
| `verification_evidence` | `completion_evidence` | `collect_verification_evidence` | `runtime` | `none` |
| `repair_plan` | `repair_control` | `verify_task_completion` | `checkpoint` | `checkpoint_snapshot` |
| `repair_round` | `repair_control` | `build_repair_task` | `checkpoint` | `checkpoint_snapshot` |
| `repair_history` | `repair_audit` | `verify_task_completion` | `resume` | `resume_state` |
| `last_repair_fingerprint` | `repair_guard` | `verify_task_completion` | `checkpoint` | `checkpoint_snapshot` |
| `repair_no_progress_count` | `repair_guard` | `verify_task_completion` | `checkpoint` | `checkpoint_snapshot` |
| `execution_mode` | `execution_control` | `dispatch_agent / dispatch_repair_agent` | `checkpoint` | `checkpoint_snapshot` |
| `original_subagent_result` | `repair_audit` | `dispatch_agent` | `runtime` | `none` |
| `previous_subagent_results` | `repair_audit` | `dispatch_repair_agent` | `runtime` | `none` |

### 5.2 投影原则

`CheckpointSnapshot` 只保存：

```text
selected_skill_id
selected_skill_version
repair_round
repair_plan summary
task_completion status/summary/evidence_ids
tool_log_refs
evidence_refs
```

不保存：

```text
完整 Skill 文本
完整 verifier prompt
完整 tool result
pending_messages
pending_tools
完整 previous_subagent_results
```

`AgentResumeState` 需要保存：

```text
selected_skill_id
execution_mode
repair_round
repair_plan
repair_history
last_repair_fingerprint
repair_no_progress_count
```

用于审批恢复后继续 completion verify/repair。

## 6. Phase 0：现状审查与设计确认

### 目标

确认当前主图、Verification、Approval、SubAgent、Skill、Tool 和 Eval 的真实边界。

### 为什么做

Verify-Repair 会跨 Graph、SubAgent、Approval、Evidence、Checkpoint 和 Eval 多个层面，必须先明确当前事实，避免把目标架构误写成已实现能力。

### 修改文件

无生产代码修改。仅确认：

```text
design/VERIFY_REPAIR_EVAL_ARCHITECTURE.md
tasks/TASK_VERIFY_REPAIR_LOOP.md
tasks/TASK_AGENT_BEHAVIOR_EVAL.md
```

### 新增文件

本阶段已新增上面三个文档。

### 主要类或函数

不新增运行时代码。

### 输入

当前源码和测试。

### 输出

设计确认结论、风险清单、分阶段文件变更清单。

### 状态变化

无。

### 异常路径

发现源码与文档不一致时，以源码为准，并在文档中记录。

### 测试

不运行生产测试，文档阶段可执行：

```text
rg -n "TaskContract|TaskAcceptanceCriteria" design tasks
```

确认未引入 TaskContract 设计。

### 验收标准

- 三个文档存在。
- 明确写出当前无 completion verify。
- 明确写出当前 approval 不是 LangGraph interrupt。
- 明确写出现有 Prompt Eval 不等于 Agent Eval。

### 依赖关系

无。

## 7. Phase 1：Schema 与状态模型

### 目标

新增 completion verification schema、repair schema、配置项和 Graph State 字段，但不接主图。

### 为什么做

先建立稳定协议和状态治理，避免后续节点通过 metadata 临时传递 repair 信息。

### 修改文件

```text
app/config/settings.py
app/runtime/graph_state.py
app/runtime/state_contracts.py
app/runtime/state_projector.py
app/runtime/node_contracts.py
app/session/message_metadata_sanitizer.py
app/llm/output_schemas.py
```

### 新增文件

```text
app/verification/task_completion/__init__.py
app/verification/task_completion/schemas.py
tests/test_task_completion_verifier_schema.py
tests/test_graph_state_authority.py
tests/test_node_contracts.py
tests/test_checkpoint_projection.py
```

### 主要类或函数

```text
TaskCompletionStatus
RepairPlan
TaskCompletionVerificationResult
VerificationEvidence
TaskCompletionLLMOutput
project_checkpoint_snapshot()
project_approval_resume_state()
```

### 输入

- `subagent_result`
- `selected_agent`
- `request_id`
- `trace_id`
- `entities`
- `approval_resume` state

### 输出

- 新 schema 可被 Pydantic 严格校验。
- Graph State authority 覆盖新增字段。
- Checkpoint 和 Resume projector 可输出安全摘要。

### 状态变化

新增受控字段，特别是：

```text
selected_skill_id
execution_mode
repair_round
repair_plan
repair_history
task_completion_verification_result
verification_evidence
```

### 异常路径

- `RepairPlan.target_agent` 为空或不等于原 Agent：schema 或 sanitizer 拒绝。
- `RepairPlan.selected_skill_id` 为空或不等于原 Skill：schema 或 sanitizer 拒绝。
- `confidence` 不在 0～1：schema 拒绝。

### 测试

新增：

```text
tests/test_task_completion_verifier_schema.py
tests/test_checkpoint_projection.py
tests/test_graph_state_authority.py
tests/test_node_contracts.py
```

必须覆盖：

1. RepairPlan 必填字段和非法 confidence。
2. TaskCompletionVerificationResult 不允许 extra 字段。
3. `selected_skill_id` 顶层字段被 authority 表覆盖。
4. checkpoint 不保存完整 verification_evidence 大字段。
5. resume state 保留 repair 继续执行所需字段。
6. 修正 `intent_recognition` contract 不再输出 `entities` 的漂移。

### 验收标准

- 不接主图时现有业务流程不变。
- 新 schema 单测通过。
- `test_graph_state_authority.py` 反映新语义：`selected_skill_id` 是 repair 控制字段，不是 cache。

### 依赖关系

依赖 Phase 0 设计确认。

## 8. Phase 2：Skill-aware Verifier

### 目标

实现 Skill-aware task completion verifier：按 `selected_skill_id` 重新加载完整 Skill，组装上下文，调用 LLM，严格解析输出，非法输出降级。

### 为什么做

任务完成度判断必须以用户目标、选中 Skill SOP、工具证据和业务状态证据为共同依据，不能只看子 Agent 回答。

### 修改文件

```text
app/prompts/manifest.yaml
app/prompts/manifest.py
app/llm/output_schemas.py
app/bootstrap/container.py
```

### 新增文件

```text
app/prompts/task_completion_verifier/system.md
app/prompts/task_completion_verifier/user.md
app/verification/task_completion/service.py
app/verification/task_completion/llm_verifier.py
app/verification/task_completion/repair_plan_sanitizer.py
tests/test_task_completion_verifier.py
tests/test_skill_aware_verification.py
```

### 主要类或函数

```text
TaskCompletionVerifierService
SkillAwareLLMTaskCompletionVerifier
RepairPlanSanitizer
verify(context) -> TaskCompletionVerificationResult
```

### 输入

```text
original_query
rewritten_query
entities
selected_agent
selected_skill_id
full_skill_content
subagent answer
tool call summaries
evidence summaries
runner stopped_reason
repair_history
business_state_evidence
```

### 输出

```text
TaskCompletionVerificationResult
```

### 状态变化

本阶段不接 Graph；只返回对象。

### 异常路径

1. `selected_skill_id` 为空：返回 `HUMAN_HANDOFF` 或 `FAILED`，不能 PASS。
2. Skill 不存在：返回 `HUMAN_HANDOFF`。
3. LLM provider 异常：返回 `HUMAN_HANDOFF`，`fallback_reason=llm_provider_error`。
4. 第一次 JSON 解析失败：发起一次格式修复。
5. 第二次仍失败：`HUMAN_HANDOFF`。
6. LLM 输出换 Agent/Skill：sanitizer 拒绝，`HUMAN_HANDOFF`。
7. 低置信度：`HUMAN_HANDOFF` 或 `NEED_USER`。

### 测试

新增：

```text
tests/test_task_completion_verifier.py
tests/test_skill_aware_verification.py
tests/test_llm_strict_schema.py
tests/test_prompt_manifest.py
tests/test_prompt_templates.py
```

覆盖：

1. Verifier prompt 包含完整 Skill SOP。
2. Verifier prompt 不包含未选中 Skill。
3. PASS 需要证据支持。
4. CONTINUE 生成合法 RepairPlan。
5. LLM 输出非法 JSON 时格式修复一次。
6. 第二次非法输出 fail closed。
7. RepairPlan 换 Agent 被拒绝。
8. RepairPlan 换 Skill 被拒绝。
9. Verifier 不接收 tools，不调用 ToolExecutor。

### 验收标准

- 新 prompt scene 通过 manifest 校验。
- Verifier 单测均使用 Fake LLM。
- 不修改现有 `VerificationService` 的合规语义。

### 依赖关系

依赖 Phase 1 schema。

## 9. Phase 3：Evidence Collector 与一个 StateProbe

### 目标

实现 `VerificationEvidenceCollector` 和一个代表性只读 `BusinessStateProbe`。

### 为什么做

Verifier 不能直接执行工具；写操作或异步状态变更不能只相信子 Agent 说成功。需要确定性代码采集只读状态证据后交给 Verifier。

### 修改文件

```text
app/bootstrap/container.py
app/evidence/schemas.py
app/evidence/store.py
```

### 新增文件

```text
app/verification/task_completion/evidence_collector.py
app/verification/task_completion/state_probes/__init__.py
app/verification/task_completion/state_probes/base.py
app/verification/task_completion/state_probes/endo_aftercare.py
tests/test_verification_evidence_collector.py
tests/test_business_state_probe.py
```

### 主要类或函数

```text
VerificationEvidenceCollector.collect(state) -> list[VerificationEvidence]
BusinessStateProbe.supports(context) -> bool
BusinessStateProbe.collect(context) -> list[VerificationEvidence]
EndoAftercareStateProbe
```

### 输入

```text
AgentGraphState
SubAgentResult
EvidenceStore
ToolExecutionLogStore
SkillCatalog
entities
selected_skill_id
repair_history
```

### 输出

```text
verification_evidence: list[VerificationEvidence]
selected_skill_version or skill_hash
evidence_ids
```

### 状态变化

Graph 尚未接入时只返回对象；Phase 5 接入后写入：

```text
verification_evidence
selected_skill_version
```

### 异常路径

- EvidenceStore 查询失败：返回 `status=unavailable` 的 system evidence，不抛出阻断异常。
- StateProbe 不支持当前 Skill：跳过。
- StateProbe 支持但只读接口失败：返回 `status=failed/unavailable`，不得视为任务完成。
- 发现敏感字段：只保留摘要和 redaction metadata。

### 测试

新增：

```text
tests/test_verification_evidence_collector.py
tests/test_business_state_probe.py
tests/test_evidence_store.py
tests/test_tool_execution_pipeline.py
```

覆盖：

1. 能从 `subagent_result.tool_calls` 生成安全摘要。
2. 能从 EvidenceStore 读取 Evidence refs。
3. 不把完整工具 result 写入 verification_evidence。
4. EndoAftercareStateProbe 支持对应 Skill。
5. Probe 失败返回 evidence-unavailable。
6. 写操作 success 但状态仍旧时，collector 能提供不一致证据。

### 验收标准

- 至少一个业务场景能采集只读状态证据。
- Collector 不调用写工具。
- Collector 不依赖 LLM。

### 依赖关系

依赖 Phase 1 schema。

## 10. Phase 4：Repair Task 与原 Agent 续跑

### 目标

实现 Repair Task 协议、Skill pinning、RepairPlan 注入、同 Agent/Skill 续跑。

### 为什么做

Repair 不是“再试一次”，而是在 Verifier 指出缺失项后继续完成未完成步骤，并避免重复成功步骤。

### 修改文件

```text
app/schemas/subagent.py
app/schemas/runtime.py
app/agents/task_assembler.py
app/runtime/context_builder.py
app/runtime/context/skill_context_resolver.py
app/subagents/base.py
app/prompts/subagent_reasoning/system.md
app/prompts/subagent_reasoning/user.md
```

### 新增文件

```text
app/agents/repair_task_builder.py
tests/test_repair_task_builder.py
tests/test_repair_skill_pinning.py
```

### 主要类或函数

```text
RepairTaskBuilder.build()
SubAgentTask.execution_mode
SubAgentTask.pinned_skill_id
SubAgentTask.repair_plan
SkillContextResolver.resolve_pinned_skill()
BaseSubAgent.build_messages(... repair context ...)
```

### 输入

```text
original SubAgentTask
parent OrchestratorContext
selected_agent
selected_skill_id
RepairPlan
previous answer
previous evidence refs
previous tool call refs
repair_round
```

### 输出

```text
SubAgentTask(execution_mode="repair", pinned_skill_id=...)
SubAgentContext with selected skill loaded
SubAgentResult from same agent/tool loop
```

### 状态变化

本阶段可通过独立 service 测试，不接主图。后续 Phase 5 写入：

```text
execution_mode=repair
repair_round += 1
previous_subagent_results append summary
```

### 异常路径

- `RepairPlan.target_agent != selected_agent`：拒绝。
- `RepairPlan.selected_skill_id != selected_skill_id`：拒绝。
- pinned skill 不在 AgentCard.skills：拒绝。
- pinned skill disabled：拒绝。
- repair_round 超限：不构建 task。
- do_not_repeat 与 next_steps 冲突：返回 handoff 或 failed。

### 测试

新增：

```text
tests/test_repair_task_builder.py
tests/test_repair_skill_pinning.py
tests/test_skill_context_builder.py
tests/test_tool_calling_runner.py
```

覆盖：

1. repair task 固定原 Agent。
2. repair task 固定原 Skill。
3. repair 模式跳过自由 SkillSelector。
4. pinned skill 加载完整 Skill 正文。
5. repair prompt 包含缺失项、next_steps、do_not_repeat。
6. repair prompt 不包含完整原始工具 JSON。
7. pinned skill 无效时不 fallback 到其他 Skill。
8. repair 中写工具仍返回 approval required。

### 验收标准

- Repair 不重新选择 Agent。
- Repair 不重新选择 Skill。
- Repair 仍通过 BaseSubAgent 和 ToolCallingRunner。
- 现有 no-skill 行为不被破坏。

### 依赖关系

依赖 Phase 1 schema 和 Phase 2 RepairPlan。

## 11. Phase 5：接入 MainGraph

### 目标

把 Completion Verify 和 Repair Loop 接入主图，并正确兼容审批 pending 和审批 callback resume。

### 为什么做

只有接入主图后，完整链路才能做到：

```text
Agent执行 -> 验收 -> 修复 -> 再验收 -> 最终合规
```

### 修改文件

```text
app/runtime/graph.py
app/runtime/route_policy.py
app/runtime/node_contracts.py
app/runtime/graph_state.py
app/runtime/state_projector.py
app/runtime/handlers/approval_handler.py
app/runtime/handlers/message_commit_handler.py
app/session/message_metadata_sanitizer.py
app/bootstrap/container.py
app/config/settings.py
```

### 新增文件

```text
app/runtime/handlers/task_completion_handler.py
tests/test_verify_repair_loop.py
tests/test_verify_repair_approval_flow.py
tests/test_verify_repair_no_progress.py
tests/test_verify_repair_max_rounds.py
```

### 主要类或函数

```text
TaskCompletionGraphHandler.collect_verification_evidence()
TaskCompletionGraphHandler.verify_task_completion()
TaskCompletionGraphHandler.build_repair_task()
TaskCompletionGraphHandler.dispatch_repair_agent()
RoutePolicy.route_task_completion()
AgentGraphFactory.collect_verification_evidence()
AgentGraphFactory.verify_task_completion()
AgentGraphFactory.build_repair_task()
AgentGraphFactory.dispatch_repair_agent()
AgentGraphFactory.build_verification_clarification()
AgentGraphFactory.build_handoff_answer()
```

### 输入

```text
state after dispatch_agent
state after resume_approved_tool
approval_required flag
repair_plan
repair_round
task_completion_verification_result
```

### 输出

```text
verification_evidence
task_completion_verification_result
repair_plan
answer
subagent_result
approval_required
graph_path
```

### 状态变化

Graph 目标边：

```text
dispatch_agent -> check_human_approval_required
resume_approved_tool -> check_human_approval_required
check_human_approval_required.required -> create_approval_request
check_human_approval_required.not_required -> collect_verification_evidence
collect_verification_evidence -> verify_task_completion
verify_task_completion.PASS -> pre_answer_verify
verify_task_completion.CONTINUE -> build_repair_task
build_repair_task -> dispatch_repair_agent
dispatch_repair_agent -> check_human_approval_required
verify_task_completion.NEED_USER -> build_verification_clarification -> pre_answer_verify
verify_task_completion.HUMAN_HANDOFF -> build_handoff_answer -> pre_answer_verify
verify_task_completion.FAILED -> fallback_answer
pause_for_approval -> pre_answer_verify
```

### 异常路径

- `approval_required=True`：不执行 Completion Verify。
- `manual_intervention_required=True`：不执行 Repair，进入 handoff/final compliance。
- `TaskCompletionVerifier` 不可用且配置要求启用：`HUMAN_HANDOFF`。
- `CONTINUE` 但 repair_round 达上限：`HUMAN_HANDOFF`。
- 无新增 Evidence：增加 `repair_no_progress_count`，达到阈值后 `HUMAN_HANDOFF`。
- 重复工具/参数：阻断 repair 或转 handoff。
- Repair 中产生写工具：继续现有审批链。

### 测试

新增：

```text
tests/test_verify_repair_loop.py
tests/test_verify_repair_approval_flow.py
tests/test_verify_repair_no_progress.py
tests/test_verify_repair_max_rounds.py
```

回归：

```text
tests/test_langgraph_flow.py
tests/test_final_compliance_check.py
tests/test_approval_full_flow.py
tests/test_approval_chain_resume.py
tests/test_tool_calling_runner.py
tests/test_skill_context_builder.py
tests/test_skill_selection_end_to_end.py
tests/test_graph_state_authority.py
tests/test_node_contracts.py
tests/test_checkpoint_projection.py
```

覆盖：

1. 首轮 PASS 直接进入 `pre_answer_verify`。
2. 首轮 CONTINUE 构建 repair task。
3. repair 后 PASS。
4. repair 仍是同 Agent。
5. repair 仍是同 Skill。
6. pending approval 不进入 Completion Verify。
7. approval callback 后进入 Completion Verify。
8. repair 中写工具触发审批。
9. max repair rounds 生效。
10. no progress guard 生效。
11. Completion PASS 但 Compliance block 仍被最终合规拦截。

### 验收标准

- 所有新增节点出现在 `node_contracts.py`。
- 所有新增 state 字段出现在 `GRAPH_STATE_FIELD_AUTHORITY`。
- `pause_for_approval -> pre_answer_verify` 保持。
- `dispatch_agent -> check_human_approval_required` 保持。
- Completion Verify 不绕过 Approval。
- `ENABLE_TASK_COMPLETION_VERIFY=false` 时可回退当前主链路。

### 依赖关系

依赖 Phase 1～4。

## 12. 配置项

新增到 `app/config/settings.py`：

```text
ENABLE_TASK_COMPLETION_VERIFY=true
TASK_COMPLETION_MAX_REPAIR_ROUNDS=2
TASK_COMPLETION_MIN_VERIFIER_CONFIDENCE=0.55
TASK_COMPLETION_ENABLE_LLM=true
TASK_COMPLETION_ENABLE_STATE_PROBES=true
TASK_COMPLETION_FAIL_CLOSED=true
```

已确认默认策略：

```text
本地和测试环境默认开启 ENABLE_TASK_COMPLETION_VERIFY=true
Verifier 连续非法输出统一转 HUMAN_HANDOFF
第一阶段 StateProbe 使用 troubleshooting_agent.endo_completion_aftercare
```

生产建议：

```text
ENABLE_TASK_COMPLETION_VERIFY=true
TASK_COMPLETION_FAIL_CLOSED=true
```

灰度期可：

```text
ENABLE_TASK_COMPLETION_VERIFY=false
```

## 13. 设计细节：Completion Verify 输入

Verifier context 建议字段：

```text
request_id
trace_id
session_key
original_query
rewritten_query
entities
selected_agent
selected_skill_id
skill_content
skill_version_or_hash
subagent_answer
tool_call_summaries
evidence_summaries
runner_stopped_reason
repair_round
repair_history
business_state_evidence
approval_status
```

不包含：

```text
完整 pending_messages
完整 pending_tools
完整 raw tool result
完整 user auth context
完整 Skill metadata 以外的大对象
```

## 14. 设计细节：RepairPlan Sanitizer

Sanitizer 规则：

1. `target_agent` 必须等于 state.selected_agent。
2. `selected_skill_id` 必须等于 state.selected_skill_id。
3. `CONTINUE` 必须有 `next_steps`。
4. `do_not_repeat` 不能和 `next_steps` 完全冲突。
5. 高风险写工具如果已经成功且没有新证据，不允许重复。
6. `confidence < min_confidence` 时改为 `HUMAN_HANDOFF`。
7. `expected_new_evidence` 为空时降低 confidence 或要求 NEED_USER。

## 15. 验收标准总表

| 验收点 | 标准 |
| --- | --- |
| 不引入 TaskContract | repo 中不新增 `TaskContract` / `TaskAcceptanceCriteria` |
| Verifier 不执行工具 | Verifier service 不依赖 ToolExecutor |
| Repair 同 Agent | 所有 repair case `target_agent == selected_agent` |
| Repair 同 Skill | 所有 repair case `pinned_skill_id == selected_skill_id` |
| pending 不验收 | `pause_for_approval` 路径不出现 `verify_task_completion` |
| 审批恢复后验收 | callback 完成后无下一审批时进入 completion verify |
| 修复有限 | 不超过 `TASK_COMPLETION_MAX_REPAIR_ROUNDS` |
| 无进展保护 | 重复 plan/无新增 evidence 会终止 |
| 最终合规仍执行 | 所有出口仍过 `pre_answer_verify` |
| 大字段不入库 | checkpoint/resume/message metadata 不保存完整 raw tool result |

## 16. 回滚方案

1. 通过 `ENABLE_TASK_COMPLETION_VERIFY=false` 回退到当前主链路。
2. 保留新增 schema 和 service，不参与主图时无运行影响。
3. 如 verifier 误判严重，先关闭 LLM verifier，只保留 evidence collector 日志和 Eval。
4. Agent Eval 与生产主链路解耦，不影响运行。

## 17. 已确认决策与后续执行约束

1. `selected_skill_id` 升级为顶层 Graph State 控制字段。
   - 后续实现必须更新 `AgentGraphState`、`GRAPH_STATE_FIELD_AUTHORITY`、`node_contracts.py`、`state_projector.py`、`CheckpointSnapshot`、`AgentResumeState` 和相关测试。
   - 旧的“顶层不能出现 selected_skill_id”测试语义需要调整为“不能出现 selected_skill_metadata / skill_selection_score / skill_selection_reason 等 cache 字段”。

2. 第一阶段 `BusinessStateProbe` 选择 `troubleshooting_agent.endo_completion_aftercare`。
   - 必须围绕 `query_endo_task_record` 和保全 9/10/11 节点状态设计代表性只读状态证据。

3. Verifier 连续非法输出时统一转 `HUMAN_HANDOFF`。
   - 第一次非法输出可做一次严格格式修复。
   - 第二次仍非法时不得进入 Repair，不得返回 PASS。

4. Completion verification 摘要写入 MessageStore metadata。
   - 只写轻量字段：`task_completion_status`、`repair_round`、`task_completion_summary`、`task_completion_evidence_ids`。
   - 不写完整 verifier prompt、完整 LLM 输出、完整 Skill 文本、完整 raw tool result。

5. `ENABLE_TASK_COMPLETION_VERIFY` 在本地和测试环境默认开启。
   - 测试应覆盖开启后的完整主链路。
   - 仍需保留关闭开关，用于灰度和回滚。
