---
skill_id: change_impact.signature_rule_change
name: 签名规则变更影响分析
description: 用于分析 timestamp、base string、字段排序、密钥版本、签名算法变更对接口和错误码的影响
agent: change_impact_analysis_agent
intent_tags:
  - change_impact_analysis
  - signature_rule_change
  - 签名规则
  - timestamp
  - E102
business_domain:
  - health_insurance_onboarding
required_context:
  - interface_name
  - error_code
enabled: true
is_default: false
---

# 签名规则变更影响分析 Skill

分析签名规则变更对 submitProposal、E102、渠道联调、回归测试和排障知识的影响。
