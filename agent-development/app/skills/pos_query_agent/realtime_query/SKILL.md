---
skill_id: pos_query_agent.realtime_query
name: 保全实时查询
description: 用于实时查询可做保全项、退保试算详情、保全保单标准信息、批文信息和退保提交校验。
agent: pos_query_agent
intent: pos_query
sub_intents:
  - pos_available_items
  - pos_surrender_premium_calc
  - pos_policy_standard_query
  - pos_approval_text_query
  - pos_submit_verify
intent_tags:
  - pos_query
  - pos_available_items
  - pos_surrender_premium_calc
  - pos_policy_standard_query
  - pos_approval_text_query
  - pos_submit_verify
  - 保全
  - 可做保全项
  - 退保试算
  - 保单查询
  - 批文查询
  - 提交校验
required_entities: []
optional_entities:
  - policy_no
  - customer_no
  - apply_seq
  - endorseType
  - applyDate
  - surDate
  - payMode
  - acceptDate
  - surrenderReason
  - taskSrc
  - operatorId
private_tools:
  - pos_query_available_items
  - pos_calc_surrender_premium
  - pos_query_policy_standard
  - pos_query_approval_text
  - pos_submit_verify
enabled: true
is_default: false
business_domain:
  - health_insurance_pos
required_context: []
routing_keywords:
  - 保全实时查询
  - 可做保全项
  - 退保试算
  - 试算详情
  - 批文
  - 批文查询
  - 保全批文
  - 提交校验
  - submitVerify
  - queryPreserveChangeDetail
routing_negative_keywords: []
---

# 保全实时查询 Skill

## 适用场景

当用户询问健康险保全实时接口查询时，优先使用本 skill。

覆盖场景：

- 查询保单线上可做保全项
- 查询退保试算详情
- 查询保全保单标准信息
- 通过受理号查询批文或保全变更详情
- 做退保任务提交前校验

## 总体原则

1. 先判断用户要查哪一类 POS 接口。
2. 不要因为缺少所有可能参数而直接澄清。
3. 只针对当前查询类型澄清该工具必需参数。
4. 所有工具都是 read 查询工具，不需要人工审批。
5. 工具返回后，不要原样输出完整 JSON；根据用户问题读取关键节点组织回答。
6. 如果接口返回包含敏感字段，最终仍由 VerificationService 做数据权限和合规过滤。

## 工具选择规则

### 线上可做保全项查询

用户表达：

- 可以做哪些保全项
- 可做保全项
- 这张保单能做什么保全

使用工具：

```text
pos_query_available_items
```

必要参数：

- policyNo：保单号
- customerNo：客户号

默认参数：

- src：16

缺少 policyNo 或 customerNo 时，先向用户澄清。

### 退保试算详情查询

用户表达：

- 退保试算
- 试算详情
- 退保金额
- 退保可以退多少钱

使用工具：

```text
pos_calc_surrender_premium
```

必要参数：

- applyDate：受理日期毫秒时间戳
- policyNo：保单号
- surDate：退保日期毫秒时间戳

默认参数：

- endorseType：001028
- taskSrc：01
- surrenderType：1
- commission：1
- operatorId：优先从 Principal.user_id 获取

缺少 applyDate、policyNo 或 surDate 时，先向用户澄清。

### 保全保单标准查询

用户表达：

- 保全保单查询
- 保单标准查询
- 查保单信息
- 查保单锁定或被保人扩展信息

使用工具：

```text
pos_query_policy_standard
```

必要参数：

- policyNo：保单号

工具内部字段映射：

```text
policyNo -> polNo
```

默认参数：

- withInsureds：Y
- extensions：pollist、assuredPolicyInfo、pollLock

### 批文查询

用户表达：

- 批文查询
- 保全批文
- 查询受理号对应批文
- 查询保全变更详情
- 受理号完成后的变更内容

使用工具：

```text
pos_query_approval_text
```

必要参数：

- applySeq：受理号

默认参数：

- pageSize：0
- pageNo：1
- operatorId：优先从 Principal.user_id 获取

### 退保任务提交校验

用户表达：

- 退保提交校验
- 提交前校验
- 支付方式校验
- 任务提交校验

使用工具：

```text
pos_submit_verify
```

必要参数：

- policyNo：保单号
- acceptDate：受理日期毫秒时间戳

默认参数：

- endorseType：001028
- payMode：Y
- surrenderReason：11
- taskSrc：31
- operatorId：优先从 Principal.user_id 获取

## 输出要求

最终回答应包含：

1. 本次查询类型。
2. 使用的接口工具名。
3. 关键入参，例如 policyNo、applySeq、endorseType。
4. 接口返回的关键节点或业务结论。
5. 如果接口返回失败，说明失败原因和下一步建议。
6. 如果证据不足，说明还缺少哪些参数。

不要输出完整原始 JSON，除非用户明确要求并且内容不包含敏感字段。
