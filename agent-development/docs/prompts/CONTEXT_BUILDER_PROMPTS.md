# ContextBuilder Prompts

## 当前代码位置

- `app/runtime/context_builder.py`
- 上游：LangGraph state、`SessionManager`、`MessageStore`、`ShortTermMemoryManager`、`KnowledgeService`
- 下游：`OrchestratorContext`、`SubAgentContext`、`SkillSelector`、子 Agent

## build_for_orchestrator 做了什么

`ContextBuilder.build_for_orchestrator()` 当前构建主干轻量上下文：

- `original_query`
- `rewritten_query`
- `intent`
- `session_key`
- `recent_messages`
- `short_summary`
- `available_subagents`
- `available_tools`
- `lightweight_knowledge_hints`

`lightweight_knowledge_hints` 来自 `KnowledgeService.pre_search()`。

当前该方法不拼接 system prompt，不构造 LLM messages。

## build_for_subagent 做了什么

`ContextBuilder.build_for_subagent()` 当前负责：

1. 调用 `build_skill_selection_context()` 构建 skill 选择上下文。
2. 通过 `SkillCatalog.list_skills(task.name)` 获取候选 skill metadata。
3. 通过 `SkillSelector.select()` 选择 `selected_skill_id`。
4. 通过 `SkillLoader.load()` 加载选中的完整 `SKILL.md`。
5. 将 selected skill 信息写入 `task.metadata`。
6. 调用 `KnowledgeService.search()` 获取子 Agent 任务级知识提示。
7. 返回 `SubAgentContext`。

当前该方法会把 selected skill 正文放入：

```text
SubAgentContext.skill_content
```

但当前没有将该内容发送给 LLM。

## build_skill_selection_context 做了什么

`ContextBuilder.build_skill_selection_context()` 当前构建 `SkillSelectionContext`：

- `agent_name`
- `intent`
- `original_query`
- `rewritten_query`
- `session_key`
- `short_summary`
- `recent_messages_summary`
- `lightweight_knowledge_hints`
- `request_id`
- `trace_id`
- `extracted_error_code`
- `extracted_request_id`
- `extracted_interface_name`
- `business_domain`

这些字段用于规则版 `SkillSelector` 打分。

## 当前是否拼接 System Prompt

当前 ContextBuilder 未拼接 system prompt。

当前 ContextBuilder 只构建结构化上下文对象，不构建如下格式：

```json
[
  {"role": "system", "content": "..."},
  {"role": "user", "content": "..."}
]
```

## 当前传给子 Agent 的上下文

`SubAgentContext` 当前包含：

- `task`
- `rewritten_query`
- `intent`
- `allowed_tools`
- `skill_content`
- `selected_skill_id`
- `selected_skill_metadata`
- `skill_selection_score`
- `skill_selection_reason`
- `mock_knowledge_hint`
- `recent_troubleshooting_context`

## selected skill 如何进入上下文

流程如下：

```text
SubAgentTask
-> ContextBuilder.build_skill_selection_context
-> SkillCatalog.list_skills
-> SkillSelector.select
-> SkillLoader.load(selected_skill_id)
-> SubAgentContext.skill_content
-> SubAgentResult.selected_skill_id
-> LangGraph final state.selected_skill_id
```

## 哪些内容属于 Prompt-like Context

以下内容可以视为 prompt-like context：

- `skill_content`
- `selected_skill_metadata.description`
- `short_summary`
- `recent_messages_summary`
- `lightweight_knowledge_hints`
- `mock_knowledge_hint`
- `allowed_tools`
- `intent`
- `rewritten_query`

## 哪些只是结构化上下文

以下字段当前只是结构化上下文，不是 prompt：

- `request_id`
- `trace_id`
- `session_key`
- `tenant_id`
- `user_id`
- `available_subagents`
- `available_tools`
- `selected_skill_score`
- `selected_skill_reason`

## 后续 Prompt 模板建议

如果后续让 ContextBuilder 构造 LLM messages，建议分为主 Agent 和子 Agent 两类。

### Orchestrator System Prompt 建议

```text
你是企业健康险个险业务 Agent 平台的主协调 Agent。
你只负责任务协调、上下文准备和子 Agent 路由，不承担深度业务排查。

你必须：
1. 使用 rewritten_query 和 intent 作为路由依据。
2. 不直接调用工具。
3. 不编造日志、知识库或渠道 trace。
4. 对需要专业处理的任务交给固定子 Agent。
```

### SubAgent System Prompt 建议

```text
你是 {agent_name}。
你必须遵循 selected skill 的指令完成任务。

selected_skill:
{skill_content}

allowed_tools:
{allowed_tools}

要求：
1. 只能使用 allowed_tools 中的工具。
2. 工具调用必须经过 ToolCallingRunner / ToolExecutor。
3. 结论必须区分证据和推断。
4. 输出必须包含 answer、diagnosis、evidence、recommendation、responsibility、confidence。
```

## 推荐 LLM Messages 结构

```json
[
  {"role": "system", "content": "{system_prompt}"},
  {"role": "user", "content": "{task_query}"},
  {"role": "user", "content": "{structured_context_json}"}
]
```

该结构只是后续建议，当前未实现。
