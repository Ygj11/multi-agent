# 主 agent 构建上下文

## 初始化
- ContextBuilder.__init__ 只装配 SkillCatalog / SkillLoader / SkillSelector；不会初始化所有 Skill body。完整 Skill body 只在子 Agent 执行时，选中特定 Skill 后按需加载。

```txt
SkillCatalog：
  公司手册目录
  知道有哪些手册，每本手册标题、适用场景、需要什么资料

SkillSelector：
  根据当前问题，从目录里选一本最合适的手册

SkillLoader：
  把选中的那本手册正文打开给执行人员看
```

## 意义


## 入参
```python
original_query=state["original_query"],
rewritten_query=state.get("rewritten_query", state["original_query"]),
intent=state.get("intent", "unknown"),
sub_intent=state.get("sub_intent"),
entities=state.get("entities", {}),
entity_bag=state.get("entity_bag", {}),
conversation_window=state.get("conversation_window", {}),
session_key=state["session_key"],
recent_messages=state.get("recent_messages", []),
short_summary=state.get("short_summary"),
available_subagents=self.subagent_manager.list_agents(),
auth_context=state.get("auth_context"),
```

- 在 main.py 中，初始化了subagent_manager = build_subagent_manager(*) ，所以可以使用 self.subagent_manager.list_agents()

## 使用知识服务
- hints = await self.knowledge_hint_builder.build_lightweight_hints(*)
