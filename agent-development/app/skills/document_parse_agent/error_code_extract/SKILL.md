---
skill_id: document_parse.error_code_extract
name: 错误码提取
description: 用于从文档中提取 E102 等错误码、错误说明、排查提示和错误映射
agent: document_parse_agent
intent_tags:
  - document_parse
  - error_code_extract
  - 错误码
  - E102
business_domain:
  - health_insurance_onboarding
required_context:
  - error_code
enabled: true
is_default: false
---

# 错误码提取 Skill

从文档中提取错误码、错误含义、触发条件和建议处理动作。
