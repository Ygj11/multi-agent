# Current Architecture

本文是当前代码主链路的同步快照。结论以源码为准，主要对应 `app/main.py`、`app/runtime/graph.py`、`app/subagents/base.py`、`app/tools/executor.py`、`app/approval/*`、`app/verification/*`。

## 当前定位

项目是一个企业级健康险个险业务对接 Agent 平台 MVP。当前不是简单聊天机器人，而是一个以 FastAPI + LangGraph 为主编排、以 AgentCard/Skill/Tool/Verification/Approval 为执行边界的多 Agent Harness。

主 Agent 只做任务级编排和路由，不承载所有业务逻辑。子 Agent 负责深度任务执行，工具调用统一经过 `ToolCallingRunner -> ToolExecutor`。最终返回用户前统一经过 `pre_answer_verify -> VerificationService`，旧的 `final_compliance_check -> FinalComplianceChecker` 主路径已经被替换。

## 启动装配

`app/main.py::create_app` 当前装配顺序的核心对象是：

```text
get_settings()
-> build_storage()
-> build_llm_provider()
-> ShortTermMemoryManager
-> build_checkpointer()
-> build_knowledge_service()
-> ToolRegistry
-> register_public_tools()
-> register_agent_private_tools()
-> register_admin_restricted_tools()
-> build_verification_service()
-> ToolExecutor
-> ToolCallingRunner
-> ApprovalService
-> SkillCatalog / SkillSelector / ContextBuilder
-> SubAgentManager
-> AgentCardLoader.validate_with_skill_catalog()
-> AgentGraphFactory(...).build()
-> AgentOrchestrator
-> FastAPI routes
-> lifespan MCP discovery
```

默认知识服务是 `DisabledKnowledgeService`；只有 `ENABLE_KNOWLEDGE_API=true` 且 `KNOWLEDGE_API_URL` 配置后才使用 `KnowledgeAPIClient`。MCP 是消费方能力，在 FastAPI lifespan startup 中通过 `MCPClientManager.initialize()` 发现并注册到 `ToolRegistry`。

## MainGraph

当前 LangGraph 节点来自 `app/runtime/graph.py::AgentGraphFactory.build`：

```text
route_entry
load_session
resume_approved_tool
save_user_message
query_rewrite
intent_recognition
build_orchestrator_context
discover_agents
select_agent
assemble_task
dispatch_agent
build_clarification_answer
check_human_approval_required
create_approval_request
submit_approval_request
pause_for_approval
pre_answer_verify
regenerate_compliant_answer
fallback_answer
save_assistant_message
compress_short_memory
finalize_response
```

普通请求路径：

```text
/api/chat
-> RequestAdapter
-> AgentOrchestrator.run
-> route_entry(normal)
-> load_session
-> save_user_message
-> query_rewrite
-> intent_recognition
-> build_orchestrator_context
-> discover_agents
-> select_agent
-> assemble_task
-> dispatch_agent
-> check_human_approval_required
-> pre_answer_verify
-> save_assistant_message
-> compress_short_memory
-> finalize_response
-> ResponseAdapter
```

clarification 路径：`query_rewrite`、`intent_recognition`、`select_agent` 任一节点设置 `need_clarification=true` 时，进入：

```text
build_clarification_answer
-> pre_answer_verify
-> save_assistant_message
-> compress_short_memory
-> finalize_response
```

审批 pending 路径：

```text
dispatch_agent
-> check_human_approval_required(required)
-> create_approval_request
-> submit_approval_request
-> pause_for_approval
-> pre_answer_verify
-> save_assistant_message
-> compress_short_memory
-> finalize_response
```

审批恢复路径：

```text
/api/approval/callback approved
-> ApprovalService.handle_callback
-> AgentOrchestrator.resume_after_approval
-> route_entry(resume)
-> resume_approved_tool
-> check_human_approval_required
-> pre_answer_verify 或再次创建下一审批
```

`AgentOrchestrator` 当前使用 `thread_id = f"{session_key}:{request_id}"`，不是纯 `session_key`。LangGraph checkpointer 默认是 `MemorySaver`；项目自己的 `SQLiteCheckpointStore` 保存每次图执行后的最终 state snapshot。

## Agent / Skill / Tool

AgentCard 文件位于 `app/agents/cards/*.yaml`，用于声明子 Agent 能力、支持 intent、工具可见性、skills、RAG namespace、memory policy 和 access policy。

Skill 采用 metadata-first：

```text
SkillCatalog.scan()
-> 只解析 app/skills/{agent}/{skill}/SKILL.md frontmatter
-> SkillSelector 只看 metadata
-> 选中 skill 后 SkillLoader 才加载完整 body
```

`SkillSelector` 当前已经拆为：

- `app/skills/scorer.py::SkillRuleScorer`
- `app/skills/reranker.py::SkillLLMReranker`
- `app/skills/selection_policy.py::SkillSelectionPolicy`
- `app/skills/selector.py::SkillSelector` facade

`ContextBuilder` 仍保留外观入口，但内部已拆出：

- `app/runtime/context/knowledge_hint_builder.py::KnowledgeHintBuilder`
- `app/runtime/context/skill_context_resolver.py::SkillContextResolver`

子 Agent 如果继承 `BaseSubAgent`，执行模板是：

```text
读取 AgentCard
-> 计算 allowed tools
-> ContextBuilder.build_for_subagent
-> skill selection / required entity check
-> 构造 LLM messages
-> ToolCallingRunner.run
-> SubAgentResult
```

没有明确 skill 匹配时，子 Agent 可以走 generic execution，不会因为没有 skill 就强行澄清。只有选中的 skill 声明了 `required_entities` 且缺失时，才进入 clarification。

## Tool Loop

工具 schema 最终以 OpenAI function-calling 格式传给 LLM。LLM 不直接看到 `scope/source/is_write/metadata/callable` 等内部字段。

工具调用链路：

```text
ToolCallingRunner.run
-> LLMProvider.chat(messages, tools, scene="subagent_reasoning")
-> normalize_tool_call
-> ToolExecutor.execute
-> ToolExecutionPipeline guards
-> local callable 或 MCPClientManager.call_tool
-> role=tool observation append
-> 下一轮 LLM
```

`ToolExecutionPipeline` 顺序是：

```text
tool exists
-> AgentCard visibility
-> required arguments
-> AuthorizationService / ResourceAccessService
-> VerificationService(pre_tool)
-> approval guard(is_write)
-> execute
```

`ToolCallingRunner` 当前具备：

- `max_iterations`
- `max_consecutive_tool_failures`
- `max_same_tool_failures`
- `max_duplicate_tool_calls`

写工具不会直接执行。`is_write=true` 时返回 `human_approval_required`，由主图创建审批。

## Verification / Auth

当前最终出口是 `pre_answer_verify`，由 `app/runtime/handlers/verification_handler.py::VerificationHandler` 调用 `VerificationService(stage="pre_answer")`。

`build_verification_service()` 当前注册：

- `DataPermissionVerifier`
- `ComplianceVerifier`

职责边界：

- `AuthorizationService`：Agent/tool 粗粒度可用性。
- `ResourceAccessService`：机构/资源级访问控制。
- `VerificationService(pre_tool)`：工具执行前的可插拔安全校验。
- `VerificationService(pre_answer)`：最终外发前验证、脱敏、patch/retry/fallback。

## Storage

SQLite 当前承担：

- `messages`
- `short_term_memory`
- `graph_checkpoints`
- `tool_execution_logs`
- `approval_requests`
- `approval_events`
- `evidence`

`messages` 保留完整历史；运行时加载最近消息窗口，`short_summary` 承接更早上下文。`compress_short_memory` 现在由 `MemoryCommitHandler` 调用 `ShortTermMemoryManager.compress_after_turn` 完成。

## 当前业务流程示例

以“保全任务完成后异常处理”为例：

```text
用户：保全任务完成了，但是保单信息没有更新，受理号 APPLY_POLICY_UPDATE_FAIL，保单号 P001，保全项退保
-> query_rewrite 抽取 apply_seq/policy_no/endorseType
-> intent_recognition 识别 troubleshooting / endo_completion_aftercare
-> select_agent 选择 troubleshooting_agent
-> assemble_task 构造任务信封
-> BaseSubAgent.run 选择 troubleshooting_agent.endo_completion_aftercare
-> ToolCallingRunner 第一轮调用 query_endo_task_record
-> ToolExecutor 执行本地查询工具
-> LLM 根据 9 节点失败和 response_body 调用 notice_policy_update
-> ToolExecutor 发现 notice_policy_update is_write=true
-> 返回 human_approval_required
-> Graph 创建审批单并返回 pending
```

审批通过后，callback 恢复图执行，先执行原 pending tool，再继续 tool loop。如果恢复后又遇到第二个写工具，Graph 会再次创建新的 ApprovalRequest，而不是把第二次审批需求当作普通错误。

## 当前仍需注意

- 大量历史中文文案/测试字符串仍存在 mojibake，暂未批量清理。
- `app/integrations/*` 多数是未来外部系统适配器或示例，不代表已进入主链路。
- LangGraph 官方 SQLite checkpointer 只有在可用依赖存在时才启用；默认仍是 `MemorySaver` + 项目自定义 SQLite final state snapshot。
