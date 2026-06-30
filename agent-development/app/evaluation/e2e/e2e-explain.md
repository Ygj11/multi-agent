# Agent Dynamic E2E Eval 使用说明

`app/evaluation/e2e` 用来评估真实 LLM 对完整 Agent 链路的影响。它和现有两类 eval 的关系是：

| 类型 | 入口 | LLM | 主要用途 |
| --- | --- | --- | --- |
| Prompt Eval | 单个 prompt scene | 默认静态，也可注入 provider | 检查单个提示词输出结构和期望 |
| Agent Deterministic Eval | MainGraph | `AgentEvalFakeLLM` | 稳定回归主流程、审批、Repair、工具链路 |
| Agent Dynamic E2E Eval | `/api/chat` 等价输入 | 真实项目 LLM Provider | 评估真实模型是否让完整 Agent 偏航 |

## 运行前准备

Dynamic E2E 默认读取项目 `.env`。至少需要配置一个真实 LLM Provider：

```bash
ENABLE_REAL_LLM=true
ENABLE_OPENSDK_LLM=true
OPENAI_BASE_URL=https://api.deepseek.com
OPENAI_MODEL=deepseek-v4-pro
OPENAI_API_KEY=你的apikey
```

如果使用内部 LLM，则配置：

```bash
ENABLE_REAL_LLM=true
ENABLE_OPENSDK_LLM=false
INTERNAL_LLM_API_URL=http://你的内网模型地址
```

工具可以先使用 mock：

```bash
POS_TOOL_MODE=mock
TROUBLESHOOTING_TOOL_MODE=mock
ENABLE_MCP_CLIENT=false
ENABLE_KNOWLEDGE_API=false
```

## 如何运行

可以在项目根目录执行：

```bash
uv run python - <<'PY'
from app.evaluation.e2e.runner import run_dynamic_e2e_eval_sync
from app.evaluation.agent.report import AgentEvalReportRenderer

report = run_dynamic_e2e_eval_sync(
    suite_name="dynamic_smoke",
    case_id="aftercare_dynamic_smoke",
)

print(AgentEvalReportRenderer.to_markdown(report))
PY
```

## Case 怎么写

用例放在：

```text
app/evaluation/e2e/cases/
```

一个最小 case 包含：

```yaml
suite: dynamic_smoke
cases:
  - case_id: aftercare_dynamic_smoke
    transport: orchestrator
    llm_mode: real
    input:
      tenant_id: tenant
      channel: web
      user_id: u1
      session_id: s1
      messages:
        - role: user
          content: "保全任务完成，保单9200100000458846没有更新，受理号930021042875719，保全项001028"
    settings_overrides:
      ENABLE_REAL_LLM: "true"
      POS_TOOL_MODE: "mock"
      TROUBLESHOOTING_TOOL_MODE: "mock"
    expected:
      selected_agent: troubleshooting_agent
      selected_skill_id: troubleshooting_agent.endo_completion_aftercare
      tool_calls_must_include:
        - query_endo_task_record
      answer_must_include:
        - 保全
```

## transport 怎么选

`transport: orchestrator` 表示从 `RequestAdapter + Orchestrator` 进入，能稳定拿到完整 state 和 trace，适合大多数评测。

`transport: http` 表示通过 FastAPI `/api/chat` 进入，更接近外部调用方式。HTTP 响应本身不会暴露内部 state，所以 runner 会在请求结束后读取 checkpoint 和日志来补齐 trace。

## 断言策略

不要只断言最终回答全文相等。真实 LLM 文案会波动，Dynamic E2E 更适合断言关键行为：

- `selected_agent`
- `selected_skill_id`
- `graph_path_must_include`
- `tool_calls_must_include`
- `answer_must_include`
- `answer_must_not_include`
- `final_outcome`
- `approval_required`
- `final_verifier_status`

最终回答只做关键词和风险项断言；路由、工具和状态用确定性断言兜住。

## 和 CI 的关系

Dynamic E2E 会调用真实模型，成本、耗时和输出稳定性都不同于 Fake eval。建议：

- 普通 CI 跑 Prompt Eval 和 Agent Deterministic Eval；
- Dynamic E2E 用于手动回归、上线前回归、模型切换前后对比、Prompt 调整后验收；
- 高风险 case 可以单独建 suite，作为发布门禁人工执行。
