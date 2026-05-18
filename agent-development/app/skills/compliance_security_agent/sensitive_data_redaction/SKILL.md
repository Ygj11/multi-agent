---
skill_id: compliance.sensitive_data_redaction
name: 敏感数据脱敏
description: 用于对手机号、身份证号、密钥、token、password、健康信息等敏感数据提出脱敏方案
agent: compliance_security_agent
intent_tags:
  - compliance_review
  - sensitive_data_redaction
  - 脱敏
  - token
  - secret
business_domain:
  - health_insurance_onboarding
required_context:
  - short_summary
enabled: true
is_default: false
---

# 敏感数据脱敏 Skill

为文本中的敏感字段生成脱敏建议。输出只展示掩码示例，不展示完整原值。
