---
skill_id: compliance.privacy_check
name: 隐私信息检查
description: 用于检查身份证、手机号、健康告知、医疗记录、个人隐私和敏感健康信息
agent: compliance_security_agent
intent_tags:
  - compliance_review
  - privacy_check
  - 隐私
  - 身份证
  - 手机号
business_domain:
  - health_insurance_onboarding
required_context:
  - short_summary
enabled: true
is_default: true
---

# 隐私信息检查 Skill

识别文本中的个人身份信息、联系方式、健康告知、病史、医疗记录和其他隐私数据。输出时必须脱敏，不得回显完整敏感值。
