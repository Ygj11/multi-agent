# 整个 MainGraph 的总体职责
```text
请求进入
→ 恢复会话
→ 保存用户原话
→ 查询改写和实体收敛
→ 意图识别
→ 构建上下文
→ 选择子 Agent
→ 子 Agent 执行
→ 审批判断
→ 任务完成度验收
→ 必要时修复
→ 最终合规验证
→ 保存回复
→ 压缩记忆
→ 返回结果
```

## 主 Graph 的所有节点和条件边集中在app/runtime/graph.py

## 条件路由的通用规则主要集中在：app/runtime/route_policy.py

## Graph State 定义在：app/runtime/graph_state.py

## 节点输入输出治理在：app/runtime/node_contracts.py

### conclusion
当前 MainGraph 一共注册了 26 个 LangGraph 节点。
ToolCallingRunner 内部虽然也有“LLM → Tool → Observation → LLM”的循环，但它不是 LangGraph 节点，而是 dispatch_agent 节点内部的一段 Agent Loop。