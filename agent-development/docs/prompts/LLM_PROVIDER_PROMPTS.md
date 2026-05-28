# LLM Provider Prompts

## 当前默认 Provider

当前 `app/main.py::create_app` 通过 `app/llm/factory.py::build_llm_provider` 创建全局 LLMProvider：

```text
ENABLE_OPENSDK_LLM=true -> OpenSDKLLMProvider
其他情况 -> InternalLLMProvider
```

`InternalLLMProvider` 是默认实现。配置 `INTERNAL_LLM_API_URL` 时走内部数智 LLM HTTP API；未配置 URL 时，`InternalLLMProvider` 自己提供本地 deterministic fallback，方便本地 MVP 和测试运行。

项目不再保留单独的 fake provider 文件；本地 MVP 和测试运行所需的确定性行为由 `InternalLLMProvider` 在未配置内部 LLM URL 时提供。

## Provider 不负责什么

LLMProvider 只负责模型调用和响应归一化：

- 不执行工具
- 不做工具权限判断
- 不选择所有工具
- 不绕过 `ToolCallingRunner`
- 不绕过 `ToolExecutor`
- 不做最终合规出口替代

工具循环由 `app/subagents/tool_calling_runner.py::ToolCallingRunner.run` 负责；真正工具执行、AgentCard 可见性二次校验、MCP 分发和工具执行日志由 `app/tools/executor.py::ToolExecutor` 负责。

## 当前会传入 LLM 的主要场景

| scene | 调用位置 | 说明 |
| --- | --- | --- |
| `query_rewrite` | `app/query/query_rewrite_node.py` | 多轮上下文消解和 query 改写，失败时走 EntityExtractor / EntityBag fallback。 |
| `intent_recognition` | `app/query/intent_recognition_node.py` | intent/sub_intent JSON 分类，失败时走新规则 fallback。 |
| `agent_selection` | `app/agents/llm_router.py` | 规则 Top-K 不确定时，在候选 AgentCard 摘要内重排。 |
| `subagent_reasoning` | `app/subagents/tool_calling_runner.py` | 子 Agent ReAct-style tool loop。 |
| `final_compliance` | `app/compliance/final_checker.py` | 最终返回前合规辅助检查，规则脱敏仍是强制基础。 |
| `summary` | `app/memory/short_term_memory_manager.py` | `previous_summary + current_turn -> new_summary` 短期记忆滚动摘要。 |

## 可选 OpenAI-compatible Provider

OpenAI-compatible 调用由 `app/llm/opensdk_provider.py::OpenSDKLLMProvider` 提供；旧的 `app/llm/openai_provider.py` 兼容别名已移除。

启用条件：

```text
ENABLE_OPENSDK_LLM=true
OPENAI_API_KEY=...
OPENAI_BASE_URL=...
OPENAI_MODEL=...
```

## Prompt 维护注意事项

- 不要让 provider 内部硬编码业务 prompt。
- Prompt 应由调用节点根据 scene 构造。
- Provider 只转发 `messages` / `tools` 并归一化 `LLMResponse`。
- 如果新增 scene，需要同步检查 `app/llm/model_config.py::get_llm_model` 和对应节点测试。
