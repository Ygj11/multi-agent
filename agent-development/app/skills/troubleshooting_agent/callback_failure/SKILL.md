---
skill_id: troubleshooting_agent.callback_failure
name: ??????
description: ??????????????????????????????????????
agent: troubleshooting_agent
intent_tags:
  - troubleshooting
  - callback_failure
  - ????
  - ????
required_entities:
  - request_id
optional_entities:
  - policy_no
  - interface_name

private_tools:
  - query_internal_log
enabled: true
is_default: false
business_domain:
  - health_insurance_onboarding
required_context:
  - request_id
routing_keywords:
  - callback
  - 回调
  - 回调失败
  - 回调超时
  - 渠道未收到回调
routing_negative_keywords:
  - 字段缺失
  - 保全任务完成
---

# 回调失败排查 Skill

当问题包含回调失败、回调超时、渠道未收到回调或回调验签失败时，使用本 skill。

执行步骤：

1. 确认主请求是否成功进入出单或承保后续流程。
2. 查询内部日志中的回调发送记录、HTTP 状态码和错误摘要。
3. 必要时通过 MCP/HTTP 工具查询渠道侧是否收到回调。
4. 输出回调链路证据、失败位置、重试建议和渠道联调动作。


