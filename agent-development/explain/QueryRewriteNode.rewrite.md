# query 改写

## 入参
- original_query=state["original_query"],
- recent_messages=state.get("recent_messages", []),
- short_summary=state.get("short_summary"),
- session_key=state["session_key"],

## 抽取实体
1. 从`original_query`抽取得到 `current_bag`
2. 从`short_summary`和`recent_messages`抽取得到 `history_bag`

## 组装 ConversationWindow
```python
window = ConversationWindow(
    session_key=session_key,
    summary=short_summary,
    recent_turns=recent_messages or [],
    entity_bag=window_bag,
)
```
- window_bag 是历史实体 + 当前实体，是给 LLM rewrite 和后续节点看的上下文窗口

## llm 改写
1. 入参
```python
self._rewrite_with_llm(MESSAGES[original_query, current_bag, window])
```
2. 提示词
3. llm 结果解析

## llm 改写失败，fallback 兜底（规则）
1. 如果当前 query 已经抽到实体，则不是追问
2. 如果是追问且当前没有实体，就尝试从 history_bag 继承唯一高置信实体
3. 如果历史里同一实体类型有多个候选，比如多个 policy_no，就进入 clarification
4. 如果完全继承不到，也进入 clarification

## 返回 query改写结果
- return QueryRewriteResult

## 疑问
- 对于返回值的实体，有`entities`,`inherited_entities`,`missing_required_entities`,`entity_bag`,这些区别是什么？有哪些是必要的，哪些是后续需要用的？

## 回答实体
- `entities`: 给后续业务节点快速消费的紧凑实体
```
{
  "policy_no": "P001"
}
```
- `entity_bag`: 给理解、继承、澄清、调试用的完整实体结构
```
{
  "entities": {
    "policy_no": [
      {
        "type": "policy_no",
        "value": "P001",
        "normalized_value": "P001",
        "confidence": 0.85,
        "source": "current_query",
        "turn_id": null,
        "sensitive": false,
        "metadata": {
          "description": "..."
        }
      }
    ]
  }
}
```
- query rewrite 阶段的 `missing_required_entities` 不是最终业务 skill 缺参判断；真正决定“能不能执行 skill/tool”的 required entity check 在子 Agent 选中 skill 后进行。