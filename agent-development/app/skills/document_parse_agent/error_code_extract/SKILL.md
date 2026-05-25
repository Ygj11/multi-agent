---
skill_id: document_parse_agent.error_code_extract
name: ?????
description: ???????? E102 ???????????????????
agent: document_parse_agent
intent_tags:
  - document_parse
  - error_code_extract
  - ???
  - E102
required_entities: []
optional_entities:
  - error_code

private_tools: []
enabled: true
is_default: false
business_domain:
  - health_insurance_onboarding
required_context:
  - error_code
---

# 错误码提取 Skill

从文档中提取错误码、错误含义、触发条件和建议处理动作。


