# Query Rewrite Prompts

## 当前代码位置

- 运行时代码：`app/query/query_rewrite_node.py`
- 相关但未运行时使用的 skill 文档：`app/skills/query_rewrite/SKILL.md`
- LangGraph 调用位置：`app/runtime/graph.py` 的 `query_rewrite` 节点

## 当前是否使用 Prompt

当前 query 改写没有调用 LLM prompt，是规则实现。

`QueryRewriteNode` 没有读取 `app/skills/query_rewrite/SKILL.md`，也没有调用 `FakeLLMProvider` 或 `OpenAICompatibleLLMProvider`。

## 当前规则

当前规则来自 `QueryRewriteNode.rewrite()`：

1. 如果用户输入包含 `REQ_xxx` 格式 requestId，且包含 `E102`：
   - 输出：`排查 requestId={request_id} 的健康险个险接口 E102 错误原因`
2. 如果用户输入像多轮追问，并且 `recent_messages` 或 `short_summary` 中包含 `E102`、`requestId` 或 `REQ_`：
   - 输出：`继续排查上一轮 requestId 的 E102 签名校验失败问题，并判断问题归属`
3. 否则：
   - 原样返回 `original_query`

当前追问关键词：

```text
这个
那个
一般是谁
谁的问题
继续
刚才
```

## 当前 SKILL.md 状态

`app/skills/query_rewrite/SKILL.md` 描述了 query rewrite 的任务指令、输出要求和示例，但当前只是文档/skill 指令，没有被运行时代码读取。

## 后续 LLM Prompt 模板建议

如果后续要将 query rewrite 改为 LLM prompt，可以使用如下模板。该模板是建议，不是当前运行时代码。

### System Prompt 建议

```text
你是健康险个险业务 Agent 的 query 改写器。
你的任务是把用户当前输入改写为清晰、可检索、可路由、可用于工具调用的标准查询。

要求：
1. 必须保留用户原始语义。
2. 不得编造产品、接口、保单、客户、渠道、requestId 或错误码。
3. 如果用户输入包含 requestId 和错误码，必须原样保留。
4. 如果用户是多轮追问，只能基于 recent_messages 和 short_summary 补全指代对象。
5. 如果上下文不足，返回原始 query。
6. 输出必须是 JSON，不要输出解释。
```

### User Prompt 建议

```text
original_query:
{original_query}

recent_messages:
{recent_messages}

short_summary:
{short_summary}

known_business_terms:
- submitProposal
- E102
- requestId
- timestamp
- 签名校验失败

请输出改写结果。
```

## 推荐输入字段

- `request_id`
- `trace_id`
- `session_key`
- `tenant_id`
- `user_id`
- `original_query`
- `recent_messages`
- `short_summary`
- `business_domain`
- `known_interface_names`
- `known_error_codes`

## 推荐输出 JSON Schema

```json
{
  "type": "object",
  "required": ["original_query", "rewritten_query", "changed", "reason", "confidence"],
  "properties": {
    "original_query": {"type": "string"},
    "rewritten_query": {"type": "string"},
    "changed": {"type": "boolean"},
    "reason": {"type": "string"},
    "confidence": {"type": "number"},
    "extracted_request_id": {"type": ["string", "null"]},
    "extracted_error_code": {"type": ["string", "null"]},
    "extracted_interface_name": {"type": ["string", "null"]}
  }
}
```

## 改造注意事项

- 保留当前规则实现作为 fallback。
- Prompt 版本变更必须有回归测试覆盖 `REQ_001`、`REQ_002` 和多轮追问。
- 不要让 LLM 编造 requestId。

