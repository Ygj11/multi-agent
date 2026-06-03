# Target Architecture

本文描述当前代码正在收敛的目标架构。它不是空想蓝图，而是以当前 `app/` 实现为基线的后续演进方向。

## Harness Core

目标不是把所有逻辑堆进一个 Agent，而是形成稳定 Harness：

```text
FastAPI
-> RequestAdapter
-> LangGraph MainGraph
-> Query/Intent/Entity Understanding
-> AgentCard Router
-> SubAgent
-> Skill / Knowledge / Tool Loop
-> Approval / Verification / Memory
-> ResponseAdapter
```

## MainGraph

MainGraph 负责请求级状态机：

- 加载会话和短期记忆。
- 保存用户消息。
- query rewrite。
- intent recognition。
- 构建 orchestrator context。
- discover/select AgentCard。
- assemble task。
- dispatch sub agent。
- 捕获 clarification。
- 捕获 human approval。
- 执行 `pre_answer_verify`。
- 保存 assistant message。
- 压缩短期记忆。
- finalize response。

Graph 应保持“薄节点 + handler”的方向。当前已经拆出：

- `ClarificationHandler`
- `ApprovalGraphHandler`
- `VerificationHandler`
- `MessageCommitHandler`
- `MemoryCommitHandler`

## SubAgent

子 Agent 执行边界：

- 从任务信封读取 AgentCard。
- 只看自己 AgentCard 授权的 tools。
- 通过 `ContextBuilder` 构建 `SubAgentContext`。
- 通过 Skill metadata 选择 skill。
- 只加载选中的 skill body。
- 缺少 selected skill required entities 时 clarification。
- 使用 `ToolCallingRunner` 进入 LLM + tools loop。
- 返回结构化 `SubAgentResult`。

不是所有问题都必须强制匹配具体 Skill。没有高置信 Skill 时可以 generic execution，由子 Agent 依靠 AgentCard、上下文和可见工具直接回答或 tool calling。

## Entity / Routing

目标实体体系是三层：

1. `EntityExtractor` 从 `app/query/entity_patterns.yaml` 抽取通用实体。
2. AgentCard 的 `required_entities` / `optional_entities` 负责 Agent 粗粒度召回和打分。
3. Skill 的 `required_entities` / `optional_entities` 负责具体流程执行前检查。

`ConversationWindow` 不应该增加 `last_policy_no`、`last_claim_no` 这类业务字段；动态实体进入 `EntityBag`。

Agent 选择目标是 hybrid router：

```text
Rule Top-K recall
-> if clear winner: rule select
-> else LLM rerank only among Top-K AgentCard summaries
-> fallback/clarification on invalid output
```

## Skill

Skill 目标是 metadata-first + progressive disclosure：

```text
SkillCatalog.scan metadata
-> SkillRuleScorer
-> SkillLLMReranker
-> SkillSelectionPolicy
-> SkillLoader.load(selected_skill_id)
```

LLM rerank 不能看到全部 skill body，也不能编造 skill_id。

## Tool System

目标工具系统保持单一执行入口：

```text
ToolRegistry.list_tools_for_agent
-> OpenAI function schema
-> ToolCallingRunner
-> ToolExecutor
-> ToolExecutionPipeline
```

ToolExecutor 负责：

- tool exists
- AgentCard visibility
- required arguments
- tool/resource authorization
- `VerificationService(pre_tool)`
- write tool approval guard
- local/MCP dispatch
- tool execution log
- evidence save

LLMProvider 永远不执行工具。

## Human Approval

写工具审批目标是 Graph checkpoint + ApprovalStore 混合方案：

- LangGraph checkpointer 保存执行状态。
- ApprovalStore 保存审批业务记录。
- callback approved 后回到 Graph resume path。
- 恢复后再次遇到写工具，创建下一张审批单。
- 每个写工具调用对应一张 ApprovalRequest。
- `parent_approval_id`、`root_approval_id`、`approval_depth`、`next_approval_id` 形成审批链。

当前代码已经实现 Graph resume 路径和审批链字段。默认 checkpointer 仍是 MemorySaver；SQLite final state snapshot 由 `SQLiteCheckpointStore` 保存。

## Verification

长期目标是 Verification Framework，而不是单独的 FinalComplianceChecker 节点。

当前出口：

```text
pre_answer_verify
-> VerificationService(stage="pre_answer")
-> DataPermissionVerifier
-> ComplianceVerifier
```

Verification 目标阶段包括：

- `request_access`
- `agent_access`
- `pre_skill`
- `pre_tool`
- `post_tool`
- `pre_answer`

当前主要落地的是 `pre_tool` 和 `pre_answer`。Agent/tool/resource access 仍由确定性 AuthorizationService/ResourceAccessService 负责，避免让 LLM 决策权限。

## Auth / Data Permission

权限目标分三层：

- Agent 级：能否使用某个子 Agent。
- Tool 级：能否调用某个工具。
- Result 级：最终回答能否返回这些字段，是否需要脱敏。

机构级权限应优先于个人散点权限建模。Principal 可包含 `tenant_id`、`org_id`、`org_path`、roles、scopes、data_permissions、attributes。最终敏感输出由 `VerificationService(pre_answer)` 统一处理。

## Knowledge

KnowledgeService 是检索抽象：

- 默认：`DisabledKnowledgeService`。
- 启用：`KnowledgeAPIClient`。
- 返回：统一 `KnowledgeChunk`，由 `KnowledgeChunkPostProcessor` 归一化。

知识可以作为：

- ContextBuilder 的 lightweight hints / subagent knowledge hint。
- public tool `rag_search_tool`。

不再在生产代码中保留内置 mock chunks。

## Memory

当前策略：

- messages 表保存完整历史。
- runtime 加载最近消息窗口。
- short_term_memory 保存 `short_summary`。
- 每轮回答后 `compress_short_memory` 更新 summary。

长期可以演进结构化 memory，但不要在当前主链路里把所有业务实体写死到 ConversationWindow 顶层。

## Audit / Evidence

目标职责：

| 模块 | 职责 |
|---|---|
| `ToolExecutionLogStore` | 工具执行事实流水 |
| `ApprovalStore` | 审批业务状态和审批事件 |
| `EvidenceStore` | 回答/验证可引用证据 |

## Storage

MVP 使用 SQLite。后续生产可替换为 PostgreSQL/Redis/向量库，但应通过当前抽象替换，不直接把外部存储耦合进 Graph 节点。

当前 SQLite 表覆盖：

- messages
- short_term_memory
- graph_checkpoints
- tool_execution_logs
- approval_requests
- approval_events
- evidence

## 当前优先级

已完成 P0/P1 后，后续更适合推进：

1. 批量清理历史 mojibake 文案。
2. 官方 SQLite/Postgres LangGraph checkpointer 接入。
3. Verification 阶段扩展到 `request_access`、`pre_skill`、`post_tool`。
4. 机构级权限中心/资源权限服务接入。
5. 真实 Knowledge API 和 MCP server 对接。
