---
skill_id: troubleshooting_agent.missing_field
name: ??????
description: ???? submitProposal ??????????????appId ???????????????
agent: troubleshooting_agent
intent: troubleshooting
sub_intents:
  - missing_field
intent_tags:
  - troubleshooting
  - missing_field
  - ????
  - ??
  - submitProposal
required_entities:
  - interface_name
optional_entities:
  - error_code

private_tools:
  - query_internal_log
enabled: true
is_default: false
business_domain:
  - health_insurance_onboarding
required_context:
  - interface_name
routing_keywords:
  - appId
  - field
  - 字段
  - 字段缺失
  - 不能为空
  - 必填字段
routing_negative_keywords:
  - E102
  - 回调失败
  - 保全任务完成
---

# 字段缺失排查 Skill

当问题包含字段缺失、不能为空、必填字段、字段映射或请求报文不完整时，使用本 skill。

执行步骤：

1. 先确认接口名和缺失字段名。
2. 对照接口文档或知识库中的字段要求。
3. 检查渠道报文字段映射、空值处理和字段命名大小写。
4. 输出缺失字段、影响接口、疑似责任方和补充字段建议。

