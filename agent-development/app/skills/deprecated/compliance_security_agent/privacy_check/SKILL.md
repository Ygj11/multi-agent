---
skill_id: compliance_agent.deprecated_privacy_check
name: ????????
description: 用于检查身份证、手机号、健康告知、医疗记录、个人隐私和敏感健康信息
agent: compliance_agent
intent_tags:
  - deprecated
required_entities: []

private_tools: []
enabled: false
is_default: false
---

# 隐私信息检查 Skill

识别文本中的个人身份信息、联系方式、健康告知、病史、医疗记录和其他隐私数据。输出时必须脱敏，不得回显完整敏感值。
