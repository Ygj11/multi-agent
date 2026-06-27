# TASK: 端到端 Agent Behavior Eval

## 0. 任务定位

本任务新增 Agent 行为级 Eval，用于评估完整或足够接近真实的 Agent 主链路：

```text
用户请求
→ Query Rewrite
→ Intent Recognition
→ Agent Selection
→ Skill Selection
→ SubAgent Tool Loop
→ Task Completion Verify
→ Repair
→ 再执行
→ 再 Verify
→ Final Compliance Verify
→ 最终回答
```

现有 `PromptEvalRunner` 必须保留。Agent Eval 是新增能力，不直接替换 Prompt Eval。

## 1. 当前实现审查

### 1.1 现有 Prompt Eval

当前文件：

```text
app/evaluation/schemas.py
app/evaluation/runner.py
app/evaluation/cases/*.yaml
scripts/run_prompt_evals.py
tests/test_evaluation_cases_load.py
```

当前能力：

- 读取 YAML suite。
- 校验 suite 对应 prompt manifest scene。
- fixture 模式校验 expected 字段。
- real provider 模式可以调用 LLM 并校验输出 schema。
- 不启动 AppContainer。
- 不执行主图。
- 不执行 ToolExecutor。
- 不覆盖审批。
- 不覆盖 Completion Verify 和 Repair。

### 1.2 现有测试覆盖

现有关键测试：

| 测试 | 覆盖内容 |
| --- | --- |
| `tests/test_langgraph_flow.py` | 主图节点路径和 no legacy node |
| `tests/test_final_compliance_check.py` | 最终合规 patch/retry/fallback |
| `tests/test_tool_calling_runner.py` | Tool Loop 多轮、失败、重复、缺参 |
| `tests/test_approval_full_flow.py` | 写工具 pending approval |
| `tests/test_approval_chain_resume.py` | 审批链和 callback resume |
| `tests/test_skill_context_builder.py` | Skill 延迟加载、no-skill 策略 |
| `tests/test_skill_selection_end_to_end.py` | 端到端 Skill 选择 |
| `tests/test_checkpoint_projection.py` | checkpoint/resume 投影 |

这些是单测/集成测试，不是可配置案例化 Eval suite。

### 1.3 Agent Eval 要补的空白

Agent Eval 需要覆盖：

- 全链路行为，而不是单 prompt。
- selected_agent 是否正确。
- selected_skill_id 是否正确。
- repair 是否固定同 Agent/Skill。
- Tool 调用是否符合预期。
- 是否重复成功步骤。
- 审批 pending 是否不进入 Completion Verify。
- callback 后是否继续验收。
- Completion PASS 但 Compliance block 是否被拦截。
- Verifier 非法输出是否 fail closed。
- 是否存在无限 repair 或超过 max rounds。

## 2. 总体目标

1. 新增 `app/evaluation/agent/` 行为级 Eval。
2. 保留现有 `PromptEvalRunner` 和 prompt cases。
3. 支持隔离构建测试 runtime。
4. 支持 Fake LLM、Fake Tool、Fake Approval、Fake BusinessStateProbe。
5. 支持 case YAML/JSON 描述。
6. 支持断言 graph path、agent、skill、tool、approval、verification、repair。
7. 支持 JSON/Markdown report。
8. 支持 baseline 比较和 CI 非零退出码。

## 2.1 已确认的运行前提

本 Eval 任务按以下已确认决策设计：

1. `selected_skill_id` 会升级为顶层 Graph State 控制字段，Eval 断言优先读取顶层字段，同时兼容从 `subagent_result.selected_skill_id` 做诊断。
2. 第一阶段 `BusinessStateProbe` 使用 `troubleshooting_agent.endo_completion_aftercare`。
3. Verifier 连续非法输出统一转 `HUMAN_HANDOFF`，Agent Eval 必须覆盖该 fail-closed 路径。
4. Completion verification 摘要会写入 MessageStore metadata，Agent Eval 可以断言轻量摘要存在，但不得要求完整 verifier 输入输出入库。
5. `ENABLE_TASK_COMPLETION_VERIFY` 在本地和测试环境默认开启，Agent Eval 默认按开启路径运行。

## 3. 禁止事项

- 不删除现有 Prompt Eval。
- 不让 Agent Eval 依赖真实外部 LLM 或真实业务 API。
- 不用 TaskContract 作为运行时验收依据。
- 不让 Eval 修改生产 Graph 行为。
- 不为通过测试硬编码保单号、request_id 或环境分支。
- 不用 Eval 的 expected 字段污染运行时 Verifier。

## 4. 目录设计

新增：

```text
app/evaluation/agent/
  __init__.py
  schemas.py
  runner.py
  assertions.py
  report.py
  fixtures.py
  fake_llm.py
  cases/
    verify_repair_core.yaml
    verify_repair_approval.yaml
    verify_repair_safety.yaml

scripts/run_agent_evals.py
```

保留：

```text
app/evaluation/schemas.py
app/evaluation/runner.py
app/evaluation/cases/*.yaml
scripts/run_prompt_evals.py
```

可选后续迁移：

```text
app/evaluation/prompt/
```

第一阶段不强制迁移，避免破坏现有 Prompt Eval。

## 5. AgentEvalCase Schema

### 5.1 新增文件

```text
app/evaluation/agent/schemas.py
```

### 5.2 主要模型

```text
AgentEvalSuite
AgentEvalCase
AgentEvalInput
AgentEvalSessionFixture
AgentEvalLLMScript
AgentEvalToolFixture
AgentEvalApprovalFixture
AgentEvalBusinessStateFixture
AgentEvalExpected
AgentEvalCaseResult
AgentEvalSuiteResult
AgentEvalReport
AgentEvalMetrics
```

### 5.3 AgentEvalCase 字段

```text
case_id: str
description: str
input:
  tenant_id
  channel
  user_id
  session_id
  messages
session_fixtures:
  recent_messages
  short_summary
llm_scripted_responses:
  scene
  match
  response
tool_fixtures:
  tool_name
  expected_arguments
  result
  is_write
approval_fixtures:
  submit_result
  callbacks
business_state_fixtures:
  probe_name
  supports_skill_id
  evidence
expected:
  initial_verifier_status
  repair_count
  final_verifier_status
  selected_agent
  selected_skill_id
  final_outcome
  approval_required
  graph_path_must_include
  graph_path_must_not_include
  tool_calls_must_include
  tool_calls_must_not_repeat
  forbidden_duplicate_actions
  max_iterations
tags: list[str]
risk_level: low | medium | high
```

### 5.4 Eval expected 与运行时 TaskContract 的区别

Agent Eval case 可以有 expected 字段，因为它是测试断言。

运行时仍不新增 TaskContract：

- Eval expected 用于判断本案例是否通过。
- Runtime Verifier 仍读取完整 Skill SOP、工具证据和状态证据。
- Eval expected 不进入 prompt，不影响生产逻辑。

## 6. AgentEvalRunner 设计

### 6.1 新增文件

```text
app/evaluation/agent/runner.py
```

### 6.2 职责

`AgentEvalRunner` 负责：

1. 加载 Agent Eval suites。
2. 为每个 case 创建隔离 AppContainer。
3. 注入 Fake LLM。
4. 注入 Fake Tools 或 monkeypatch 注册工具 callable。
5. 注入 Fake Approval client。
6. 注入 Fake BusinessStateProbe。
7. 构造 `ChatRequest`。
8. 调用真实 `AgentOrchestrator.run()` 或编译 Graph。
9. 如 case 包含 approval callback，调用 `/api/approval/callback` 或 `ApprovalService.handle_callback()`。
10. 收集运行轨迹。
11. 调用 assertions。
12. 输出 case result 和 suite report。

### 6.3 输入

```text
cases_root
suite_name
settings overrides
provider fixture mode
report_dir
baseline_path
```

### 6.4 输出

```text
AgentEvalReport
JSON report
Markdown report
exit code
```

### 6.5 状态变化

每个 case 使用独立 SQLite 文件或临时目录，不污染其他 case。

### 6.6 异常路径

- container startup 失败：case failed，并执行 shutdown。
- Fake LLM 脚本耗尽：case failed，reason=`llm_script_exhausted`。
- 真实 Graph 抛异常：case failed，记录 exception。
- 断言失败：case failed，记录失败断言。
- callback 失败：case failed。
- report 写入失败：runner 返回非零。

## 7. Fixture 设计

### 7.1 Fake LLM

新增：

```text
app/evaluation/agent/fake_llm.py
```

能力：

- 按 scene 匹配响应。
- 按调用顺序匹配响应。
- 支持 tool_calls 响应。
- 支持非法 JSON 响应。
- 记录每次调用的 scene、messages、tools、request_id、trace_id。

示例：

```yaml
llm_scripted_responses:
  - scene: query_rewrite
    response:
      content_json:
        is_follow_up: false
        rewritten_query: "..."
        rewrite_type: new_request
        entities: {}
        inherited_entities: {}
        need_clarification: false
        missing_required_entities: []
        confidence: 0.9
  - scene: subagent_reasoning
    response:
      tool_calls:
        - name: query_endo_task_record
          arguments:
            apply_seq: "930021042875719"
  - scene: task_completion_verifier
    response:
      content_json:
        status: CONTINUE
        ...
```

### 7.2 Fake Tools

可选方式：

1. 使用现有 mock tool handlers。
2. 在 case fixture 中覆盖指定工具 callable。

Fake Tool 必须仍注册到 `ToolRegistry`，并通过真实 `ToolExecutor` 执行。

禁止直接把工具结果塞给子 Agent 绕过 ToolExecutor。

### 7.3 Fake Approval

使用 Fake `ApprovalSystemClient`：

```text
submit_approval_request() -> ApprovalSubmitResult(accepted=True, status="pending")
```

callback 通过 `ApprovalService.handle_callback()` 触发。

### 7.4 Fake BusinessStateProbe

用于验证写接口 success 但最终状态不一致等场景。

Fake Probe 只返回 `VerificationEvidence`，不执行工具。

## 8. Assertions 设计

新增：

```text
app/evaluation/agent/assertions.py
```

核心断言：

| 断言 | 说明 |
| --- | --- |
| `assert_selected_agent` | 最终 state 中 `selected_agent` 等于 expected |
| `assert_selected_skill` | `selected_skill_id` 或 `subagent_result.selected_skill_id` 等于 expected |
| `assert_repair_count` | repair_round 或 trace 中 repair 次数等于 expected |
| `assert_completion_status` | initial/final verifier status 符合 expected |
| `assert_graph_path` | graph_path 包含/不包含指定节点 |
| `assert_tool_calls` | 工具调用包含预期工具 |
| `assert_no_duplicate_actions` | 成功工具和参数不重复 |
| `assert_approval_route` | 写工具触发审批，pending 不进入 completion verify |
| `assert_no_agent_drift` | repair 没有换 Agent |
| `assert_no_skill_drift` | repair 没有换 Skill |
| `assert_max_rounds` | 不超过最大修复次数 |
| `assert_compliance_boundary` | completion PASS 但 compliance block 时最终仍被拦截 |

断言失败要输出：

```text
case_id
assertion_name
expected
actual
graph_path
selected_agent
selected_skill_id
repair_round
tool_call_summary
```

## 9. Report 设计

新增：

```text
app/evaluation/agent/report.py
```

JSON report：

```text
suite
total
passed
failed
metrics
cases[]
```

Markdown report：

```text
# Agent Eval Report
## Summary
## Metrics
## Failed Cases
## Case Details
```

报告不保存完整 prompt、完整 tool result 或敏感字段。

## 10. 指标

### Task Agent

```text
first_pass_completion_rate
first_pass_failure_rate
```

### Verifier

```text
verifier_pass_accuracy
verifier_incomplete_detection_rate
verifier_false_pass_rate
verifier_false_continue_rate
```

### Repair

```text
repair_attempt_rate
repair_success_rate
average_repair_rounds
no_progress_termination_rate
```

### 整体系统

```text
final_task_completion_rate
final_failure_rate
human_handoff_rate
need_user_rate
average_tool_calls
duplicate_tool_call_rate
average_llm_calls
average_latency
```

### CI 硬门禁

高风险核心 suite：

```text
verifier_false_pass_rate = 0
infinite_loop_count = 0
max_repair_round_violation_count = 0
agent_drift_count = 0
skill_drift_count = 0
approval_bypass_count = 0
```

模型质量分数暂不作为唯一硬门禁。

## 11. 第一批必须覆盖的案例

### A. 首轮直接完成

目标：

```text
子 Agent 按 Skill 完成任务
Verifier 返回 PASS
repair_round = 0
```

检查：

- graph_path 包含 `verify_task_completion`。
- 不包含 `dispatch_repair_agent`。
- final compliance 执行。

### B. 首轮未完成，修复后完成

目标：

```text
首轮只完成部分步骤
Verifier 返回 CONTINUE
RepairPlan 指出缺失项
原子 Agent 继续执行
第二次 Verifier 返回 PASS
```

检查：

- 同一个 Agent。
- 同一个 Skill。
- 没有重复成功步骤。

### C. 缺少用户信息

目标：

```text
Verifier 返回 NEED_USER
不进入 Repair Agent
```

检查：

- 进入 `build_verification_clarification`。
- 最终仍经过 `pre_answer_verify`。

### D. Repair 中触发审批

目标：

```text
首轮未产生写工具
Verifier 要求继续
Repair 子 Agent 产生写工具
进入现有审批链
```

检查：

- `approval_required=true`。
- `pause_for_approval` 之后不进入 Completion Verify。

### E. 审批 pending 不执行 Completion Verify

目标：

```text
pending response 不被 completion verifier 判定失败
```

检查：

- graph_path 不包含 `verify_task_completion` after `pause_for_approval`。
- pending 答案进入 `pre_answer_verify`。

### F. 审批 callback 后完成

目标：

```text
审批通过后恢复工具循环
无更多审批后进入 Completion Verify
最终 PASS
```

检查：

- graph_path 包含 `resume_approved_tool`。
- 包含 `verify_task_completion`。

### G. 写操作 success 但最终状态不一致

目标：

```text
写接口 success
BusinessStateProbe 显示状态仍旧
Verifier 返回 CONTINUE 或 HUMAN_HANDOFF
```

检查：

- 不允许 false PASS。

### H. 最大修复次数

目标：

```text
连续两次修复仍未完成
停止循环
不能第三次执行
```

检查：

- repair_round 不超过 2。
- final status 是 HUMAN_HANDOFF 或 FAILED。

### I. 无进展检测

目标：

```text
两轮没有新增 Evidence 或重复相同工具调用
停止继续 Repair
```

检查：

- no_progress guard 命中。

### J. Verifier 输出非法 JSON

目标：

```text
第一次非法 -> 格式修复
第二次非法 -> fail closed
```

检查：

- 不进入无限 repair。
- final status HUMAN_HANDOFF 或 FAILED。

### K. Verifier 错误要求重复操作

目标：

```text
RepairPlan 要求重复已成功高风险写操作
sanitizer 或 guard 阻止
```

检查：

- 不产生重复写工具审批。

### L. Completion PASS 但 Compliance block

目标：

```text
任务已完成
但最终回答包含敏感字段
pre_answer_verify 仍拦截或 patch
```

检查：

- completion status PASS。
- final compliance action retry/block/patch。

## 12. Phase 6：Agent Eval MVP

### 目标

完成 AgentEvalCase、AgentEvalRunner、fixtures、assertions、report 和核心 A-F 案例。

### 为什么做

在 Verify-Repair 主图接入后，需要可重复、可 CI 的行为级评估，验证系统没有换 Agent/Skill、没有绕过审批、没有无限修复。

### 修改文件

```text
pyproject.toml
```

仅在需要注册 script entrypoint 时修改。

### 新增文件

```text
app/evaluation/agent/__init__.py
app/evaluation/agent/schemas.py
app/evaluation/agent/runner.py
app/evaluation/agent/assertions.py
app/evaluation/agent/report.py
app/evaluation/agent/fixtures.py
app/evaluation/agent/fake_llm.py
app/evaluation/agent/cases/verify_repair_core.yaml
app/evaluation/agent/cases/verify_repair_approval.yaml
scripts/run_agent_evals.py
tests/test_agent_eval_cases_load.py
tests/test_agent_eval_runner.py
tests/test_agent_eval_report.py
```

### 主要类或函数

```text
AgentEvalCase
AgentEvalSuite
AgentEvalRunner.run()
AgentEvalFixtureApplier
AgentEvalFakeLLM
AgentEvalAssertions
AgentEvalReportRenderer
```

### 输入

```text
YAML cases
settings overrides
Fake LLM scripts
Fake tool fixtures
Fake approval fixtures
Fake state probe fixtures
```

### 输出

```text
AgentEvalReport
JSON report
Markdown report
exit code
```

### 状态变化

每个 case 使用隔离 DB。Eval 不写生产 DB。

### 异常路径

- case schema 无效：suite load 失败。
- Fake LLM 响应不足：case fail。
- Graph exception：case fail。
- Assertion fail：case fail。
- report 写入 fail：CLI 非零退出。

### 测试

新增：

```text
tests/test_agent_eval_cases_load.py
tests/test_agent_eval_runner.py
tests/test_agent_eval_report.py
```

回归：

```text
tests/test_evaluation_cases_load.py
```

覆盖：

1. Agent eval cases 能加载且 ID 唯一。
2. Prompt eval cases 仍能加载。
3. Runner 能跑单 case。
4. Runner 能收集 graph_path、selected_agent、selected_skill_id。
5. Runner 能执行 approval callback fixture。
6. 断言失败时输出清晰 reason。
7. JSON/Markdown report 可生成。

### 验收标准

- Prompt Eval 不受影响。
- Agent Eval MVP 至少覆盖 A-F。
- Fake LLM/Fake Tools 不绕过真实 Graph/ToolExecutor。
- CI 可通过 `scripts/run_agent_evals.py --suite verify_repair_core` 执行。

### 依赖关系

依赖 Verify-Repair Phase 5 接入主图。可以先用 stub completion verifier 做 runner 骨架，但完整验收必须等 Phase 5。

## 13. Phase 7：CI 与基线

### 目标

增加核心 suite、baseline report、阈值检查和非零退出码。

### 为什么做

Agent Eval 的价值在于防止架构级回归，尤其是 false pass、绕过审批、无限 repair、Agent/Skill drift。

### 修改文件

```text
scripts/run_agent_evals.py
pyproject.toml
.github/workflows/* 或项目实际 CI 配置
```

如果当前项目没有 CI 配置，本阶段只新增本地 CLI 和文档化命令，不强行引入 GitHub Actions。

### 新增文件

```text
app/evaluation/agent/baseline.py
app/evaluation/agent/cases/verify_repair_safety.yaml
app/evaluation/agent/cases/verify_repair_state_probe.yaml
tests/test_agent_eval_baseline.py
```

### 主要类或函数

```text
AgentEvalBaseline
compare_baseline(report, baseline)
enforce_thresholds(report, thresholds)
```

### 输入

```text
current report
baseline report
threshold config
```

### 输出

```text
pass/fail
diff summary
exit code
```

### 状态变化

无生产状态变化。

### 异常路径

- baseline 缺失：允许 `--update-baseline` 创建，CI 默认失败或 warning。
- 指标超过阈值：非零退出。
- case 新增但 baseline 无记录：要求显式更新 baseline。

### 测试

新增：

```text
tests/test_agent_eval_baseline.py
tests/test_agent_eval_thresholds.py
```

覆盖：

1. false pass > 0 时失败。
2. max repair rounds violation > 0 时失败。
3. agent drift > 0 时失败。
4. skill drift > 0 时失败。
5. approval bypass > 0 时失败。
6. baseline diff 能列出新增/删除/变化 case。

### 验收标准

- 核心高风险 suite 有硬门禁。
- 失败报告足够定位：case_id、graph_path、tool_calls、repair trace。
- 不使用真实外部 API。

### 依赖关系

依赖 Phase 6。

## 14. 推荐 CLI

新增：

```text
uv run python scripts/run_agent_evals.py
uv run python scripts/run_agent_evals.py --suite verify_repair_core
uv run python scripts/run_agent_evals.py --suite verify_repair_safety --report-dir .reports/agent-eval
uv run python scripts/run_agent_evals.py --baseline .reports/baseline.json
```

保留：

```text
uv run python scripts/run_prompt_evals.py
```

## 15. Eval 与生产代码的边界

Agent Eval 可以：

- 构建真实 AppContainer。
- 注入 Fake LLM。
- 注入 Fake Approval client。
- 覆盖工具 callable。
- 使用隔离 SQLite。
- 调用真实 Orchestrator。

Agent Eval 不可以：

- 修改生产 prompt 以迎合测试。
- 修改生产路由以迎合 case。
- 直接调用子 Agent 跳过主图。
- 直接把工具结果塞进 LLM messages 绕过 ToolExecutor。
- 把 expected 字段作为运行时验收规则。

## 16. Agent Eval Case 示例草案

```yaml
suite: verify_repair_core
cases:
  - case_id: aftercare_first_pass
    description: "保全任务完成后未更新，首轮完成并验收通过"
    input:
      tenant_id: "tenant"
      channel: "web"
      user_id: "u1"
      session_id: "s1"
      messages:
        - role: "user"
          content: "保全任务完成，保单9200100000458846没有更新，受理号930021042875719，保全项001028"
    llm_scripted_responses:
      - scene: "query_rewrite"
        response:
          content_json:
            is_follow_up: false
            rewritten_query: "保全任务完成，保单9200100000458846，受理号930021042875719，保全项001028，为什么没有更新？"
            rewrite_type: "new_request"
            entities:
              policy_no: "9200100000458846"
              apply_seq: "930021042875719"
              endorseType: "001028"
            inherited_entities: {}
            missing_required_entities: []
            need_clarification: false
            confidence: 0.95
            reason: "eval"
      - scene: "subagent_reasoning"
        response:
          tool_calls:
            - name: "query_endo_task_record"
              arguments:
                apply_seq: "930021042875719"
      - scene: "subagent_reasoning"
        response:
          content: "已查询到9节点失败，已根据规则通知保单更新。"
      - scene: "task_completion_verifier"
        response:
          content_json:
            status: "PASS"
            completed: true
            summary: "查询和处理均有证据。"
            completed_items:
              - "已查询保全任务节点"
            missing_items: []
            repair_plan: null
            confidence: 0.9
            reasoning_summary: "工具证据满足 Skill 输出要求。"
            evidence_ids: []
    expected:
      selected_agent: "troubleshooting_agent"
      selected_skill_id: "troubleshooting_agent.endo_completion_aftercare"
      repair_count: 0
      final_verifier_status: "PASS"
      final_outcome: "answered"
```

实际 schema 可以比此草案更严格，但必须表达同等信息。

## 17. 风险与控制

| 风险 | 控制 |
| --- | --- |
| Fake 太理想化 | 用失败、非法 JSON、审批、状态不一致案例补齐 |
| Eval 误以为通过但主图没跑 | Runner 必须调用真实 Orchestrator 或编译 Graph |
| 绕过 ToolExecutor | Fake tool 必须注册到 ToolRegistry，由 ToolExecutor 执行 |
| 难定位失败 | Report 输出 graph_path、tool summary、repair trace |
| Prompt Eval 被破坏 | 单独回归 `tests/test_evaluation_cases_load.py` |
| 指标成为噪声 | 第一阶段只对安全门禁设硬阈值 |

## 18. 回滚方案

1. Agent Eval 新目录与生产主链路解耦，可直接不运行。
2. Prompt Eval 保持原入口。
3. CI 集成失败时先从强制门禁降为手动命令。
4. Baseline 机制可独立关闭。

## 19. 需要人工确认的问题

1. Agent Eval 报告是否需要默认写入 `.reports/agent-eval/`。
2. 高风险 suite 是否第一阶段就进入 CI 硬门禁。
3. baseline 文件是否提交到仓库。
4. 是否允许 runner 通过 monkeypatch 覆盖 container 内工具 callable，还是必须通过 fixture 注册新 ToolRegistry。
5. 首批 case A-L 是否全部一次完成，还是 Phase 6 完成 A-F、Phase 7 完成 G-L。
