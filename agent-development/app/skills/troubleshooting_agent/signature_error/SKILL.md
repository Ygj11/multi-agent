---
skill_id: troubleshooting_agent.signature_error
name: 签名失败排查
description: 用于排查 E102、签名校验失败、timestamp 未参与签名、密钥版本不一致、字段排序不一致等问题
agent: troubleshooting_agent
intent_tags:
  - troubleshooting
  - signature_error
  - E102
  - submitProposal
  - timestamp
business_domain:
  - health_insurance_onboarding
required_context:
  - request_id
  - error_code
  - interface_name
enabled: true
is_default: true
---

# 签名失败排查 Skill

当问题包含 E102、签名校验失败、timestamp、submitProposal 或渠道签名原文时，优先使用本 skill。

执行步骤：

1. 使用 `query_internal_log` 查询内部日志，确认接口名、错误码、签名规则版本和疑似原因。
2. 使用 `get_knowledge` 查询 E102、签名规则、timestamp、密钥版本、字段排序和空值字段处理知识。
3. 如内部日志证据不足或需要外部流程证据，使用 AgentCard 授权的 MCP Client 工具，例如 `mcp.workflow.query_refund_task`。
4. 输出内部日志证据、知识库依据、MCP workflow 证据、初步问题归属和建议动作。
