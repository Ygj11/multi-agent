# TASK_SKILL_UPGRADE.md

## 1. skills 升级阶段目标

将当前“一个子 Agent 固定绑定一个 `SKILL.md`”的实现，升级为“一个子 Agent 拥有多个 skills，并根据子 Agent 上下文与 skill metadata 的相似度/匹配规则动态选择一个最合适 skill，再渐进式加载完整 `SKILL.md`”的机制。

本阶段目标是补齐 V3 架构中 Skill Manager / Skill Catalog / 按需加载 skill 的核心思想，但仍保持本地 MVP 范围：

1. 不接真实 embedding。
2. 不接真实 LLM 做 skill selection。
3. 不做在线 skill 编辑平台。
4. 不做完整企业级 skill 审批流。
5. 所有工具调用仍必须经过 `ToolBroker / PolicyGate`。
6. 所有已有测试继续通过。

---

## 2. 当前固定 skill 绑定的问题

当前实现是固定映射：

```text
SubAgentTask.name -> skill 目录 -> SKILL.md
```

例如：

```text
troubleshooting_agent -> app/skills/troubleshooting/SKILL.md
compliance_security_agent -> app/skills/compliance_security/SKILL.md
document_parse_agent -> app/skills/document_parse/SKILL.md
change_impact_analysis_agent -> app/skills/change_impact_analysis/SKILL.md
```

当前问题：

1. 一个子 Agent 只能使用一个固定 skill，不能细分专业能力。
2. 所有请求进入同一子 Agent 后都加载同一份完整 `SKILL.md`。
3. 主流程无法看到 skill metadata summary，也无法做 skill 候选选择。
4. 无法记录 `selected_skill_id`，不利于日志、审计和回放。
5. 不符合目标架构中“先加载 metadata，按需加载完整 skill”的渐进式披露方式。

---

## 3. 新的 SkillCatalog 设计

新增模块：

```text
app/skills/catalog.py
```

`SkillCatalog` 负责扫描、缓存和读取 skill。

必须支持：

1. 扫描 `app/skills` 下所有子 Agent 的 skill 目录。
2. 只加载 YAML frontmatter，不加载完整正文。
3. 支持 `list_skills(agent_name)`。
4. 支持 `get_skill_metadata(skill_id)`。
5. 支持 `load_skill_content(skill_id)`。
6. `enabled=false` 的 skill 不参与选择。
7. 支持 metadata 缓存，避免每次请求重复扫描。
8. 不允许根据用户输入读取任意文件。
9. `source_path` 必须解析到 `app/skills` 根目录内。

建议接口：

```python
class SkillCatalog:
    def __init__(self, skills_root: Path) -> None: ...
    def scan(self, force_reload: bool = False) -> list[SkillMetadata]: ...
    def list_skills(self, agent_name: str, include_disabled: bool = False) -> list[SkillMetadata]: ...
    def get_skill_metadata(self, skill_id: str) -> SkillMetadata | None: ...
    def load_skill_content(self, skill_id: str) -> SkillContent: ...
```

---

## 4. 新的 SkillMetadata 设计

新增模块：

```text
app/skills/metadata.py
app/schemas/skill.py
```

`SkillMetadata` 至少包含：

1. `skill_id`
2. `name`
3. `description`
4. `agent`
5. `intent_tags`
6. `business_domain`
7. `required_context`
8. `enabled`
9. `source_path`

建议补充：

```text
is_default
version
owner
last_updated
```

但本轮不强制实现复杂版本治理。

建议 schema：

```python
class SkillMetadata(BaseModel):
    skill_id: str
    name: str
    description: str
    agent: str
    intent_tags: list[str] = []
    business_domain: list[str] = []
    required_context: list[str] = []
    enabled: bool = True
    is_default: bool = False
    source_path: str


class SkillContent(BaseModel):
    metadata: SkillMetadata
    content: str


class SkillSelectionResult(BaseModel):
    selected_skill_id: str
    selected_skill_metadata: SkillMetadata
    score: float
    reason: str
    fallback: bool = False
```

---

## 5. 新的 SkillSelector 设计

新增模块：

```text
app/skills/selector.py
```

`SkillSelector` 输入：

1. `agent_name`
2. `subagent_context` 或 `skill_selection_context`
3. `candidate_skill_metadata list`

`SkillSelector` 输出：

1. `selected_skill_id`
2. `selected_skill_metadata`
3. `score`
4. `reason`
5. `fallback`

第一阶段使用规则 + 关键词相似度，不接真实 embedding，不接真实 LLM。

建议接口：

```python
class SkillSelector:
    async def select(
        self,
        *,
        agent_name: str,
        context: SkillSelectionContext,
        candidates: list[SkillMetadata],
    ) -> SkillSelectionResult: ...
```

---

## 6. skills 目录结构调整方案

将当前目录：

```text
app/skills/
  troubleshooting/SKILL.md
  compliance_security/SKILL.md
  document_parse/SKILL.md
  change_impact_analysis/SKILL.md
```

升级为：

```text
app/skills/
  troubleshooting_agent/
    signature_error/
      SKILL.md
    missing_field/
      SKILL.md
    callback_failure/
      SKILL.md

  compliance_security_agent/
    privacy_check/
      SKILL.md
    external_message_review/
      SKILL.md
    sensitive_data_redaction/
      SKILL.md

  document_parse_agent/
    api_doc_parse/
      SKILL.md
    markdown_parse/
      SKILL.md
    error_code_extract/
      SKILL.md

  change_impact_analysis_agent/
    api_field_change/
      SKILL.md
    signature_rule_change/
      SKILL.md
    error_code_change/
      SKILL.md
```

兼容策略：

1. 可以保留旧的 `app/skills/troubleshooting/SKILL.md` 等文件作为迁移参考。
2. 新流程必须使用新目录结构。
3. 测试必须证明新流程不会读取旧固定 skill 文件作为子 Agent skill。
4. `query_rewrite/SKILL.md` 可以暂时保持原状，不纳入本轮子 Agent 多 skill 选择。

---

## 7. 子 Agent 如何加载 skill metadata

子 Agent 不应自行扫描文件系统。

推荐流程：

1. 应用启动时创建 `SkillCatalog(skills_root=...)`。
2. `SkillCatalog.scan()` 加载所有 skill metadata。
3. `SubAgentManager` 持有或可访问 `SkillCatalog`。
4. 当某个子 Agent 被调用时，`SubAgentManager` 或 `ContextBuilder` 通过 `SkillCatalog.list_skills(agent_name)` 获取候选 metadata。
5. 候选 metadata 只包含 frontmatter，不包含完整正文。

要求：

1. 只加载当前 `agent_name` 下的 skills。
2. `enabled=false` 的 skill 默认不返回。
3. 日志记录 `skill_metadata_loaded`。

---

## 8. 子 Agent 如何根据上下文选择 skill

请求流转到子 Agent 后：

1. `ContextBuilder.build_skill_selection_context(...)` 构建 skill 选择所需上下文。
2. `SubAgentManager` 或 `ContextBuilder` 获取该子 Agent 的 candidate skill metadata。
3. `SkillSelector.select(...)` 根据上下文和 metadata 计算分数。
4. 选出 `selected_skill_id`。
5. `SkillCatalog.load_skill_content(selected_skill_id)` 加载完整 `SKILL.md`。
6. `ContextBuilder.build_for_subagent(...)` 只注入 selected skill 的完整内容。
7. 子 Agent 根据 selected skill 内容执行任务。

不允许：

1. 在主流程一次性加载所有 `SKILL.md` 正文。
2. 由用户输入直接指定任意本地路径。
3. 绕过 `SkillCatalog` 读取 skill 文件。

---

## 9. 子 Agent 如何渐进式加载完整 SKILL.md

渐进式披露要求：

1. 主流程和主 Agent 只能看到 skill metadata summary。
2. Skill selection 阶段只使用 metadata。
3. 只有确定 `selected_skill_id` 后，才加载完整 `SKILL.md`。
4. `ContextBuilder.build_for_subagent` 只注入 selected skill 的完整内容。
5. 未选中的 skill 只作为 metadata 参与匹配。
6. `selected_skill_id` 必须进入 `SubAgentTask.metadata`、`SubAgentContext` 或 `SubAgentResult`，便于测试和回放。

---

## 10. ContextBuilder 如何为 skill selection 提供上下文

`ContextBuilder` 必须新增：

```text
build_skill_selection_context
```

新增 schema：

```text
app/schemas/skill.py
```

建议 `SkillSelectionContext` 至少包含：

1. `agent_name`
2. `intent`
3. `original_query`
4. `rewritten_query`
5. `session_key`
6. `short_summary`
7. `recent_messages_summary`
8. `lightweight_knowledge_hints`
9. `request_id`
10. `trace_id`
11. `extracted_error_code`
12. `extracted_request_id`
13. `extracted_interface_name`
14. `business_domain`

`ContextBuilder.build_for_subagent(...)` 改造要求：

1. 接收或内部生成 `selected_skill_id`。
2. 只读取 selected skill 的完整内容。
3. 将 `selected_skill_id`、`selected_skill_metadata`、`selection_score`、`selection_reason` 写入 `SubAgentContext`。
4. 不再通过 `_skill_name_for_task(task.name)` 固定读取单个 `SKILL.md`。

---

## 11. SkillSelector 的匹配算法要求

第一阶段使用规则 + 关键词相似度。

匹配维度至少包含：

1. `intent`
2. `rewritten_query`
3. `original_query`
4. `error_code`
5. `request_id`
6. `interface_name`
7. `business_domain`
8. `recent_messages_summary`
9. `skill.description`
10. `skill.intent_tags`
11. `skill.required_context`

建议评分规则：

```text
intent_tags 命中 intent：+3
intent_tags 命中 query 关键词：每个 +2
description 命中 query 关键词：每个 +1
required_context 在上下文中存在：每个 +1
business_domain 匹配：+1
接口名匹配：+2
错误码匹配：+3
```

fallback 规则：

1. 如果所有候选分数都低于阈值，选择该子 Agent 的 default skill。
2. default skill 通过 `is_default: true` 标识。
3. 如果没有 default skill，则选择该 agent 下第一个 enabled skill，并记录 `skill_selection_fallback`。
4. fallback 必须记录日志和 reason。

---

## 12. TroubleshootingAgent 多 skill 示例

至少新增：

```text
troubleshooting.signature_error
troubleshooting.missing_field
troubleshooting.callback_failure
```

### troubleshooting.signature_error

路径：

```text
app/skills/troubleshooting_agent/signature_error/SKILL.md
```

frontmatter 示例：

```yaml
---
skill_id: troubleshooting.signature_error
name: 签名失败排查
description: 用于排查 E102、签名校验失败、timestamp 未参与签名、密钥版本不一致、字段排序不一致等问题
agent: troubleshooting_agent
intent_tags:
  - troubleshooting
  - signature_error
  - E102
  - submitProposal
business_domain:
  - health_insurance_onboarding
required_context:
  - request_id
  - error_code
  - interface_name
enabled: true
is_default: true
---
```

示例匹配：

```text
输入：REQ_001 为什么返回 E102？
应该选择：troubleshooting.signature_error
原因：query 包含 REQ_001、E102，metadata description 和 intent_tags 匹配签名失败排查。
```

### troubleshooting.missing_field

用于字段缺失、必填字段为空、submitProposal 报文字段不完整等问题。

### troubleshooting.callback_failure

用于回调失败、回调超时、渠道未收到回调、回调验签失败等问题。

---

## 13. ComplianceSecurityAgent 多 skill 示例

至少新增：

```text
compliance.privacy_check
compliance.external_message_review
compliance.sensitive_data_redaction
```

建议路径：

```text
app/skills/compliance_security_agent/privacy_check/SKILL.md
app/skills/compliance_security_agent/external_message_review/SKILL.md
app/skills/compliance_security_agent/sensitive_data_redaction/SKILL.md
```

匹配示例：

1. 包含“隐私、个人信息、身份证、手机号、健康告知” -> `compliance.privacy_check`
2. 包含“外发、发给渠道、发给合作方、邮件内容” -> `compliance.external_message_review`
3. 包含“脱敏、掩码、隐藏、redaction” -> `compliance.sensitive_data_redaction`

---

## 14. DocumentParseAgent 多 skill 示例

至少新增：

```text
document_parse.api_doc_parse
document_parse.markdown_parse
document_parse.error_code_extract
```

建议路径：

```text
app/skills/document_parse_agent/api_doc_parse/SKILL.md
app/skills/document_parse_agent/markdown_parse/SKILL.md
app/skills/document_parse_agent/error_code_extract/SKILL.md
```

匹配示例：

1. 包含“接口文档、submitProposal、字段、请求参数、响应参数” -> `document_parse.api_doc_parse`
2. 包含“markdown、# 标题、表格” -> `document_parse.markdown_parse`
3. 包含“错误码、E102、错误说明、错误映射” -> `document_parse.error_code_extract`

---

## 15. ChangeImpactAnalysisAgent 多 skill 示例

至少新增：

```text
change_impact.api_field_change
change_impact.signature_rule_change
change_impact.error_code_change
```

建议路径：

```text
app/skills/change_impact_analysis_agent/api_field_change/SKILL.md
app/skills/change_impact_analysis_agent/signature_rule_change/SKILL.md
app/skills/change_impact_analysis_agent/error_code_change/SKILL.md
```

匹配示例：

1. 包含“字段变更、必填字段、新增字段、删除字段” -> `change_impact.api_field_change`
2. 包含“签名规则、timestamp、base string、密钥版本” -> `change_impact.signature_rule_change`
3. 包含“错误码变更、E102、错误说明调整” -> `change_impact.error_code_change`

---

## 16. ToolBroker / PolicyGate 与 selected skill 的关系

skill 可以在正文中说明建议使用哪些 tools，例如：

```text
query_internal_log
get_knowledge
partner_trace.get_request_detail
http_request
mcp_http.call_tool
shell_exec
```

但 selected skill 不能绕过工具治理。

要求：

1. 子 Agent 调用任何工具仍必须构造 `ToolCall`。
2. 工具必须经过 `ToolBroker.call(...)`。
3. `ToolBroker` 必须继续调用 `PolicyGate.allow(...)`。
4. `selected_skill_id` 应写入 `ToolCall.arguments` 或 `ToolCall` metadata 的安全位置，便于审计关联。
5. 本轮不改造 PolicyGate 为 tool metadata 模式。
6. 本轮不新增 `ToolMetadata / ToolRiskLevel / ToolOperationType`。
7. HTTP / MCP HTTP 工具仍默认禁用，启用也必须受 host 白名单限制。

---

## 17. 日志和审计要求

新增日志事件：

1. `skill_metadata_loaded`
2. `skill_candidates_built`
3. `skill_selection_started`
4. `skill_selected`
5. `skill_content_loaded`
6. `skill_selection_fallback`

日志字段必须包含：

```text
timestamp
level
event
request_id
trace_id
session_key
agent_name
selected_skill_id
score
reason
```

要求：

1. 日志仍使用 `app/observability/logger.py` 的 `log_event`。
2. `data` 中只能放脱敏后的摘要。
3. 不记录完整用户敏感文本。
4. `subagent_result` 或 graph final state 必须能看到 `selected_skill_id`。
5. 如果有工具调用，`tool_call_logs` 应能通过 `session_key`、`request_id` 和可选 `selected_skill_id` 关联回本轮 skill。

---

## 18. 测试要求

新增或增强测试：

```text
tests/test_skill_catalog.py
tests/test_skill_selector.py
tests/test_skill_context_builder.py
tests/test_skill_selection_end_to_end.py
```

必须覆盖：

1. `SkillCatalog` 能扫描所有子 Agent skills metadata。
2. `SkillCatalog` 只加载 metadata，不加载正文。
3. `SkillCatalog` 能按 `skill_id` 加载完整 `SKILL.md`。
4. `SkillSelector` 对 E102 请求选择 `troubleshooting.signature_error`。
5. `SkillSelector` 对字段缺失问题选择 `troubleshooting.missing_field`。
6. `SkillSelector` 对回调失败问题选择 `troubleshooting.callback_failure`。
7. `ContextBuilder.build_for_subagent` 只注入 selected skill 内容，不注入所有 skill 正文。
8. `TroubleshootingAgent` 对 `REQ_001` 端到端选择 `troubleshooting.signature_error`。
9. `subagent_result` 或 graph final state 中能看到 `selected_skill_id`。
10. 未启用 skill 不参与选择。
11. 没有明显匹配时走 default skill。
12. `skill_selected` 日志事件会出现。
13. 所有已有测试继续通过。

建议额外覆盖：

1. ComplianceSecurityAgent 选择 `compliance.privacy_check`。
2. DocumentParseAgent 选择 `document_parse.api_doc_parse` 或 `document_parse.markdown_parse`。
3. ChangeImpactAnalysisAgent 选择 `change_impact.signature_rule_change`。
4. 不同 user/session 的 skill selection 不互相污染。

---

## 19. README 更新要求

README.md 必须新增：

1. 多 skill 目录结构说明。
2. `SkillCatalog` 只加载 metadata 的说明。
3. `SkillSelector` 规则 + 关键词相似度说明。
4. 渐进式加载完整 `SKILL.md` 的说明。
5. `selected_skill_id` 如何进入日志、subagent_result 或 graph state。
6. 每个子 Agent 的多 skill 示例。
7. 与 `ToolBroker / PolicyGate` 的关系说明。
8. 当前不接 embedding / Milvus / Elasticsearch / LLM selector 的说明。

README 中需要明确：

```text
当前不允许根据用户输入动态读取任意 skill 文件。
候选 skill 必须来自固定 SkillCatalog。
未选中的 skill 只以 metadata 参与匹配，不会把正文塞进上下文。
```

---

## 20. 验收命令

必须保证以下命令可运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

如果当前本地环境无法直接找到 `uv`，也必须保证项目 `.venv` 下 pytest 全量通过，并在总结中说明。

---

## 21. 本轮不要做的内容

本轮不要做：

1. 不接真实 embedding。
2. 不接 Milvus。
3. 不接 Elasticsearch。
4. 不接真实 LLM 做 skill selection。
5. 不做复杂语义召回。
6. 不做在线 skill 编辑平台。
7. 不做 skill 审批流。
8. 不改变 `/api/chat` 现有核心响应格式，除非保持向后兼容。
9. 不绕过 `ToolBroker / PolicyGate`。
10. 不实现自由 spawn。
11. 不改造 PolicyGate 为 tool metadata 模式。
12. 不新增 `ToolMetadata / ToolRiskLevel / ToolOperationType`。
13. 不接真实 MCP Server。
14. 不接真实保险核心系统。
15. 不把所有 skill 正文一次性加载到主流程上下文。

---

## 22. 计划新增或修改的文件

必须新增：

```text
app/skills/catalog.py
app/skills/metadata.py
app/skills/selector.py
app/skills/loader.py
app/schemas/skill.py

app/skills/troubleshooting_agent/signature_error/SKILL.md
app/skills/troubleshooting_agent/missing_field/SKILL.md
app/skills/troubleshooting_agent/callback_failure/SKILL.md

app/skills/compliance_security_agent/privacy_check/SKILL.md
app/skills/compliance_security_agent/external_message_review/SKILL.md
app/skills/compliance_security_agent/sensitive_data_redaction/SKILL.md

app/skills/document_parse_agent/api_doc_parse/SKILL.md
app/skills/document_parse_agent/markdown_parse/SKILL.md
app/skills/document_parse_agent/error_code_extract/SKILL.md

app/skills/change_impact_analysis_agent/api_field_change/SKILL.md
app/skills/change_impact_analysis_agent/signature_rule_change/SKILL.md
app/skills/change_impact_analysis_agent/error_code_change/SKILL.md
```

必须修改：

```text
app/runtime/context_builder.py
app/runtime/graph_state.py
app/schemas/runtime.py
app/schemas/subagent.py
app/subagents/manager.py
app/subagents/troubleshooting_agent.py
app/subagents/compliance_security_agent.py
app/subagents/document_parse_agent.py
app/subagents/change_impact_analysis_agent.py
app/main.py
README.md
```

可能修改：

```text
app/runtime/graph.py
app/tools/broker.py
tests/conftest.py
```

---

## 23. 验收请求

### 23.1 Troubleshooting signature skill

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "pingan_health",
    "channel": "web",
    "user_id": "u001",
    "session_id": "s_skill_001",
    "messages": [
      {
        "role": "user",
        "content": "REQ_001 为什么返回 E102？"
      }
    ]
  }'
```

验收：

```text
intent = troubleshooting
selected_skill_id = troubleshooting.signature_error
answer 仍包含 E102、签名校验失败、timestamp、渠道侧 trace
```

### 23.2 Troubleshooting missing field skill

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "pingan_health",
    "channel": "web",
    "user_id": "u001",
    "session_id": "s_skill_002",
    "messages": [
      {
        "role": "user",
        "content": "submitProposal 报文字段缺失，提示 appId 不能为空，帮我排查"
      }
    ]
  }'
```

验收：

```text
intent = troubleshooting
selected_skill_id = troubleshooting.missing_field
```

### 23.3 Change impact signature rule skill

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "pingan_health",
    "channel": "web",
    "user_id": "u001",
    "session_id": "s_skill_003",
    "messages": [
      {
        "role": "user",
        "content": "签名规则变更：timestamp 必须加入签名原文。请分析影响哪些接口、错误码和测试。"
      }
    ]
  }'
```

验收：

```text
intent = change_impact_analysis
selected_skill_id = change_impact.signature_rule_change
answer 包含 submitProposal、E102、签名规则、回归测试或联调测试
```
