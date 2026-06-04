# ToolCallingRunner

## loop
```TEXT
最多循环 limit 次
每一轮：
  1. 调 LLM
  2. 看 LLM 是直接回答，还是要调工具
  3. 如果要调工具，执行工具
  4. 把工具结果塞回 messages
  5. continue，进入下一轮，让 LLM 基于工具结果继续思考

```

## 工具结果追加回 messages
```PYTHON
messages.append({
    "role": "tool",
    "content": json.dumps(dumped, ensure_ascii=False, default=str),
})

```

## 停止条件
```TEXT
LLM 直接回答	return stopped_reason="final"
LLM 报错	return stopped_reason="error"
达到最大轮数	return stopped_reason="max_iterations"
工具需要人工审批	return stopped_reason="human_approval_required"
重复调用同一工具太多	max_duplicate_tool_calls
工具连续失败太多	max_consecutive_tool_failures
同一工具同参失败太多	max_same_tool_failures
```

## 工具执行 await self.tool_executor.execute

### 执行前的校验
1. 检查工具存在，agent存在。
2. 检查调用工具的参数是否完整
3. 检查权限是否足够使用工具，通过 principal 和 工具的required_scopes和resource_type 做比对，其定义是在registry中，目前默认为空，无校验。
4. _verify_pre_tool：跑多个验证器
5. （目前验证器有DataPermissionVerifier和ComplianceVerifier），验证器的stages，是规定在什么时候需要验证。如`pre_answer`，是写在 graph节点中的。
6. verify_all 负责按 stage 执行所有匹配的 verifier，并且 verifier 异常时 fail closed；aggregate 负责把多个 verifier 的结果汇总成一个最终决策：有 block/manual 就阻断，有 patch 就返回脱敏/改写结果，否则通过。

#### ComplianceVerifier校验
```text
拿到 answer
-> 可选调用 LLM 做 final_compliance scene
-> 用规则脱敏手机号/身份证/银行卡/token/secret
-> 脱敏内部日志敏感字段
-> 标记健康隐私内容
-> 如果发现原始工具输出，要求 retry
-> 返回 VerificationResult

```


#### DataPermissionVerifier校验
1. DataPermissionVerifier 根据 principal.data_permissions/scopes 决定是否脱敏
2. scopes 控制“能不能做某类动作”，data_permissions 控制“能看到哪些数据字段”