---
skill_id: document_parse_agent.markdown_parse
name: Markdown 文档解析
description: 用于解析 markdown 标题、表格、列表、代码块和字段说明
agent: document_parse_agent
intent_tags:
  - document_parse
  - markdown_parse
  - markdown
business_domain:
  - health_insurance_onboarding
required_context:
  - short_summary
enabled: true
is_default: false
---

# Markdown 文档解析 Skill

解析 markdown 文档结构，提取标题、表格字段、列表项和代码块中的接口信息。
