# 修改导航手册

本目录是基于当前运行时代码编写的变更手册，不是目标架构或历史设计文档。修改前先从本文件选择入口；不要仅修改 YAML、Prompt 或某个节点后就假定主链路会自动生效。

## 真实主链路

```text
Settings + AppContainer
  -> MainGraph
  -> load_session / query_rewrite / intent_recognition
  -> build_orchestrator_context / select_agent / dispatch_agent
  -> BaseSubAgent / SkillSelector / ToolCallingRunner
  -> ToolExecutor / Approval / Verification
  -> message, memory, checkpoint, evidence, logs
```

关键原则：

- `entity_bag` 是 canonical 实体状态；`entities` 只是 `entity_bag.to_compact_dict()` 的兼容投影。
- `intent_taxonomy.yaml` 定义系统允许的业务意图；AgentCard 声明哪个 Agent 能处理哪些 route；Skill 定义 Agent 内部的 SOP。
- LLM 只能提出 tool call；`ToolExecutor` 才能决定工具是否实际执行。
- `AppContainer` 是运行时 composition root；FastAPI 只暴露 `app.state.container`，内部组件不得依赖整个 container。

## 从“我想改什么”开始

| 变更诉求 | 先读 | 常见下游依赖 |
| --- | --- | --- |
| 增加/修改实体、改写、追问、澄清继承 | [01-query-rewrite-and-entities.md](01-query-rewrite-and-entities.md) | Intent、Skill required entities、工具参数、测试 fixture |
| 增加 Intent 或调整分类、Agent 路由 | [02-intent-and-agent-routing.md](02-intent-and-agent-routing.md) | AgentCard、Skill、Prompt、eval、路由测试 |
| 新增或调整子 Agent | [03-agent-card-and-subagent.md](03-agent-card-and-subagent.md) | taxonomy、Skill、工具、`app/bootstrap/agents.py` |
| 新增/修改 Skill SOP | [04-skill-sop-and-selection.md](04-skill-sop-and-selection.md) | AgentCard、required entities、工具、Skill 测试 |
| 新增本地 public/private 工具或改工具契约 | [05-local-tool-and-contract.md](05-local-tool-and-contract.md) | AgentCard、Skill、contract、授权、审批、工具测试 |
| 接入或调整 MCP server / MCP 工具策略 | [06-mcp-integration.md](06-mcp-integration.md) | `.env`、Container startup、AgentCard `mcp_policy`、MCP 测试 |
| 新增/调整 LangGraph 节点、状态字段或分支 | [07-main-graph-and-state.md](07-main-graph-and-state.md) | RoutePolicy、state projector、handlers、主流程测试 |
| 调整审批、Verification、Evidence 或恢复行为 | [08-approval-verification-and-evidence.md](08-approval-verification-and-evidence.md) | ToolExecutor、Graph handler、SQLite store、审批回归 |
| 改 LLM Prompt、schema、fallback 或 eval | [09-prompts-fallback-and-evaluation.md](09-prompts-fallback-and-evaluation.md) | manifest、output schema、fixtures、节点测试 |
| 改启动、环境变量、持久化、日志或外部 client | [10-runtime-configuration-and-storage.md](10-runtime-configuration-and-storage.md) | AppContainer、settings、store、启动与持久化测试 |

## 通用修改顺序

1. 先确定变更属于哪个业务边界，不要直接在 Graph 里堆判断。
2. 先改权威声明：taxonomy、AgentCard、Skill metadata、ToolDefinition/contract、实体规则中的对应一项。
3. 再改执行实现：node/service/handler/client。
4. 再改 LLM Prompt 或 fallback；只有语义行为变化时才改，不能用 Prompt 掩盖代码边界缺失。
5. 补与本次行为相对应的单元测试、节点测试和端到端回归。
6. 至少执行目标测试；跨越 Graph、Tool、审批、持久化边界时执行 `uv run pytest -q`。

## 需要同时保持的跨文件约束

| 约束 | 关系 |
| --- | --- |
| 实体状态 | 不直接手写合并 `entities`；使用 `EntityResolver` 和 `build_entity_state_updates()` 同步写入 Graph state。 |
| Intent 路由 | `taxonomy intent/sub_intent` -> `AgentCard.supported_routes` -> `Skill.intent/sub_intents`。启动时会验证。 |
| Skill 工具 | `Skill.private_tools` 必须是所属 AgentCard `private_tools` 的子集。 |
| Agent 实现 | AgentCard `agent_name` 必须能在 `app/bootstrap/agents.py` 注册到 `SubAgentManager`。 |
| 工具可见性 | 工具必须注册到 `ToolRegistry`，并被 AgentCard 声明；MCP 还要由 `mcp_policy.enabled` 放行。 |
| 写操作 | `is_write`、`operation`、`risk_level`、ToolContract 与审批策略必须一致，不能只改 Tool 描述。 |

## 统一验证命令

```bash
cd /Users/ygj/ygjAll/multi-agent/agent-development
uv run pytest <目标测试文件> -q
uv run pytest -q
```

修改 Prompt 或 eval fixture 时，额外执行：

```bash
uv run pytest tests/test_prompt_manifest.py tests/test_prompt_templates.py tests/test_evaluation_cases_load.py -q
```

修改启动装配或 FastAPI state 时，额外执行：

```bash
uv run pytest tests/test_app_container.py tests/test_settings_env.py tests/test_sqlite_persistence.py -q
```
