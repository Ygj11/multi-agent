---
skill_id: document_parse_agent.api_doc_parse
name: ??????
description: ???? submitProposal ??????????????????????????????
agent: document_parse_agent
intent_tags:
  - document_parse
  - api_doc_parse
  - ????
  - submitProposal
required_entities:
  - interface_name
optional_entities:
  - document_type
  - field_name

private_tools: []
enabled: true
is_default: true
business_domain:
  - health_insurance_onboarding
required_context:
  - interface_name
---

# 接口文档解析 Skill

解析接口文档中的标题、接口名、字段、错误码和签名规则说明，输出结构化摘要。


