# dispatch_agent 节点详解

## 1. 这个节点做什么

`dispatch_agent` 是主流程中“把主 Agent 已经组装好的任务交给某个子 Agent 执行”的节点。

它本身不做意图识别、不重新选择 Agent、不直接调用工具。它主要完成三件事：

1. 从 graph state 里取出 `orchestrator_context` 和 `assembled_task`。
2. 调用 `DispatchAgentNode.dispatch(...)` 把 `AgentTaskEnvelope` 转成子 Agent 协议 `SubAgentTask`。
3. 通过 `SubAgentManager` 调用真正的子 Agent，例如 `troubleshooting_agent`。

代码位置：

- `app/runtime/graph.py::AgentGraphFactory.dispatch_agent`
- `app/agents/dispatcher.py::DispatchAgentNode.dispatch`
- `app/subagents/manager.py::SubAgentManager.call_subagent`
- `app/subagents/base.py::BaseSubAgent.run`

整体链路：

```text
AgentGraphFactory.dispatch_agent
  -> OrchestratorContext(**state["orchestrator_context"])
  -> AgentTaskEnvelope(**state["assembled_task"])
  -> DispatchAgentNode.dispatch(task, context)
  -> SubAgentManager.call_subagent(agent_name, SubAgentTask, parent_context)
  -> BaseSubAgent.run(...)
  -> ContextBuilder.build_for_subagent(...)
  -> SkillContextResolver.resolve(...)
  -> ToolCallingRunner.run(...) 或 do_run(...)
```

---

## 2. Graph 节点入参和出参

### 入参

`dispatch_agent` 读取 graph state 中的两个核心字段：

```python
context = OrchestratorContext(**state["orchestrator_context"])
task = AgentTaskEnvelope(**state["assembled_task"])
```

也就是说，它依赖前面节点已经完成：

```text
build_orchestrator_context
select_agent
assemble_task
```

关键输入大致是：

```json
{
  "orchestrator_context": {
    "original_query": "...",
    "rewritten_query": "...",
    "intent": "troubleshooting",
    "sub_intent": "endo_completion_aftercare",
    "entities": {
      "apply_seq": "APPLY_POLICY_UPDATE_FAIL",
      "policy_no": "P001",
      "endorseType": "退保"
    },
    "entity_bag": {},
    "recent_messages": [],
    "short_summary": null,
    "lightweight_knowledge_hints": [],
    "auth_context": {}
  },
  "assembled_task": {
    "agent_name": "troubleshooting_agent",
    "query": "...",
    "intent": "troubleshooting",
    "entities": {},
    "agent_card": {},
    "auth_context": {}
  }
}
```

### 出参

`dispatch_agent` 返回：

```python
return {
    "subagent_result": result.model_dump(),
    "answer": result.answer,
    "graph_path": self._append_path(state, "dispatch_agent"),
}
```

后续节点会根据 `subagent_result` 判断：

- 是否需要人工审批
- 是否需要最终验证
- 最终回答是什么

---

## 3. DispatchAgentNode 如何转换任务

代码位置：

`app/agents/dispatcher.py::DispatchAgentNode.dispatch`

它把主 Agent 组装出的 `AgentTaskEnvelope` 转成子 Agent 使用的 `SubAgentTask`：

```python
task = SubAgentTask(
    name=task_envelope.agent_name,
    query=task_envelope.query,
    intent=task_envelope.intent,
    session_key=task_envelope.session_key,
    original_query=task_envelope.original_query,
    entities=task_envelope.entities,
    task_id=task_envelope.task_id,
    metadata={
        **task_envelope.metadata,
        "agent_card": task_envelope.agent_card.model_dump(),
        "auth_context": task_envelope.auth_context,
    },
)
```

这里有两个重要点：

1. `agent_card` 会进入 `SubAgentTask.metadata`，子 Agent 后续会用它读取自己的能力边界、工具、skills。
2. `auth_context` 也会进入 `SubAgentTask.metadata`，后续工具可见性和工具执行权限会从这里取 `principal`。

`SubAgentTask` 是子 Agent 的执行任务，不是主流程 state。它更偏运行时任务对象。

---

## 4. SubAgentManager 如何找到子 Agent

代码链路：

```text
DispatchAgentNode.dispatch
  -> self.subagent_manager.call_subagent(task_envelope.agent_name, task, parent_context)
```

`SubAgentManager` 内部维护了一个子 Agent 注册表。

应用启动时，`main.py` / bootstrap 代码会注册这些子 Agent。运行时根据 `agent_name` 找到对应实例。

例如：

```text
agent_name = "troubleshooting_agent"
  -> 找到 TroubleshootingAgent 实例
  -> 调用 agent.run(task, parent_context)
```

如果找不到对应 Agent，一般会抛错或返回失败结果，具体取决于 `SubAgentManager` 当前实现。

---

## 5. BaseSubAgent.run 的整体模板

代码位置：

`app/subagents/base.py::BaseSubAgent.run`

大部分子 Agent 继承 `BaseSubAgent`，所以真正执行时会走统一模板：

```text
BaseSubAgent.run
  -> get_agent_card(task)
  -> get_available_tool_names(agent_card)
  -> ContextBuilder.build_for_subagent(...)
  -> 如果 need_clarification，直接返回澄清 SubAgentResult
  -> 如果启用 ToolCallingRunner，构造 messages + tools schema
  -> ToolCallingRunner.run(...)
  -> build_result_from_runner(...)
  -> 否则走 do_run(...)
```

也就是说，`BaseSubAgent.run` 是子 Agent 执行的统一骨架。

---

## 6. 获取 AgentCard

子 Agent 不重新从 YAML 读取 AgentCard，而是从 `SubAgentTask.metadata["agent_card"]` 中恢复：

```python
def get_agent_card(self, task: SubAgentTask) -> AgentCard | None:
    data = task.metadata.get("agent_card")
    return AgentCard(**data) if isinstance(data, dict) else None
```

这里的 AgentCard 来源是前面 `assemble_task` 节点放入 `AgentTaskEnvelope` 的 selected card。

AgentCard 对子 Agent 很重要，因为它定义了：

- `agent_name`
- `description`
- `private_tools`
- `public_tools_allowed`
- `mcp_tools`
- `mcp_tool_scopes`
- `skills`
- `rag_namespaces`
- `access_policy`

---

## 7. 获取当前子 Agent 可见工具

代码位置：

`app/subagents/base.py::BaseSubAgent.get_available_tool_names`

```python
allowed_tools = self.get_available_tool_names(agent_card)
```

它调用 ToolRegistry：

```python
self.tool_executor.registry.list_available_tools_for_agent(self.name, agent_card)
```

这个阶段只是得到工具名列表，主要用于放入 `SubAgentContext.allowed_tools`。

工具可见性主要由这些因素决定：

1. `AgentCard.private_tools`
2. `AgentCard.public_tools_allowed`
3. `AgentCard.mcp_tools`
4. `AgentCard.mcp_tool_scopes`
5. ToolRegistry 中工具是否真实注册
6. ToolDefinition 是否 `enabled=True`

真正传给 LLM 的工具 schema 会在后面调用：

```python
tool_schemas = self.get_available_tool_schemas(agent_card, principal=principal)
```

这个会额外考虑当前用户权限。

---

## 8. 构建 SubAgentContext

代码位置：

`app/runtime/context_builder.py::ContextBuilder.build_for_subagent`

```python
sub_context = await self.context_builder.build_for_subagent(
    task=task,
    parent_context=parent_context,
    allowed_tools=allowed_tools,
)
```

`SubAgentContext` 是子 Agent 执行前的完整上下文，包含：

```text
task
rewritten_query
intent
allowed_tools
skill_content
selected_skill_id
selected_skill_metadata
skill_selection_score
skill_selection_reason
missing_required_entities
need_clarification
clarification_question
knowledge_hint
auth_context
```

这里最关键的是：

```text
Skill 选择
Skill 正文加载
Skill required_entities 检查
Knowledge hint 构建
```

---

## 9. Skill 选择的完整流程

代码位置：

- `app/runtime/context/skill_context_resolver.py::SkillContextResolver.resolve`
- `app/skills/selector.py::SkillSelector.select`
- `app/skills/scorer.py::SkillRuleScorer.score`
- `app/skills/reranker.py::SkillLLMReranker.rerank`
- `app/skills/selection_policy.py::SkillSelectionPolicy.decide`

### 9.1 构建 SkillSelectionContext

```python
selection_context = self.build_selection_context(task=task, parent_context=parent_context)
```

`SkillSelectionContext` 是给 SkillSelector 的输入。它不是完整 graph state，而是挑出 skill 选择需要的字段：

```python
SkillSelectionContext(
    agent_name=task.name,
    intent=task.intent,
    sub_intent=parent_context.sub_intent,
    original_query=task.original_query,
    rewritten_query=parent_context.rewritten_query,
    session_key=task.session_key,
    entities=task.entities,
    entity_bag=parent_context.entity_bag,
    short_summary=parent_context.short_summary,
    recent_messages_summary=recent_summary[:2000],
    lightweight_knowledge_hints=parent_context.lightweight_knowledge_hints,
    request_id=task.metadata.get("request_id"),
    trace_id=task.metadata.get("trace_id"),
    extracted_error_code=self.extract_error_code(query),
    extracted_request_id=self.extract_request_id(query),
    extracted_interface_name=self.extract_interface_name(query),
)
```

重点字段说明：

| 字段 | 作用 |
|---|---|
| `intent` | 主流程识别出的粗粒度意图 |
| `sub_intent` | 更细的业务子意图 |
| `entities` | 当前任务紧凑实体 dict，例如 `policy_no/apply_seq` |
| `entity_bag` | 多来源、多候选、带置信度的完整实体袋 |
| `short_summary` | 短期记忆摘要 |
| `recent_messages_summary` | 最近几轮消息压缩成的文本 |
| `lightweight_knowledge_hints` | 主流程预检索的轻量知识提示 |
| `extracted_error_code` | 额外从 query 中提取的错误码强信号，例如 `E102` |
| `extracted_request_id` | 额外从 query 中提取的请求号强信号，例如 `REQ_001` |
| `extracted_interface_name` | 额外从 query 中提取的接口名强信号，目前只识别 `submitProposal` |

这三个 `extracted_*` 字段不是最终实体权威来源，只是 Skill 规则打分阶段的辅助强信号。

### 9.2 构建候选 Skill metadata

```python
candidates = self.build_candidates(task=task)
```

内部逻辑：

```python
agent_card_data = task.metadata.get("agent_card")
allowed_skill_ids = set(agent_card_data.get("skills", [])) if isinstance(agent_card_data, dict) else set()
candidates = self.skill_catalog.list_skills(task.name)
if allowed_skill_ids:
    candidates = [candidate for candidate in candidates if candidate.skill_id in allowed_skill_ids]
```

这里有两层过滤：

1. `SkillCatalog.list_skills(task.name)`：列出 metadata 中 `agent == task.name` 的 skill。
2. `AgentCard.skills` 白名单过滤：只有被当前 AgentCard 声明的 skill_id 才能进入候选。

所以候选 skill 必须同时满足：

```text
SKILL.md frontmatter: agent = 当前子 Agent
AgentCard.yaml: skills 包含这个 skill_id
```

这可以防止某个 SKILL.md 误写 agent 后自动进入执行链路。

### 9.3 SkillSelector 只使用 metadata，不读取正文

```python
selection = await self.skill_selector.select(
    agent_name=task.name,
    context=selection_context,
    candidates=candidates,
)
```

这里传入的是 `list[SkillMetadata]`，不是完整 `SKILL.md` body。

也就是说，选择 skill 时 LLM 看不到完整 SOP 内容，只能看到 metadata，例如：

```text
skill_id
name
description
agent
intent_tags
required_entities
optional_entities
required_context
business_domain
private_tools
public_tools
mcp_tools
```

这是 metadata-first / progressive disclosure 的设计：

```text
先用轻量 metadata 选 skill
选中后才加载完整 skill body
```

### 9.4 规则打分

`SkillSelector.select` 先调用：

```python
scored = [self.scorer.score(context, candidate) for candidate in candidates]
```

规则打分在 `app/skills/scorer.py::SkillRuleScorer.score`。

当前主要打分信号：

| 信号 | 加分逻辑 |
|---|---|
| `intent` 命中 `skill.intent_tags` | 加分 |
| `sub_intent` 命中 `skill.intent_tags` | 加分 |
| query 中出现 skill 的 intent tag | 加分 |
| query token 命中 skill description | 加分 |
| `skill.required_entities` 已存在 | 加分 |
| `skill.optional_entities` 已存在 | 加分 |
| `skill.required_context` 满足 | 加分 |
| `business_domain` 匹配 | 加分 |
| `extracted_interface_name` 出现在 skill metadata | 加分 |
| `extracted_error_code` 出现在 skill metadata | 加分 |
| domain-specific 规则，如签名、缺字段、回调、退保、保全完成后异常 | 加分 |

注意：这里仍然只看 metadata，不看 skill body。

### 9.5 LLM rerank

规则打分后，如果不够确定，会尝试 LLM 语义重排：

```python
rerank_attempted = self.reranker.should_rerank(context, scored)
```

触发条件包括：

```text
有多个候选
llm_provider 存在
Top1 分数低于 confident threshold
Top1 和 Top2 分差小
query 有语义复杂信号，例如“但是/却/没有/未/完成/成功”
query 较长
```

LLM rerank 只接收 Top-K skill metadata summary：

```python
summaries = [self.metadata_summary(item.skill, item.score, item.reason) for item in top_scored]
```

LLM 必须返回 JSON：

```json
{
  "selected_skill_id": "troubleshooting_agent.endo_completion_aftercare",
  "confidence": 0.86,
  "reason": "..."
}
```

校验规则：

1. `selected_skill_id` 必须来自 Top-K 候选。
2. JSON 解析失败，返回 None。
3. confidence 低于阈值，返回 None。
4. 选择非法 skill_id，返回 None。

如果 LLM rerank 不可用或结果非法，会 fallback 到规则 Top1。

### 9.6 最终决策和 fallback generic execution

最终由：

```python
SkillSelectionPolicy.decide(...)
```

决定。

如果最终分数低于 `min_confident_score`，会选择默认 skill，但标记：

```python
fallback=True
```

随后 `SkillContextResolver.resolve` 会走：

```python
if selection.fallback:
    return SkillResolution(
        selection=selection,
        skill_content=self.generic_skill_content,
        entity_check=None,
    )
```

这很关键：

> 没有匹配到具体 skill，不代表子 Agent 不执行。

如果 `fallback=True`，系统会使用一段通用 skill content：

```text
No specific Skill matched confidently. Use the AgentCard, user query,
conversation context, and visible tools to reason and answer.
```

这种情况下：

- `selected_skill_id = None`
- 不加载任何具体 SKILL.md body
- 不检查某个具体 skill 的 required_entities
- 子 Agent 仍可以继续使用 LLM + tools loop

所以当前设计不是“每个问题都必须匹配 skill”。准确说是：

```text
匹配到具体 skill：按该 skill SOP + required_entities 执行
没匹配到具体 skill：走 generic subagent execution，由 AgentCard + query + context + tools 驱动 LLM loop
```

---

## 10. 加载选中 Skill body

只有在 `selection.fallback == False` 时，才加载完整 skill body：

```python
loaded_skill = self.skill_loader.load(selection.selected_skill_id)
```

这一步对应：

```text
selected skill metadata 已经确定
现在才读取对应 SKILL.md 完整正文
```

完整 skill body 后续会进入：

```python
SubAgentContext.skill_content
```

并最终进入 BaseSubAgent 的 system prompt：

```python
f"Skill body:\n{sub_context.skill_content}"
```

---

## 11. 实体检查 required_entities

代码位置：

- `app/runtime/context/skill_context_resolver.py::SkillContextResolver.resolve`
- `app/skills/required_entities.py::RequiredEntityChecker.check`

实体检查只在选中了具体 skill 时执行：

```python
entity_check = self.required_entity_checker.check(
    skill=selection.selected_skill_metadata,
    entities=task.entities,
    entity_bag=entity_bag,
)
```

### 11.1 task.entities 是什么

`task.entities` 是当前任务的紧凑实体 dict。

例如：

```json
{
  "apply_seq": "APPLY_POLICY_UPDATE_FAIL",
  "policy_no": "P001",
  "endorseType": "退保"
}
```

特点：

- 简单 dict
- 当前任务执行优先使用
- 适合判断工具参数是否具备
- 一般来自 query rewrite / intent recognition / assemble_task

### 11.2 entity_bag 是什么

`entity_bag` 是完整实体袋，来自：

```python
parent_context.entity_bag
```

它支持多来源、多候选、置信度、敏感标记。

代码会把当前任务实体也合进去：

```python
entity_bag = EntityBag(**parent_context.entity_bag) if parent_context.entity_bag else EntityBag()
entity_bag.merge(EntityBag.from_compact_dict(task.entities, source="rule", confidence=0.9))
```

所以检查时既能用当前任务实体，也能用历史上下文里的实体。

### 11.3 检查逻辑

`RequiredEntityChecker.check` 遍历：

```python
for entity_type in skill.required_entities:
```

每个必需实体按顺序检查：

1. 如果 `task.entities` 已经有值，直接通过。
2. 如果没有，则看 `entity_bag` 是否有唯一高置信候选。
3. 如果有唯一高置信候选，则继承到 `merged`。
4. 如果有多个候选，标记 ambiguous，需要澄清。
5. 如果没有候选，标记 missing，需要澄清。

伪代码：

```text
for required_entity in skill.required_entities:
  if task.entities 有值:
      ok
  elif entity_bag 有唯一高置信值:
      继承这个值
  elif entity_bag 有多个候选:
      need_clarification = True，问用户明确哪一个
  else:
      need_clarification = True，问用户补充缺失参数
```

### 11.4 示例：保全任务完成后异常处理

`troubleshooting_agent.endo_completion_aftercare` 的 required_entities 可能是：

```yaml
required_entities:
  - apply_seq
  - policy_no
  - endorseType
```

如果用户输入：

```text
保全任务完成了，但是保单信息没有更新，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001，保全项退保
```

则 `task.entities` 可能是：

```json
{
  "apply_seq": "APPLY_POLICY_UPDATE_FAIL",
  "policy_no": "P001",
  "endorseType": "退保"
}
```

检查结果：

```json
{
  "missing_required_entities": [],
  "need_clarification": false,
  "clarification_question": null
}
```

如果用户只说：

```text
保全完成后保单没更新
```

则缺少：

```text
apply_seq
policy_no
endorseType
```

返回：

```json
{
  "missing_required_entities": ["apply_seq", "policy_no", "endorseType"],
  "need_clarification": true,
  "clarification_question": "执行 保全任务完成后异常处理 还缺少 保全受理号 apply_seq、保单号 policy_no、保全项 endorseType，请补充后我再继续处理。"
}
```

如果历史中有唯一高置信 `policy_no=P001`，但当前缺 `apply_seq`，则会继承 `policy_no`，只要求用户补 `apply_seq` 和其他缺失字段。

如果历史中有多个保单号，例如 `P001/P002`，则不会乱猜，会要求用户明确。

---

## 12. 如果需要澄清，会不会继续 tool loop

不会。

`BaseSubAgent.run` 在拿到 `sub_context` 后先判断：

```python
if sub_context.need_clarification:
    return SubAgentResult(...)
```

这意味着：

```text
选中了具体 skill
但是该 skill.required_entities 缺失或歧义
  -> 子 Agent 直接返回澄清问题
  -> 不构造 LLM messages
  -> 不调用 ToolCallingRunner
  -> 不调用工具
```

这和 fallback generic execution 不一样：

| 情况 | 是否检查 required_entities | 是否继续 LLM + tools loop |
|---|---|---|
| 没有匹配到具体 skill，fallback=True | 否 | 是 |
| 匹配到具体 skill，但缺 required_entities | 是，失败 | 否，返回澄清 |
| 匹配到具体 skill，实体齐全 | 是，通过 | 是 |

---

## 13. 构造 LLM messages 和 tools schema

如果不需要澄清，并且：

```python
self.use_tool_calling_runner
self.tool_calling_runner is not None
agent_card is not None
```

则进入 ToolCallingRunner。

### 13.1 构造 messages

代码位置：

`app/subagents/base.py::BaseSubAgent.build_messages`

system message 包含：

```text
You are {agent_name}. {agent_card.description}
Use only the provided tools.
Skill body:
{sub_context.skill_content}
```

user message 包含：

```text
Original query
Rewritten query
Intent
Entities
Short summary
Lightweight hints
```

所以如果选中了具体 skill，完整 SOP 会进入 system prompt。

如果是 fallback generic execution，则 system prompt 里的 Skill body 是通用执行说明，而不是某个 SKILL.md 正文。

### 13.2 构造 tools schema

代码：

```python
principal = principal_dict_from_auth_context(task.metadata.get("auth_context"))
tool_schemas = self.get_available_tool_schemas(agent_card, principal=principal)
```

这里会调用 ToolRegistry：

```text
AgentCard 工具可见性
+ ToolDefinition.enabled
+ 当前用户权限 AuthorizationService
-> OpenAI function-calling schema
```

最终传给 LLM 的不是工具对象，也不是 Python 函数，而是标准 function schema：

```json
{
  "type": "function",
  "function": {
    "name": "query_endo_task_record",
    "description": "...",
    "parameters": {
      "type": "object",
      "properties": {},
      "required": []
    }
  }
}
```

---

## 14. ToolCallingRunner 是真正的 loop

代码入口：

```python
run_result = await self.tool_calling_runner.run(...)
```

这里才是真正的 LLM + tools loop。

大体循环：

```text
LLMProvider.chat(messages, tools)
  -> 如果 LLM 返回 final answer，结束
  -> 如果 LLM 返回 tool_call
      -> ToolExecutor.execute(...)
      -> 工具结果作为 observation 追加回 messages
      -> 进入下一轮 LLMProvider.chat
  -> 如果遇到 human_approval_required
      -> 停止 loop，交给主 graph 审批分支
  -> 如果达到 max_iterations / 重复工具 / 连续失败
      -> 停止 loop，返回可控错误
```

`BaseSubAgent.build_result_from_runner` 会把 `ToolCallingRunResult` 包装成 `SubAgentResult`。

如果遇到写工具审批：

```python
needs_approval = run_result.needs_human_approval or run_result.stopped_reason == "human_approval_required"
```

返回的 `SubAgentResult` 会包含：

```text
needs_human_approval=True
approval_payloads
pending_tool_call
pending_messages
pending_tools
```

后续主 Graph 的：

```text
check_human_approval_required
create_approval_request
submit_approval_request
pause_for_approval
```

会处理审批。

---

## 15. dispatch_agent 的完整分支总结

```text
dispatch_agent
  -> DispatchAgentNode.dispatch
  -> SubAgentManager.call_subagent
  -> BaseSubAgent.run
      -> get_agent_card
      -> get_available_tool_names
      -> ContextBuilder.build_for_subagent
          -> SkillContextResolver.resolve
              -> build_selection_context
              -> build_candidates
              -> SkillSelector.select
                  -> rule scoring
                  -> optional LLM rerank
                  -> selection policy
              -> if fallback:
                    generic skill content
                    no required entity check
                 else:
                    load selected SKILL.md body
                    RequiredEntityChecker.check
          -> build subagent knowledge hint
          -> return SubAgentContext
      -> if need_clarification:
            return clarification SubAgentResult
         elif use ToolCallingRunner:
            build messages
            build tool schemas
            ToolCallingRunner.run
            build SubAgentResult
         else:
            do_run fallback
```

---

## 16. 关键概念区分

### selected_agent 和 selected_skill

`selected_agent` 是主 Agent 选择哪个子 Agent。

例如：

```text
troubleshooting_agent
```

`selected_skill` 是子 Agent 内部选择哪个具体技能 SOP。

例如：

```text
troubleshooting_agent.endo_completion_aftercare
```

先有 Agent，再在该 Agent 内选择 Skill。

### 没有匹配 Skill 不等于不能执行

如果没有具体 skill 高置信匹配：

```text
selection.fallback=True
```

系统会走 generic subagent execution，仍然可以：

- 用 AgentCard 描述
- 用用户 query
- 用上下文
- 用可见工具
- 让 LLM 自己判断是否调用工具或直接回答

### 匹配 Skill 但缺实体才会澄清

只有当：

```text
选中了具体 skill
且 skill.required_entities 缺失或歧义
```

才会触发 clarification。

这避免了“所有问题都必须满足某个 skill 的实体要求”的错误设计。

### task.entities 和 entity_bag

| 对象 | 作用 |
|---|---|
| `task.entities` | 当前任务已确认的紧凑实体 dict，执行优先使用 |
| `entity_bag` | 多来源、多候选实体池，用于继承、补全、判断歧义 |

实体检查时先看 `task.entities`，不够再从 `entity_bag` 找唯一高置信候选。

---

## 17. 本节点不做的事情

`dispatch_agent` 不负责：

1. 不重新识别 intent。
2. 不重新选择 Agent。
3. 不直接执行工具。
4. 不直接创建审批单。
5. 不直接做最终回复验证。
6. 不把所有 skill body 塞给 LLM。
7. 不把所有工具暴露给 LLM。

它只是把已经选好的任务交给子 Agent，并由子 Agent 的统一模板完成 skill/context/tool loop。


## 18. 优化
- 下一层企业级增强会是补一套 skill routing evaluation/badcase 数据集，用真实业务样本校准这些权重。