# 新增或修改子 Agent

适用场景：新增专业子 Agent、给现有 Agent 增加路由/工具/权限/记忆策略，或调整 Agent 的业务执行行为。

## 当前真实执行结构

```text
AgentCard YAML
  -> AgentCardLoader / AgentSelectionNode
  -> dispatch_agent
  -> SubAgentManager.call_subagent(agent_name)
  -> BaseSubAgent.run()
  -> ContextBuilder.build_for_subagent()
  -> SkillSelector + ToolCallingRunner
```

AgentCard 是“能否被选中、能看到什么”的声明；SubAgent class 是“选中后如何构造上下文、Prompt 和结果”的执行模板。不要只创建 YAML 而不注册实际 Agent，也不要只注册 class 而没有 enabled AgentCard。

## 1. 新增 Agent 的必改清单

### 第一步：先定义 route 和实体边界

1. 在 `app/config/intent_taxonomy.yaml` 增加或复用合法 intent/sub_intent。
2. 设计 AgentCard 的 `supported_routes`、`required_entities`、`optional_entities`、`access_policy`、工具可见性与 memory policy。
3. 确认每个 route 将由至少一个 Skill 覆盖；`STRICT_TAXONOMY_ROUTE_COVERAGE=true` 时，taxonomy route 没有 enabled AgentCard 会使启动失败。

详细 route 规则见 [02-intent-and-agent-routing.md](02-intent-and-agent-routing.md)。

### 第二步：创建 AgentCard

新增 `app/agents/cards/<agent_name>.yaml`。字段以 `app/schemas/agent_card.py:AgentCard` 为准，最低应包含：

```yaml
agent_name: new_agent
display_name: 新 Agent
description: 用于说明业务边界和候选语义。
capabilities:
  - capability_name
supported_routes:
  some_intent:
    - some_sub_intent
required_entities: []
optional_entities: []
output_schema: SubAgentResult
private_tools: []
public_tools_allowed: false
mcp_policy:
  enabled: false
skills:
  - new_agent.some_skill
rag_namespaces: []
memory_policy:
  use_short_summary: true
  recent_turns: 5
examples:
  - query: 示例问题
    intent: some_intent
    sub_intent: some_sub_intent
enabled: true
version: "1.0.0"
```

注意：

- `supported_intents` / `supported_sub_intents` 是 schema 兼容字段，当前新卡片应以 `supported_routes` 为准。
- `private_tools` 是 Agent 最大工具边界；Skill 的 private tools 只能是其子集。
- `mcp_policy.enabled: true` 表示该 Agent 可看到当前已发现的 MCP 工具，不是声明固定 MCP 工具列表。
- `description`、`capabilities`、examples 会参与候选打分和 LLM router，不要写营销文案或泛化能力。

### 第三步：实现并注册 SubAgent

| 文件 | 必须做什么 |
| --- | --- |
| `app/subagents/<agent_name>.py` | 常规场景继承 `BaseSubAgent`，设置 `name`；只有业务 Prompt、工具循环结果或非工具执行行为不同才覆写 `do_run()`、`build_messages()`、`build_result_from_runner()`。 |
| `app/bootstrap/agents.py` | 在 `build_subagent_manager()` 中创建并 `manager.register("<agent_name>", AgentClass(...))`；依赖必须显式传 `context_builder`、`tool_executor`、`tool_calling_runner`。 |
| `app/subagents/manager.py` | 通常不改。只有所有 Agent 都需要的新公共运行协议时才扩展。 |

不要把 `AppContainer` 注入 SubAgent；它是最外层 composition root。SubAgent 只能接收其真实依赖。

### 第四步：为 Agent 增加 Skill 和 Tool

至少创建一个 Skill，并把 `skill_id` 写入 AgentCard。工具按照 [05-local-tool-and-contract.md](05-local-tool-and-contract.md) 注册后，才可写进 Card 的 `private_tools`。如 Agent 无 Skill，默认 `NO_SKILL_POLICY=clarify`，不会进入 `ToolCallingRunner`。

## 2. 修改现有 Agent 的常见路径

| 需求 | 先改哪里 | 通常还要检查 |
| --- | --- | --- |
| 新增一个可处理业务 route | AgentCard `supported_routes` | taxonomy、对应 Skill frontmatter、routing tests |
| 调整候选匹配效果 | Card description/capabilities/examples 或 routing policy | `card_loader.match_candidates()`、LLM router eval |
| 让 Agent 使用一个现有 private tool | Card `private_tools` | Skill `private_tools`、实际 registry 注册 |
| 让 Agent 使用所有发现的 MCP 工具 | `mcp_policy.enabled` | `ENABLE_MCP_CLIENT`、unknown MCP policy、MCP tests |
| 增加访问限制 | Card `access_policy` | `AuthorizationService` 测试；Tool 级 scope 仍要独立配置 |
| 调整历史消息量 | Card `memory_policy` | `ContextBuilder`、长对话/追问测试 |
| 变更专业执行格式 | SubAgent class / prompt | Skill 正文、ToolCallingRunner tests |

## 3. 不要混淆的边界

- Agent selection 选“哪个业务执行边界”，不选 Skill 或工具。
- `dispatch_agent` 内部通过 `AgentTaskAssembler` 组装任务；它不是复杂 planner。
- Skill 是在 `ContextBuilder.build_for_subagent()` 中选择并延迟加载的，不在主 Graph 的独立节点中加载。
- ToolRegistry 决定可见工具；AgentCard 只是声明此 Agent 的许可范围。

## 测试与启动校验

```bash
uv run pytest tests/test_agent_card_loader.py tests/test_agent_routing_policy.py -q
uv run pytest tests/test_subagent_tool_visibility.py tests/test_skill_selection_end_to_end.py -q
uv run pytest tests/test_langgraph_flow.py tests/test_architecture_acceptance.py -q
```

新增 Agent 后，还应实际构建一次 container，确保 card/taxonomy/skill 交叉校验会在启动前通过：

```bash
uv run pytest tests/test_app_container.py -q
```
