# 发现 子agent

## 意义
- 从 `app/agents/cards/*.yaml` 加载可使用的 `子agent`，形成 json格式存入 `state`
```python
payload = [card.model_dump() for card in cards]
```

## 入参
- 空

## 抽取实体（重新抽取）
1. 从`original_query` 和 `rewritten_query`抽取得到 `extracted_bag`
2. `extracted_bag` 合并 `紧凑实体` 得到 `entities` 传递给 llm

## 组装 ConversationWindow
- 无

## llm
- 无



## 返回结果
- return IntentResult
```python
list[AgentCard]
```

## 读取
- AgentCard YAML 不是每个节点都实际读取一次；当前实现是第一次读取后缓存，后续节点复用缓存。
