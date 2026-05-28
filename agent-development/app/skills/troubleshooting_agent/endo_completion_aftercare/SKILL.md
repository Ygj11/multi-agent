---
skill_id: troubleshooting_agent.endo_completion_aftercare
name: 保全任务完成后异常处理
description: 处理保全任务完成后保单信息未更新、保单未解锁、未发起退费、未发短信等问题，通过 apply_seq 查询任务节点状态，并根据 9/10/11 节点状态和 response_body 触发对应通知或恢复工具。
agent: troubleshooting_agent
intent_tags:
  - troubleshooting
  - endo_completion
  - 保全
  - 保全任务完成
  - 保单信息未更新
  - 保单未解锁
  - 未发起退费
  - 没有发短信
  - E08
  - 财务创单
  - 收退费
required_entities:
  - apply_seq
  - policy_no
  - endorseType
optional_entities:
  - task_type
  - task_status
  - response_body
private_tools:
  - query_endo_task_record
  - notice_policy_update
  - notice_customer_update
  - notice_period_update
  - policy_suspendOrRecovery
  - notice_finance
enabled: true
is_default: false
business_domain:
  - health_insurance_endorsement
required_context:
  - apply_seq
  - policy_no
  - endorseType
---

# 保全任务完成后异常处理 Skill

## 适用场景

当用户询问：
- 保全任务完成但保单信息未更新
- 保全任务完成但保单未解锁
- 保全任务完成但未发起退费
- 保全任务完成但没有发短信

优先使用本 skill。

## 必要实体

必须具备：
- apply_seq：保全受理号 / 申请流水号
- policy_no：保单号
- endorseType：保全项

如果缺少任何一个，先澄清，不要直接调用处理工具。

字段映射：
- policy_no -> policyNo
- policy_no -> polno（仅当下游工具要求 polno 时使用）
- endorseType -> endorseType
- apply_seq -> apply_seq

## 通用步骤

1. 调用 `query_endo_task_record`，参数 `apply_seq`。
2. 从返回结果中查看节点：
   - 9 节点：更新保单、客户、账期
   - 10 节点：财务创单，进行收退费
   - 11 节点：保单恢复，发送 E08 消息
3. 节点状态字段：
   - `task_type`：节点类型
   - `task_status`：节点状态，E=失败，S=成功
   - `response_body`：节点响应内容
4. 根据用户问题和节点状态选择后续工具。

## 处理规则

### 保单信息未更新

查看 task_type=9 的节点。

如果 task_status=S：
- 说明 9 节点成功，不要重复通知。
- 回答用户 9 节点已成功，并提示继续核查下游同步或展示延迟。

如果 task_status=E：
- 查看 response_body。

如果 response_body 包含“保单更新错误”：
- 调用 `notice_policy_update`
- 参数：

```json
{
  "apply_seq": "<apply_seq>",
  "policyNo": "<policy_no>",
  "endorseType": "<endorseType>"
}
```

如果 response_body 包含“调用新客户接口异常”：
- 调用 `notice_customer_update`
- 参数：

```json
{
  "apply_seq": "<apply_seq>",
  "policyNo": "<policy_no>",
  "endorseType": "<endorseType>"
}
```

如果 response_body 包含“账单更新异常，失败”：
- 调用 `notice_period_update`
- 参数：

```json
{
  "apply_seq": "<apply_seq>",
  "policyNo": "<policy_no>",
  "endorseType": "<endorseType>"
}
```

### 保单未解锁

查看 task_type=11 的节点。

如果 task_status=E：
- 调用 `policy_suspendOrRecovery`
- 参数：

```json
{
  "handleType": "recovery",
  "premHandleFlag": "Y",
  "reqList": [
    {
      "policyInfo": [
        {
          "policyNo": "<policy_no>"
        }
      ]
    }
  ]
}
```

如果 task_status=S：
- 说明 11 节点成功，保单恢复和 E08 消息已处理。
- 不要重复调用恢复工具。

### 未发起退费

查看 task_type=10 的节点。

如果 task_status=E：
- 调用 `notice_finance`
- 参数：

```json
{
  "apply_seq": "<apply_seq>",
  "policyNo": "<policy_no>",
  "endorseType": "<endorseType>"
}
```

如果 task_status=S：
- 说明财务创单节点成功，不要重复通知。

### 没有发短信

短信发送依赖 E08 MQ。

查看 task_type=11 的节点。

如果 task_status=E：
- 按“保单未解锁”的逻辑处理，调用 `policy_suspendOrRecovery`。

如果 task_status=S：
- 说明 E08 MQ 理论上已发送。
- 不要重复恢复，提示继续核查短信平台或消息消费侧。

## 输出要求

最终回答必须包含：

1. 用户问题对应的异常场景
2. 查询到的节点状态
3. response_body 关键内容
4. 已调用或建议调用的处理工具
5. 工具处理结果
6. 如果证据不足，说明还缺少哪些信息
