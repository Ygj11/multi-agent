# 组装任务

## 意义
- 组装参数

## 入参
```python
selected_card=card,
orchestrator_context=context,
entities=state.get("entities", {}),
request_id=state["request_id"],
trace_id=state["trace_id"],
```

## 组装
- 会使用到 agentcard 的 `memory_policy` 字段

## 返回结果


