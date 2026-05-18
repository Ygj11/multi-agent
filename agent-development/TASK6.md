# TASK6.md

## 阶段目标

在现有 `SubAgentManager` 固定 Agent Catalog 基础上新增三个子 Agent：

1. 合规安全 Agent
2. 文档解析 Agent
3. 变更影响分析 Agent

本阶段目标是扩展专业子 Agent 的任务边界，让系统从“问题排查单一子 Agent”演进为“多个固定专业子 Agent 协作的 MVP”。

暂时不要做策略治理和工具元数据化，不要改造 PolicyGate 为 metadata 模式。

---

## 本轮必须实现

必须实现：

1. 新增 `ComplianceSecurityAgent`
2. 新增 `DocumentParseAgent`
3. 新增 `ChangeImpactAnalysisAgent`
4. 三个子 Agent 必须通过固定 Agent Catalog 注册
5. 不允许自由 spawn
6. 每个子 Agent 必须有自己的 `SKILL.md`
7. 每个子 Agent 必须有输入 schema 和输出 schema
8. 每个子 Agent 必须经过 `SubAgentManager.call_subagent`
9. 每个子 Agent 的工具调用必须经过 `ToolBroker / PolicyGate`
10. ContextBuilder 必须支持为这些子 Agent 构建最小必要上下文
11. LangGraph route_intent 必须能路由到对应子 Agent
12. IntentRecognitionNode 新增意图识别：
    - `compliance_review`
    - `document_parse`
    - `change_impact_analysis`
13. `/api/chat` 核心响应格式保持兼容
14. 新增测试覆盖三个子 Agent
15. 所有已有测试继续通过

---

## 本轮不要实现

本轮不要实现：

1. 不要做策略治理和工具元数据化
2. 不要改造 PolicyGate 为 tool metadata 模式
3. 不要新增 `ToolMetadata`
4. 不要新增 `ToolRiskLevel`
5. 不要新增 `ToolOperationType`
6. 不要新增复杂权限系统
7. 不要改变当前 ToolBroker / PolicyGate 的核心行为，除非是为了接入新子 Agent 的最小必要调整
8. 不接真实外部系统
9. 不接真实 MCP Server
10. 不接真实 Milvus / Elasticsearch / Redis
11. 不解析真实 PDF / Word
12. 不实现 OCR
13. 不实现复杂 DLP 引擎
14. 不改变 `/api/chat` 现有核心响应格式，除非保持向后兼容

---

## 需要新增或修改的文件

建议新增：

```text
app/subagents/compliance_security_agent.py
app/subagents/document_parse_agent.py
app/subagents/change_impact_analysis_agent.py

app/skills/compliance_security/SKILL.md
app/skills/document_parse/SKILL.md
app/skills/change_impact_analysis/SKILL.md
```

建议新增或扩展 schema：

```text
app/schemas/subagent.py
```

可能修改：

```text
app/main.py
app/runtime/graph.py
app/runtime/graph_state.py
app/runtime/context_builder.py
app/query/intent_recognition_node.py
app/subagents/manager.py
app/tools/policy_gate.py
README.md
```

新增测试：

```text
tests/test_compliance_security_agent.py
tests/test_document_parse_agent.py
tests/test_change_impact_analysis_agent.py
tests/test_langgraph_multi_subagent_routing.py
```

---

## 代码设计要求

### 固定 Agent Catalog

`SubAgentManager` 必须继续使用固定注册表。

要求：

1. app 启动时注册四个子 Agent：
   - `troubleshooting_agent`
   - `compliance_security_agent`
   - `document_parse_agent`
   - `change_impact_analysis_agent`
2. 不允许自由 spawn
3. 不允许根据用户输入动态 import 任意 Agent
4. `SubAgentManager.call_subagent` 是唯一调用入口

### LangGraph 路由

现有条件路由需要扩展。

建议路由规则：

```text
intent = troubleshooting -> call_troubleshooting_agent
intent = compliance_review -> call_compliance_security_agent
intent = document_parse -> call_document_parse_agent
intent = change_impact_analysis -> call_change_impact_analysis_agent
其他 -> direct_answer
```

必须保留已有 troubleshooting 流程不变。

### IntentRecognitionNode

新增规则：

`compliance_review`：

命中关键词示例：

```text
合规
隐私
敏感信息
脱敏
外发
能不能发给渠道
身份证
手机号
健康告知
医疗记录
```

`document_parse`：

命中关键词示例：

```text
解析文档
提取字段
读取 markdown
读取 json
读取 yaml
帮我总结这份文档
```

`change_impact_analysis`：

命中关键词示例：

```text
变更影响
字段变更
错误码变更
签名规则变更
接口变更
影响哪些接口
影响哪些渠道
```

输出仍需包含：

```text
intent
confidence
target_subagent
required_tools
```

### ContextBuilder

必须新增为以下子 Agent 构建上下文的能力：

```python
build_for_compliance_security_agent(...)
build_for_document_parse_agent(...)
build_for_change_impact_analysis_agent(...)
```

或在现有 `build_for_subagent` 中根据 task name 分支。

要求：

1. 只构建最小必要上下文
2. 读取对应 SKILL.md
3. 包含 rewritten_query、intent、recent_messages、short_summary
4. 包含 allowed_tools
5. 不加载完整历史
6. 不直接调用真实外部系统

### 合规安全 Agent

文件建议：

```text
app/subagents/compliance_security_agent.py
app/skills/compliance_security/SKILL.md
```

能力：

1. 对文本做隐私、敏感信息、外发风险检查
2. 检查常见敏感类型：
   - 身份证
   - 手机号
   - 银行卡
   - 健康告知
   - 医疗记录
   - 保单号
   - 密钥 / token / secret
3. 输出：
   - risk_level
   - findings
   - masked_preview
   - recommendation
   - confidence

第一阶段实现规则版，不接真实 DLP。

### 文档解析 Agent

文件建议：

```text
app/subagents/document_parse_agent.py
app/skills/document_parse/SKILL.md
```

能力：

1. 支持解析 markdown / text / json / yaml 文档内容
2. 第一阶段不用接真实 PDF / Word
3. 能提取：
   - 标题
   - 字段名
   - 错误码
   - 接口名
   - 签名规则提示
4. 输出：
   - document_type
   - summary
   - extracted_fields
   - extracted_error_codes
   - extracted_interfaces
   - warnings
   - confidence

可以使用标准库 `json` 和轻量规则解析。

如解析 yaml，可以：

1. 使用简单文本规则
2. 或新增 `pyyaml` 依赖

如果新增依赖，必须更新 `pyproject.toml` 并保证 `uv sync` 通过。

### 变更影响分析 Agent

文件建议：

```text
app/subagents/change_impact_analysis_agent.py
app/skills/change_impact_analysis/SKILL.md
```

能力：

对以下变更做影响分析：

1. 接口字段变更
2. 错误码变更
3. 签名规则变更
4. 知识文档变更

输出：

```text
change_type
affected_interfaces
affected_tools
affected_subagents
compatibility_risk
recommended_tests
rollback_suggestion
confidence
```

第一阶段规则版即可。

### 工具调用要求

每个新 Agent 的工具调用必须经过 ToolBroker / PolicyGate。

本阶段允许最小必要调整 PolicyGate，例如允许已有工具：

```text
get_knowledge
```

不要引入 ToolMetadata、risk level、operation type。

---

## 测试要求

必须新增测试覆盖：

1. IntentRecognitionNode 能识别 `compliance_review`
2. IntentRecognitionNode 能识别 `document_parse`
3. IntentRecognitionNode 能识别 `change_impact_analysis`
4. SubAgentManager catalog 包含三个新 Agent
5. 合规安全 Agent 能识别身份证、手机号、token 等敏感信息
6. 合规安全 Agent 输出 risk_level、findings、masked_preview、recommendation
7. 文档解析 Agent 能解析 markdown 文档中的接口名、字段名、错误码
8. 文档解析 Agent 能解析 json 文档
9. 变更影响分析 Agent 能识别签名规则变更影响 submitProposal / E102 / get_knowledge / troubleshooting_agent
10. LangGraph 能路由到 compliance_security_agent
11. LangGraph 能路由到 document_parse_agent
12. LangGraph 能路由到 change_impact_analysis_agent
13. `/api/chat` 对三个新意图能返回合理 answer
14. 所有已有测试继续通过

建议测试文件：

```text
tests/test_compliance_security_agent.py
tests/test_document_parse_agent.py
tests/test_change_impact_analysis_agent.py
tests/test_langgraph_multi_subagent_routing.py
```

不得要求真实外部系统。

---

## README 更新要求

README.md 必须新增：

1. 新增三个子 Agent 的说明
2. 固定 Agent Catalog 说明
3. 三个新 intent 的说明
4. 三个新 Agent 的示例请求
5. 每个 Agent 的 SKILL.md 说明
6. 当前仍是规则版、本地 MVP 的说明
7. 不接真实 PDF / Word / DLP / 外部系统的说明

必须继续保留：

1. FastAPI `/api/chat` 说明
2. LangGraph 状态机说明
3. SQLite 持久化说明
4. ToolBroker / PolicyGate 说明
5. InMemoryKnowledgeService 说明
6. FakeMCPConnector 说明
7. Runtime Execution Logging 说明
8. tool_call_logs 审计说明

---

## 验收命令

完成后必须能运行：

```bash
uv sync
uv run pytest
uv run uvicorn app.main:app --reload
```

---

## 验收请求或验收标准

### 合规安全 Agent 验收请求

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "pingan_health",
    "channel": "web",
    "user_id": "u001",
    "session_id": "s_compliance",
    "messages": [
      {
        "role": "user",
        "content": "请帮我检查这段内容是否可以外发给渠道：客户手机号 13800138000，身份证 110101199001011234，健康告知异常。"
      }
    ]
  }'
```

应返回：

```text
intent = compliance_review
answer 包含 敏感信息、脱敏、外发风险、建议
```

### 文档解析 Agent 验收请求

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "pingan_health",
    "channel": "web",
    "user_id": "u001",
    "session_id": "s_doc",
    "messages": [
      {
        "role": "user",
        "content": "请解析这份 markdown 接口文档：# submitProposal\n字段：appId, timestamp, nonce, body\n错误码：E102 签名校验失败"
      }
    ]
  }'
```

应返回：

```text
intent = document_parse
answer 包含 submitProposal、appId、timestamp、E102
```

### 变更影响分析 Agent 验收请求

```bash
curl -X POST http://127.0.0.1:8000/api/chat \
  -H "Content-Type: application/json" \
  -d '{
    "tenant_id": "pingan_health",
    "channel": "web",
    "user_id": "u001",
    "session_id": "s_change",
    "messages": [
      {
        "role": "user",
        "content": "签名规则变更：timestamp 必须加入签名原文。请分析影响哪些接口、错误码和测试。"
      }
    ]
  }'
```

应返回：

```text
intent = change_impact_analysis
answer 包含 submitProposal、E102、签名规则、回归测试或联调测试
```

所有已有验收请求仍必须通过。

