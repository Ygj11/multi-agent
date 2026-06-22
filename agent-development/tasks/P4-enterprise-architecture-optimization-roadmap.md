# P4 Enterprise Agent Architecture Optimization Roadmap

## 任务来源

本路线图来自：

- `opt/enterprise-agent-architecture-optimization-report.md`

该报告判断：当前项目已经具备企业级 Agent 平台雏形，但仍需要围绕生产风险、fallback 可观测、规则治理、prompt 生命周期、工具契约、观测审计和上线准入继续优化。

## 命名说明

现有项目任务已经推进到 P3，因此本轮企业级优化统一命名为 `P4.x` 系列。

每个 `P4.x` 文件内部会标明真实业务优先级：

- 企业级 P0：必须优先做，防止上环境误用 mock、silent fallback 或无 skill 泛化执行。
- 企业级 P1：治理规则、路由、节点契约，让主干可维护。
- 企业级 P2：治理 prompt 和 eval，让模型行为可评估。
- 企业级 P3：治理工具契约，让工具从“函数调用”升级为“企业能力”。
- 企业级 P4：治理观测、审计和上线准入。

## 推荐执行顺序

### 1. `P4.0-enterprise-production-risk-gates-task.md`

优先级：企业级 P0

目标：

- 增加 `APP_ENV`。
- 生产环境禁止 mock tool mode。
- 生产环境禁止 InternalLLMProvider 本地 fallback。
- 生产环境禁止 mock approval URL。
- 防止开发配置误带到上环境。

必须先做。否则后面任何能力都可能在 mock 或 fallback 状态下被误认为真实可用。

### 2. `P4.1-enterprise-fallback-and-no-skill-semantics-task.md`

优先级：企业级 P0

目标：

- 消除 silent fallback。
- 明确 no-skill 行为。
- 移除 `generic_skill_content` 的生产默认执行语义。
- 强化 subagent reasoning prompt。
- 移除 `BaseSubAgent` 中的业务硬编码。

该任务处理“系统看起来成功，但实际走了兜底”的核心风险。

### 3. `P4.2-enterprise-rule-route-node-governance-task.md`

优先级：企业级 P1

目标：

- 建立 NodeContract。
- 建立 RoutePolicy。
- 外置 Query Rewrite 上下文引用策略。
- 外置 Intent fallback policy。
- Agent selection scoring policy YAML 化。

该任务处理代码中规则散落、阈值散落、路由条件难治理的问题。

### 4. `P4.3-enterprise-prompt-manifest-eval-task.md`

优先级：企业级 P2

目标：

- 建立 PromptManifest。
- LLM 输出严格 schema 解析。
- 建立 eval cases 和 eval runner。
- prompt version 写入 decision trace。

该任务处理 prompt 无版本、无评测、难回滚的问题。

### 5. `P4.4-enterprise-tool-contract-governance-task.md`

优先级：企业级 P3

目标：

- 建立 ToolContract。
- 增加 timeout、retry、result schema、approval policy、idempotency policy。
- ToolExecutionPipeline 执行契约校验。
- 工具异常映射成稳定 error code。

该任务处理工具执行从“可调用函数”升级为“受治理企业能力”的问题。

### 6. `P4.5-enterprise-observability-release-readiness-task.md`

优先级：企业级 P4

目标：

- 标准化 request/node/llm/tool/verification span。
- 建立 fallback rate、unknown rate、tool failure rate 等指标。
- 建立 request_id 决策回放。
- 建立上线准入脚本。

该任务处理“出问题能不能定位、上线前能不能证明可用”的问题。

## 依赖关系

```text
P4.0 生产风险 gate
  -> P4.1 fallback/no-skill 语义
  -> P4.2 规则/路由/节点契约治理
  -> P4.3 prompt manifest/eval
  -> P4.4 tool contract
  -> P4.5 observability/release readiness
```

其中：

- `P4.0` 和 `P4.1` 是上线前硬门槛。
- `P4.2` 是长期架构治理的主骨架。
- `P4.3` 是 LLM 质量治理。
- `P4.4` 是工具生产治理。
- `P4.5` 是平台化和生产运维治理。

## 完成后的目标状态

完成 P4 系列后，项目应达到：

- 生产环境无法误用 mock。
- 每次 fallback 都有明确原因。
- no-skill 不再静默泛化执行。
- LangGraph node 有输入输出契约。
- 规则和阈值可以通过 policy 文件维护。
- prompt 有版本、schema 和 eval。
- 工具有完整契约、超时、重试、结果校验和审批策略。
- 失败请求可通过 request_id 回放主要决策路径。
- 上环境前有固定准入检查。
