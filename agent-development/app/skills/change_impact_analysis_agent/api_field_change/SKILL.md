---
skill_id: change_impact.api_field_change
name: 接口字段变更影响分析
description: 用于分析新增字段、删除字段、必填字段、字段类型或字段映射变更的影响
agent: change_impact_analysis_agent
intent_tags:
  - change_impact_analysis
  - api_field_change
  - 字段变更
  - 必填字段
business_domain:
  - health_insurance_onboarding
required_context:
  - interface_name
enabled: true
is_default: true
---

# 接口字段变更影响分析 Skill

分析字段变更对接口契约、渠道映射、回归测试和知识库文档的影响。
