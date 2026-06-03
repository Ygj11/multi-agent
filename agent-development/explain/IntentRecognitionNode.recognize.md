# 意图识别

## 意义
1. `intent_recognition` 不负责“选哪个 Agent”，但它负责把用户问题先归类成“任务语义标签”。
2. `select_agent` 再根据这个语义标签 + 实体 + query + AgentCard 去选择最合适的 Agent。

## 入参
- original_query=state["original_query"],
- rewritten_query=state.get("rewritten_query", state["original_query"]),
- recent_messages=state.get("recent_messages", []),
- short_summary=state.get("short_summary"),
- current_entities=state.get("entities", {}),
- conversation_window=state.get("conversation_window", {}),
- agent_card_summaries=agent_summaries,

- state.get("entities", {}) --》 由此可见取得是 `query改写` 完成的 紧凑实体
- `agent_summaries` 取值 ，如：troubleshooting_agent.yaml
```
agent_summaries = [self._agent_card_summary(card) for card in self.agent_card_loader.list_available_agents()]

return {
    "agent_name": card.agent_name,
    "description": card.description,
    "supported_intents": card.supported_intents,
    "capabilities": card.capabilities,
    "required_entities": card.required_entities,
    "optional_entities": card.optional_entities,
    "examples": card.examples,
}
```
- 它(`agent_summaries`)不是完整 AgentCard，也不包含完整 tools schema / skill body，只是给 LLM 做意图分类参考的轻量摘要。

## 抽取实体（重新抽取）
1. 从`original_query` 和 `rewritten_query`抽取得到 `extracted_bag`
2. `extracted_bag` 合并 `紧凑实体` 得到 `entities` 传递给 llm

## 组装 ConversationWindow
```python
window = self._window(conversation_window, short_summary, recent_messages, extracted_bag)
```
- conversation_window 已经从 query rewrite 传过来了，就直接复用它。

## llm 意图识别
1. 入参
```python
self._recognize_with_llm(MESSAGES[original_query, rewritten_query, entities, window, agent_card_summaries])
```

2. 提示词
- 语义判断，非强制

3. llm 结果解析

## llm 改写失败，fallback 兜底（规则）


## 返回 意图识别结果
- return IntentResult
```python
return IntentResult(
    intent=intent,
    sub_intent=data.get("sub_intent"),
    confidence=confidence,
    entities=merged_entities,
    missing_required_entities=[str(item) for item in data.get("missing_required_entities") or []],
    need_clarification=need_clarification,
    clarification_question=data.get("clarification_question"),
    is_follow_up=bool(data.get("is_follow_up", False)),
    reason=str(data.get("reason") or "llm_json_classification"),
    target_subagent=None,
)
```

## 疑问
- 结果的 `intent`是怎么得到的？
- 结果的 `sub_intent`是什么，怎么得到的？
- llm 是怎么取到这些返回值的？


## 答案
- llm 的自身语义判断


## 优化后
1. 动态构造候选空间 + 强提示词 + 轻量校验
2. 工程设计上，把 supported_intents 作为 intent 候选来源，把 capabilities 或更好的 Skill.intent_tags 作为 sub_intent 候选来源，并通过 prompt 做强约束，而不是让 LLM 自由编。

