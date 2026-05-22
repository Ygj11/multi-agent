---
skill_id: policy_query_agent.default
name: Policy Query Default
description: Query policy information and policy status using policy private tools.
agent: policy_query_agent
intent_tags:
  - policy_query
  - policy_status
  - product_rule_qa
required_entities:
  - policy_no
private_tools:
  - query_policy_info
  - query_policy_status
enabled: true
is_default: true
---

1. Confirm the policy number if available.
2. Query basic policy information.
3. Query policy status.
4. Summarize only user-safe fields.
