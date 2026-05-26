# AGENTS.md

## 项目目标

本项目是一个企业级健康险个险业务对接 Agent 平台 MVP。

架构蓝图参考：

- enterprise_health_insurance_agent_architecture_detailed_v3.md


请不要一次性实现完整企业级平台。本阶段目标是实现一个可以本地运行、可以测试、能体现核心架构思想的 MVP。

## 技术栈

- Python 3.12
- uv
- FastAPI
- uvicorn
- asyncio
- Pydantic
- pytest
- httpx
- LangGraph
- InternalLLMProvider 默认启用；未配置 INTERNAL_LLM_API_URL 时走本地 deterministic fallback
- OpenAI-compatible LLM Provider 代码必须完整提供，但默认不启用
- 第一阶段使用内存或者本地存储
- 第一阶段不接真实 Redis、Milvus、Elasticsearch、MCP、保险核心系统

## 架构原则

必须遵循以下原则：

1. 主 Agent 是协调者，不是所有业务逻辑的承载者。
2. QueryRewriteNode 和 IntentRecognitionNode 是固定前置节点。
3. ContextBuilder 是独立公共组件，不属于主 Agent，也不属于子 Agent。
4. 主干流程只做轻量级上下文准备。
5. 子 Agent 负责任务级深度执行。
6. 问题排查子 Agent 需要读取自己的 SKILL.md。
7. 内部简单能力通过 tools。
8. 外部系统能力通过 MCP 预留接口，第一阶段不接真实 MCP。
9. 子 Agent 工具调用必须经过 ToolCallingRunner 和 ToolExecutor；ToolBroker/PolicyGate 仅保留为受限直连工具的兼容通道，不是 `/api/chat` 主链路。
10. LangGraph 必须真实实现，不允许只写伪代码。
11. LangGraph 流程必须体现状态机节点和条件路由。
12. 多用户、多会话、多轮对话必须通过 session_key / thread_id 隔离。
13. 所有消息必须保留 original_query、rewritten_query、intent、session_key。
14. shell_exec 工具可以实现，但必须默认禁用或严格受限。

## LangGraph 要求

必须实现真实 LangGraph StateGraph，至少包含以下节点：

1. load_session
2. save_user_message
3. query_rewrite
4. intent_recognition
5. build_orchestrator_context
6. route_intent
7. call_troubleshooting_agent
8. direct_answer
9. save_assistant_message
10. compress_short_memory
11. finalize_response

必须有条件路由：

- intent = troubleshooting -> call_troubleshooting_agent
- intent != troubleshooting -> direct_answer

必须使用 session_key 作为 graph config 的 thread_id。

可以第一阶段使用内存 checkpointer，但代码结构必须预留后续替换 SQLite/PostgreSQL checkpointer 的位置。

## 真实大模型代码要求

第一阶段默认使用 InternalLLMProvider。未配置 INTERNAL_LLM_API_URL 时，InternalLLMProvider 使用本地 deterministic fallback；FakeLLMProvider 不再是 create_app() 默认注入对象。

但必须提供真实 OpenAI-compatible LLM Provider 完整代码，建议文件：

```text
app/llm/openai_provider.py
