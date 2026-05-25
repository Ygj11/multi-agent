---
skill_id: compliance_agent.default
name: ????????
description: ?????????????????????????????
agent: compliance_agent
intent_tags:
  - compliance_review
  - privacy_review
required_entities: []
optional_entities:
  - sensitive_type
  - risk_level

private_tools: []
enabled: true
is_default: true
---

1. Inspect text for direct identifiers, credentials, and health privacy content.
2. Redact sensitive values.
3. Return a conservative external sending recommendation.


