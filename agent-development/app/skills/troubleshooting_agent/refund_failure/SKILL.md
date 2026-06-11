---
skill_id: troubleshooting_agent.refund_failure
name: 退保失败排查
description: 用于排查保单退保没有成功、退保任务卡住、退保回调异常等问题
agent: troubleshooting_agent
intent: troubleshooting
sub_intents:
  - refund_failure
intent_tags:
  - troubleshooting
  - refund_failure
  - 退保失败
  - 退保没有成功
required_entities:
  - policy_no
optional_entities:
  - request_id
  - task_id
  - node_name

private_tools:
  - query_task_status
  - query_node_status
  - query_internal_log
enabled: true
is_default: false
business_domain:
  - health_insurance_onboarding
required_context:
  - policy_no
routing_keywords:
  - 退保
  - 退款
  - refund
  - 退费
  - 退保失败
routing_negative_keywords:
  - E102
  - 签名
  - 回调失败
  - 字段缺失
  - 保全任务完成
---

# 退保失败排查 Skill

当用户描述退保没有成功、退保任务卡住、退保回调未完成或需要查询退保任务链路时，使用本 skill。

执行步骤：

1. 先确认保单号或可关联的请求流水号。
2. 查询任务状态和节点状态，定位退保任务当前卡点。
3. 如有 request_id，再结合内部日志确认接口错误、回调状态和重试记录。
4. 输出任务状态、卡点、建议动作和需要用户或渠道补充的信息。
