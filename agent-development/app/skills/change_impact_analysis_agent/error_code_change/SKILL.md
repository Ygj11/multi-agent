---
skill_id: change_impact.error_code_change
name: 错误码变更影响分析
description: 用于分析 E102 等错误码含义、错误映射、排障建议和知识文档变更影响
agent: change_impact_analysis_agent
intent_tags:
  - change_impact_analysis
  - error_code_change
  - 错误码变更
  - E102
business_domain:
  - health_insurance_onboarding
required_context:
  - error_code
enabled: true
is_default: false
---

# 错误码变更影响分析 Skill

分析错误码定义变化对接口文档、知识库、排障 Agent 和回归测试的影响。
