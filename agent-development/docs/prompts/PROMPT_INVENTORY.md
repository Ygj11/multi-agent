# Prompt Inventory

本文汇总当前项目中所有可能属于 prompt / skill / instruction / rule-like prompt 的内容。结论：当前主链路没有真正使用 LLM prompt；运行时主要使用规则逻辑，`SKILL.md` 只作为 skill metadata 与 selected skill content 进入上下文。

| 名称 | 类型 | 当前是否真实运行时使用 | 代码位置 | 文件位置 | 调用组件 | 上游 | 下游 | 是否规则实现 | 是否 LLM prompt | 是否 SKILL.md | 备注 |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Query rewrite | 规则改写 | 是 | `app/query/query_rewrite_node.py` | 无运行时 prompt 文件 | `AgentGraphFactory.query_rewrite` | `load_session`、`save_user_message` | `intent_recognition` | 是 | 否 | 否 | 当前未使用 prompt。 |
| Query rewrite skill instruction | Skill 文档 | 否 | 无运行时读取 | `app/skills/query_rewrite/SKILL.md` | 无 | 无 | 无 | 否 | 否 | 是 | 当前只是文档/skill 指令，没有被 `QueryRewriteNode` 读取。 |
| Intent recognition | 关键词分类规则 | 是 | `app/query/intent_recognition_node.py` | 无 | `AgentGraphFactory.intent_recognition` | `query_rewrite` | `build_orchestrator_context`、`route_intent` | 是 | 否 | 否 | 当前未使用 prompt。 |
| Orchestrator context | 结构化上下文 | 是 | `app/runtime/context_builder.py` | 无 | `ContextBuilder.build_for_orchestrator` | query rewrite、intent、session memory | LangGraph `orchestrator_context` | 否 | 否 | 否 | 是 prompt-like context，但不是 system prompt。 |
| Skill selection context | 结构化上下文 | 是 | `app/runtime/context_builder.py` | 无 | `ContextBuilder.build_skill_selection_context` | `SubAgentTask`、`OrchestratorContext` | `SkillSelector` | 否 | 否 | 否 | 用于规则匹配 selected skill。 |
| Subagent context | 结构化上下文 + selected skill content | 是 | `app/runtime/context_builder.py` | selected `SKILL.md` | `ContextBuilder.build_for_subagent` | `SubAgentManager`、子 Agent | 子 Agent `run()` | 否 | 否 | 部分是 | 包含 `skill_content`，但未发给 LLM。 |
| Skill selector | 规则匹配 | 是 | `app/skills/selector.py` | `app/skills/*_agent/*/SKILL.md` metadata | `SkillSelector.select` | `ContextBuilder` | selected skill id | 是 | 否 | 否 | 使用 metadata 关键词和分数，不接 embedding 或 LLM。 |
| Troubleshooting signature skill | Skill instruction | 是，作为 selected skill content | `app/skills/catalog.py` | `app/skills/troubleshooting_agent/signature_error/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `TroubleshootingAgent` | 否 | 否 | 是 | E102/签名失败场景常用，默认 skill。 |
| Troubleshooting missing field skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/troubleshooting_agent/missing_field/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `TroubleshootingAgent` | 否 | 否 | 是 | 字段缺失/必填为空场景。 |
| Troubleshooting callback failure skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/troubleshooting_agent/callback_failure/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `TroubleshootingAgent` | 否 | 否 | 是 | 回调失败/超时场景。 |
| Compliance privacy check skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/compliance_security_agent/privacy_check/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `ComplianceSecurityAgent` | 否 | 否 | 是 | 隐私、身份证、手机号场景，默认 skill。 |
| Compliance external message review skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/compliance_security_agent/external_message_review/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `ComplianceSecurityAgent` | 否 | 否 | 是 | 外发、渠道材料审核场景。 |
| Compliance sensitive data redaction skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/compliance_security_agent/sensitive_data_redaction/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `ComplianceSecurityAgent` | 否 | 否 | 是 | 脱敏、token、secret 场景。 |
| Document parse API doc skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/document_parse_agent/api_doc_parse/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `DocumentParseAgent` | 否 | 否 | 是 | 接口文档、submitProposal 场景，默认 skill。 |
| Document parse markdown skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/document_parse_agent/markdown_parse/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `DocumentParseAgent` | 否 | 否 | 是 | Markdown 结构解析场景。 |
| Document parse error code skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/document_parse_agent/error_code_extract/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `DocumentParseAgent` | 否 | 否 | 是 | 错误码提取场景。 |
| Change impact API field skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/change_impact_analysis_agent/api_field_change/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `ChangeImpactAnalysisAgent` | 否 | 否 | 是 | 字段变更场景，默认 skill。 |
| Change impact signature rule skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/change_impact_analysis_agent/signature_rule_change/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `ChangeImpactAnalysisAgent` | 否 | 否 | 是 | timestamp、签名规则变更场景。 |
| Change impact error code skill | Skill instruction | 是，命中时加载 | `app/skills/catalog.py` | `app/skills/change_impact_analysis_agent/error_code_change/SKILL.md` | `ContextBuilder.build_for_subagent` | `SkillSelector` | `ChangeImpactAnalysisAgent` | 否 | 否 | 是 | E102/错误码变更场景。 |
| Legacy troubleshooting skill | 旧 skill 文档 | 仅 fallback 场景可能使用 | `app/runtime/context_builder.py` `_read_skill()` | `app/skills/troubleshooting/SKILL.md` | fallback `_skill_name_for_task` | 无候选 metadata 时 | 子 Agent context | 否 | 否 | 是 | 当前正常路径使用新版多 skill。 |
| Legacy compliance skill | 旧 skill 文档 | 仅 fallback 场景可能使用 | `app/runtime/context_builder.py` `_read_skill()` | `app/skills/compliance_security/SKILL.md` | fallback `_skill_name_for_task` | 无候选 metadata 时 | 子 Agent context | 否 | 否 | 是 | 迁移兼容。 |
| Legacy document parse skill | 旧 skill 文档 | 仅 fallback 场景可能使用 | `app/runtime/context_builder.py` `_read_skill()` | `app/skills/document_parse/SKILL.md` | fallback `_skill_name_for_task` | 无候选 metadata 时 | 子 Agent context | 否 | 否 | 是 | 迁移兼容。 |
| Legacy change impact skill | 旧 skill 文档 | 仅 fallback 场景可能使用 | `app/runtime/context_builder.py` `_read_skill()` | `app/skills/change_impact_analysis/SKILL.md` | fallback `_skill_name_for_task` | 无候选 metadata 时 | 子 Agent context | 否 | 否 | 是 | 迁移兼容。 |
| FakeLLMProvider messages | LLM provider 输入接口 | 当前主链路未使用 | `app/llm/fake_provider.py` | 无 | 无主链路调用 | 外部调用者 | Fake fixed response | 是 | 否 | 否 | 接收 `messages`，但只做关键词判断。 |
| OpenAICompatibleLLMProvider messages | LLM provider 输入接口 | 默认不启用，主链路未使用 | `app/llm/openai_provider.py` | 无 | 无主链路调用 | 外部调用者 | OpenAI-compatible API | 否 | 接收 messages | 否 | 不构造 prompt，只转发调用方 messages。 |
| ToolBroker / PolicyGate | 结构化工具调用 | 是 | `app/tools/broker.py`、`app/tools/policy_gate.py` | 无 | 子 Agent | `ToolCall` | Tool handler | 是 | 否 | 否 | 不使用 prompt。 |
| MCP connector | 结构化 fake MCP 调用 | 是 | `app/mcp/fake_connector.py`、`app/tools/mcp_tools.py` | 无 | ToolBroker | `partner_trace.get_request_detail` | FakeMCPConnector result | 是 | 否 | 否 | 不使用 prompt。 |

## 重要结论

- 当前没有主流程 system prompt。
- 当前没有 PromptRegistry。
- 当前没有 PromptBuilder。
- 当前没有把 `ContextBuilder` 输出转成 LLM messages。
- 当前 `SKILL.md` 是运行时 skill instruction 的主要来源，但不是 LLM prompt source of truth。
- 当前 query rewrite、intent recognition、子 Agent 业务执行仍是规则实现。

