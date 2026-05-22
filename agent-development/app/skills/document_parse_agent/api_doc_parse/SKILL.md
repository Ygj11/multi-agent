---
skill_id: document_parse_agent.api_doc_parse
name: 接口文档解析
description: 用于解析 submitProposal 等接口文档，提取接口名、请求字段、响应字段、签名规则和错误码
agent: document_parse_agent
intent_tags:
  - document_parse
  - api_doc_parse
  - 接口文档
  - submitProposal
business_domain:
  - health_insurance_onboarding
required_context:
  - interface_name
enabled: true
is_default: true
---

# 接口文档解析 Skill

解析接口文档中的标题、接口名、字段、错误码和签名规则说明，输出结构化摘要。
