---
skill_id: compliance.external_message_review
name: 外发内容审核
description: 用于审核准备发送给渠道、合作方、邮件或外部系统的内容是否存在外发风险
agent: compliance_security_agent
intent_tags:
  - compliance_review
  - external_message_review
  - 外发
  - 渠道
business_domain:
  - health_insurance_onboarding
required_context:
  - short_summary
enabled: true
is_default: false
---

# 外发内容审核 Skill

判断文本是否适合发送给渠道或合作方。重点检查最小必要原则、敏感字段脱敏、授权范围和接收方范围控制。
