---
skill_id: claim_agent.default
name: ????????
description: ????????????????????????????
agent: claim_agent
intent_tags:
  - claim_query
  - claim_progress
required_entities:
  - claim_no

private_tools:
  - query_claim_case
  - query_claim_progress
enabled: true
is_default: true
---

1. Confirm the claim number if available.
2. Query claim case state.
3. Query claim progress.
4. Return a concise answer with evidence and avoid exposing raw internal payloads.
