---
skill_id: change_impact_analysis_agent.signature_rule_change
name: ??????????
description: ???? timestamp?base string???????????????????????????
agent: change_impact_analysis_agent
intent_tags:
  - change_impact_analysis
  - signature_rule_change
  - ????
  - timestamp
  - E102
required_entities:
  - interface_name
optional_entities:
  - error_code

private_tools: []
enabled: true
is_default: false
business_domain:
  - health_insurance_onboarding
required_context:
  - interface_name
  - error_code
---

# 签名规则变更影响分析 Skill

分析签名规则变更对 submitProposal、E102、渠道联调、回归测试和排障知识的影响。


