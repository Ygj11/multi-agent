# Intent Recognition Prompts

## 当前代码位置

- 运行时代码：`app/query/intent_recognition_node.py`
- LangGraph 调用位置：`app/runtime/graph.py` 的 `intent_recognition` 节点

## 当前是否使用 Prompt

当前意图识别没有调用 LLM prompt，是规则实现。

`IntentRecognitionNode` 没有读取任何 `SKILL.md`，也没有调用 LLM provider。

## 当前支持的 Intent

| intent | target_subagent | 当前触发方式 |
| --- | --- | --- |
| `troubleshooting` | `troubleshooting_agent` | `E102`、`失败`、`报错`、`requestId`、`REQ_`、`排查`、字段缺失、回调失败等关键词。 |
| `compliance_review` | `compliance_security_agent` | `合规`、`隐私`、`敏感信息`、`脱敏`、`外发`、`身份证`、`手机号`、`token` 等关键词。 |
| `document_parse` | `document_parse_agent` | `解析文档`、`文档解析`、`markdown`、`json`、`yaml`、`接口文档` 等关键词。 |
| `change_impact_analysis` | `change_impact_analysis_agent` | `变更影响`、`影响分析`、`字段变更`、`错误码变更`、`签名规则变更` 等关键词。 |
| `product_rule_qa` | 无 | `等待期`、`责任`、`条款`。当前走 `direct_answer`。 |
| `unknown` | 无 | 未命中规则。 |

## 当前规则

当前规则优先级：

1. 如果是多轮追问，且历史上下文包含 `E102`、`requestId` 或 `REQ_`，直接识别为 `troubleshooting`。
2. 命中合规关键词，识别为 `compliance_review`。
3. 命中文档解析关键词，识别为 `document_parse`。
4. 命中变更影响关键词，识别为 `change_impact_analysis`。
5. 命中问题排查关键词，识别为 `troubleshooting`。
6. 命中产品条款关键词，识别为 `product_rule_qa`。
7. 否则 `unknown`。

## 后续 LLM / 小模型分类建议

如果后续改为 LLM 或小模型分类，建议仍保留规则优先级作为 guardrail，尤其是：

- `REQ_` + `E102` 必须稳定路由到 `troubleshooting`。
- 敏感信息、token、password 等合规场景应优先路由到 `compliance_review`。
- 未知意图应允许低置信度 fallback，不要强行分配子 Agent。

### System Prompt 建议

```text
你是健康险个险业务 Agent 的意图分类器。
你只负责根据用户输入、改写后 query、最近会话摘要判断意图和目标子 Agent。

要求：
1. 只能从给定 intent 列表中选择。
2. 不要回答用户问题。
3. 不要调用工具。
4. 如果无法判断，返回 unknown。
5. 输出必须是 JSON。
```

### Intent 列表

```text
troubleshooting
compliance_review
document_parse
change_impact_analysis
product_rule_qa
unknown
```

## 推荐输出 JSON Schema

```json
{
  "type": "object",
  "required": ["intent", "confidence", "target_subagent", "required_tools", "reason"],
  "properties": {
    "intent": {
      "type": "string",
      "enum": [
        "troubleshooting",
        "compliance_review",
        "document_parse",
        "change_impact_analysis",
        "product_rule_qa",
        "unknown"
      ]
    },
    "confidence": {"type": "number"},
    "target_subagent": {"type": ["string", "null"]},
    "required_tools": {
      "type": "array",
      "items": {"type": "string"}
    },
    "reason": {"type": "string"},
    "detected_entities": {
      "type": "object",
      "properties": {
        "request_id": {"type": ["string", "null"]},
        "error_code": {"type": ["string", "null"]},
        "interface_name": {"type": ["string", "null"]}
      }
    }
  }
}
```

## 改造注意事项

- 当前测试依赖确定性规则结果，LLM 分类必须可回退。
- 建议先实现分类器接口，再用规则和 LLM 双跑评估。
- 不建议直接用自由文本 prompt 替换全部规则。

