# LLM Provider Prompts

## FakeLLMProvider 当前是否使用 Prompt

当前 `FakeLLMProvider` 不使用真正的 prompt。

代码位置：`app/llm/fake_provider.py`

它的行为是：

1. 接收 `messages: list[dict[str, str]]`。
2. 把所有 `message.content` 拼接成一个字符串。
3. 如果文本包含 `E102`，返回固定文本：
   - `E102 通常表示签名校验失败，请检查 timestamp、密钥版本和字段排序。`
4. 否则返回：
   - `这是 FakeLLMProvider 的确定性回复。`

这属于规则返回，不是 LLM prompt 推理。

## FakeLLMProvider 是否在主链路使用

当前 `app/main.py` 会实例化：

```python
_llm = FakeLLMProvider()
```

但当前主链路没有把 `_llm` 注入 LangGraph 节点，也没有任何节点调用 `FakeLLMProvider.chat()` 或 `chat_json()`。

因此，当前默认模型存在，但没有参与 `/api/chat` 的主流程回答生成。

## OpenAICompatibleLLMProvider 当前是否真实启用

当前默认不启用。

代码位置：`app/llm/openai_provider.py`

启用条件：

- `ENABLE_REAL_LLM=true`
- 配置 `OPENAI_API_KEY`
- 可选配置 `OPENAI_BASE_URL`
- 配置 `OPENAI_MODEL`

当前测试中会验证它在未启用时不影响运行。

## OpenAICompatibleLLMProvider 预留了哪些参数

`OpenAICompatibleLLMProvider.chat()` 和 `chat_json()` 支持：

- `messages`
- `tools`
- `timeout`
- `OPENAI_API_KEY`
- `OPENAI_BASE_URL`
- `OPENAI_MODEL`
- `ENABLE_REAL_LLM=true`

但 provider 自己不构造 prompt，只把调用方传入的 `messages` 转发给 OpenAI-compatible API。

## 当前不存在的真实 Prompt

当前没有以下运行时 prompt：

- main agent system prompt
- query rewrite system prompt
- intent recognition system prompt
- troubleshooting system prompt
- final answer system prompt
- tool calling system prompt

这些在 V3 架构文档中有设计方向，但当前代码没有实现。

## 未来接真实 LLM 时 messages 建议

### chat 文本回答

```json
[
  {
    "role": "system",
    "content": "你是企业健康险个险业务 Agent。必须基于给定证据回答，不得编造。"
  },
  {
    "role": "user",
    "content": "用户问题：{original_query}"
  },
  {
    "role": "user",
    "content": "上下文：{context_json}"
  }
]
```

### chat_json 结构化输出

```json
[
  {
    "role": "system",
    "content": "你必须输出 JSON object，字段包括 diagnosis、evidence、recommendation、responsibility、confidence。"
  },
  {
    "role": "user",
    "content": "{task_and_context_json}"
  }
]
```

## 建议输出约束

真实 LLM 接入时，应至少约束：

- 不得编造 requestId、日志、trace、客户、保单、密钥。
- 所有事实性结论必须对应 evidence。
- 工具调用结果优先于模型猜测。
- 低置信度时必须明确说明需要补充信息。

## 改造注意事项

- 不要直接让 provider 内部硬编码业务 prompt。
- Prompt 应由 `ContextBuilder` 或未来 `PromptRegistry` 构造。
- Provider 只负责模型调用，不负责业务语义。
- 保留 `FakeLLMProvider` 作为测试 fallback。

