# Tool and MCP Prompts

## Tool 调用是否使用 Prompt

当前 tool 调用不使用 prompt。

当前工具调用是结构化调用：

```text
ToolCall(name, arguments, request_id, trace_id, session_key)
```

所有工具调用必须经过：

```text
ToolBroker -> PolicyGate -> ToolRegistry -> tool handler
```

## ToolBroker / PolicyGate 是否使用 Prompt

当前未使用 prompt。

- `ToolBroker` 负责统一调用、日志、审计、错误处理。
- `PolicyGate` 负责规则判断，例如工具是否允许、`shell_exec` 是否启用、HTTP host 是否在白名单。

这些都是 Python 规则，不是 LLM prompt。

## MCPConnector / FakeMCPConnector 是否使用 Prompt

当前未使用 prompt。

`FakeMCPConnector` 是结构化 fake MCP 实现：

- `list_tools()`
- `call_tool(tool_name, arguments)`

当前 fake MCP tool：

```text
partner_trace.get_request_detail
```

它根据 `request_id` 返回固定结构化结果：

- `REQ_001`：渠道侧仍使用旧版签名规则，未将 `timestamp` 纳入签名原文。
- `REQ_002`：timestamp 过期或渠道侧时间窗口异常。
- 未知 requestId：`found=false`。

## 当前 tools 是结构化调用还是 Prompt 驱动

当前是结构化调用，不是 prompt 驱动。

| tool | 当前调用方式 | 是否 prompt 驱动 |
| --- | --- | --- |
| `query_internal_log` | `ToolCall.arguments.request_id` | 否 |
| `get_knowledge` | `ToolCall.arguments.query/top_k` | 否 |
| `partner_trace.get_request_detail` | `ToolCall.arguments.request_id` | 否 |
| `shell_exec` | `ToolCall.arguments.command` | 否 |
| `http_request` | 结构化 HTTP 参数 | 否 |
| `mcp_http.call_tool` | 结构化 MCP HTTP 参数 | 否 |

## partner_trace.get_request_detail 当前如何触发

当前触发位置：`app/subagents/troubleshooting_agent.py`

触发逻辑：

1. `TroubleshootingAgent` 先尝试从 query 或 short summary 提取 `request_id`。
2. 如果有 `request_id`，先调用 `query_internal_log`。
3. 始终调用 `get_knowledge` 查询知识。
4. 如果内部日志缺失，或内部日志显示 `E102`，或疑似原因包含 partner/timestamp/渠道侧行为，则调用：
   - `partner_trace.get_request_detail`
5. 该调用仍经过 `ToolBroker / PolicyGate`。

## 后续如果用 LLM 决定工具调用

建议不要把工具选择 prompt 写进 tool handler，也不要写进 `PolicyGate`。

推荐位置：

- `ContextBuilder`：构造可供模型理解的 tool context。
- 未来 `PromptRegistry`：管理 tool selection prompt。
- 子 Agent runtime loop：读取 selected skill、allowed tools 和 evidence 后决定工具调用。
- `ToolBroker / PolicyGate`：继续作为后置强制校验，不信任模型输出。

## 推荐 Tool Selection Prompt 模板

该模板只是后续建议，当前未实现。

```text
你是 {agent_name} 的工具选择器。
你只能从 allowed_tools 中选择是否调用工具。

用户问题：
{query}

selected_skill:
{selected_skill_summary}

已有证据：
{evidence_summary}

allowed_tools:
{allowed_tools}

要求：
1. 如果已有证据不足，可以选择一个最必要的工具。
2. 不得选择 allowed_tools 之外的工具。
3. 不得构造敏感参数。
4. 输出必须是 JSON。
```

## 推荐输出 JSON Schema

```json
{
  "type": "object",
  "required": ["should_call_tool", "tool_name", "arguments", "reason"],
  "properties": {
    "should_call_tool": {"type": "boolean"},
    "tool_name": {"type": ["string", "null"]},
    "arguments": {"type": "object"},
    "reason": {"type": "string"}
  }
}
```

## 安全边界

即使未来由 LLM 选择工具，也必须保持：

- ToolBroker 必须记录审计。
- PolicyGate 必须做最终允许/拒绝判断。
- `shell_exec` 继续默认禁用。
- MCP 和 HTTP 工具必须使用结构化参数，不接受自由文本 shell 或 URL 拼接。

