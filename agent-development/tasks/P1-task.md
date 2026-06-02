# P1 Platform Slimming Tasks

P1 任务目标：在 P0 主链路瘦身稳定后，继续拆清上下文、skill、verification、evidence、配置和 integrations 的边界。P1 不应抢在 P0 之前大规模做，否则会和核心链路 refactor 互相干扰。

## 1. 拆 SkillSelector 为 Scorer / Reranker / Policy

### 目标

把 rule scoring、LLM rerank、fallback policy 拆开，降低 `SkillSelector` 的复杂度。

### 为什么要做

当前 `app/skills/selector.py` 同时处理规则打分、LLM 重排、fallback、默认 skill、日志。随着 skill 增多，选择策略会越来越难维护。

### 涉及文件

- `app/skills/selector.py`
- 新增 `app/skills/scorer.py`
- 新增 `app/skills/reranker.py`
- 新增 `app/skills/selection_policy.py`
- `app/schemas/skill.py`
- `tests/test_skill_selector.py`
- `tests/test_skill_selector_llm_rerank.py`

### 建议实现

```text
SkillRuleScorer.score(context, metadata)
SkillLLMReranker.rerank(top_k_metadata)
SkillSelectionPolicy.decide(rule_scores, llm_result)
SkillSelector.select(...)
```

### 验收标准

- Skill selection 阶段仍只看 metadata。
- 只有 selected skill 后才加载完整 body。
- LLM 不能编造 skill_id。
- 旧选择结果保持一致。

## 2. 拆 ContextBuilder 职责

### 目标

让 `ContextBuilder` 专注上下文组装，把 skill selection、required entity check、knowledge hint 构建变成可替换组件。

### 为什么要做

当前 `ContextBuilder` 同时负责 orchestrator context、subagent context、skill selection、skill body loading、knowledge hint、required entity check。它已经接近“上帝对象”。

### 涉及文件

- `app/runtime/context_builder.py`
- `app/skills/*`
- `app/knowledge/*`
- `app/schemas/runtime.py`
- `tests/test_skill_context_builder.py`
- `tests/test_skill_required_entities.py`

### 建议实现

新增：

```text
app/runtime/context/orchestrator_context_builder.py
app/runtime/context/subagent_context_builder.py
app/runtime/context/knowledge_hint_builder.py
```

或保留 `ContextBuilder` 外观，内部委托：

```text
SkillContextResolver
KnowledgeHintBuilder
RequiredEntityResolver
```

### 验收标准

- `ContextBuilder.build_for_orchestrator` 行为不变。
- `ContextBuilder.build_for_subagent` 行为不变。
- 缺实体仍 clarification。
- selected skill body 仍是按需加载。

## 3. 统一 Runtime Handler 层

### 目标

把 clarification、verification、approval pause、message commit、memory commit 做成 runtime handler，进一步降低 Graph 节点复杂度。

### 为什么要做

P0 会先拆 Graph 中最重的审批/验证逻辑。P1 继续统一 runtime handler 风格，让 Graph 更接近纯状态机。

### 涉及文件

- `app/runtime/graph.py`
- `app/runtime/handlers/*`
- `app/session/message_store.py`
- `app/memory/short_term_memory_manager.py`
- `app/verification/*`

### 建议实现

```text
ClarificationHandler.build_answer(state)
VerificationHandler.pre_answer(state)
MessageCommitHandler.save_user/save_assistant(state)
MemoryCommitHandler.compress(state)
```

### 验收标准

- Graph 节点基本只调用 handler。
- handler 单元测试覆盖。
- Graph path 不变。

## 4. 规范 integrations 预留目录

### 目标

降低“看起来已经接入，但实际只是预留”的误解成本。

### 为什么要做

`app/integrations/` 目前有很多 TODO 示例类，如真实保险核心、日志平台、向量服务、长期记忆、MCP HTTP 等。它们是合理预留，但新开发者容易误判为主链路依赖。

### 涉及文件

- `app/integrations/*`
- 可能新增 `app/integrations/README.md`

### 建议实现

每个文件顶部统一标注：

```text
Not wired into main path yet.
Future integration placeholder.
```

或拆目录：

```text
app/integrations/examples/
app/integrations/future/
```

### 验收标准

- 主链路是否使用一目了然。
- 不删除未来扩展点。
- 不影响 imports 和 tests。

## 5. 强化 Auth / Verification 边界

### 目标

明确 Agent access、Tool access、Resource access、Final answer verification 四类权限/验证职责。

### 为什么要做

当前权限链路已经有雏形，但 `AuthorizationService`、`ResourceAccessService`、`VerificationService`、`DataPermissionVerifier` 的边界需要更清楚，方便后续接 IAM 和机构权限中心。

### 涉及文件

- `app/auth/*`
- `app/verification/*`
- `app/tools/executor.py`
- `app/runtime/graph.py`
- `tests/test_enterprise_harness_p0_p1.py`

### 建议实现

边界定义：

```text
AuthorizationService: can use agent/tool?
ResourceAccessService: can access this resource?
VerificationService pre_tool: is this action safe to invoke?
VerificationService pre_answer: can this answer be returned?
```

### 验收标准

- 每个 service 的职责在代码注释和测试中清楚。
- tool 权限拒绝和 answer 脱敏不混在一起。
- `auth_context` 继续贯穿 graph/task/tool/approval/verification。

## 6. Evidence / Audit 收敛

### 目标

避免 tool log、approval event、evidence 三套记录职责重叠。

### 为什么要做

企业上线需要审计，但多套记录如果边界不清，会造成重复、缺字段或追踪困难。

### 涉及文件

- `app/evidence/*`
- `app/tools/tool_execution_log_store.py`
- `app/approval/store.py`
- `app/tools/executor.py`

### 建议职责

| 模块 | 职责 |
|---|---|
| `ToolExecutionLogStore` | 工具执行审计主记录 |
| `ApprovalStore` | 审批业务状态和审批事件 |
| `EvidenceStore` | 可供回答/验证引用的证据索引 |

### 验收标准

- 工具执行只写一次主审计。
- Approval event 不重复承担 tool log。
- Evidence 能关联 request_id/trace_id/session_key/tool_name。

## 7. 配置分组整理

### 目标

降低 `settings.py` 持续增长带来的理解成本。

### 为什么要做

当前 settings 已经包含 LLM、Tool Loop、Approval、Knowledge、MCP、Auth、HTTP、Skill 等配置。继续增长会难维护。

### 涉及文件

- `app/config/settings.py`
- `.env.example`
- `tests/test_settings_env.py`

### 建议实现

可以先不拆 dataclass，只在构造和 `.env.example` 中分组：

```text
LLM settings
Tool loop settings
Approval settings
Knowledge settings
MCP settings
Auth settings
Skill settings
Storage settings
```

如果后续继续增长，再拆：

```text
LLMSettings
ToolSettings
ApprovalSettings
AuthSettings
```

### 验收标准

- 默认值不变。
- `.env.example` 不漏字段。
- settings env 测试通过。

## 8. 编码和中文文案清理

### 目标

清理历史 mojibake，提高源码、skill、docs 可读性。

### 为什么要做

当前部分 Python 注释、字符串、SKILL.md 在终端输出中存在中文乱码。企业级交付时，这会严重影响维护和审查。

### 涉及文件

- `app/**/*.py`
- `app/skills/**/*.md`
- `docs/*.md`
- `tests/*`

### 建议实现

分批清理，不和逻辑 refactor 混在一起：

```text
Batch 1: comments/docstrings only
Batch 2: user-facing answer strings
Batch 3: skill metadata/body
Batch 4: test assertions
```

### 验收标准

- 不改业务语义。
- 所有测试通过。
- 用户可见中文文案可读。
- SKILL.md frontmatter 仍能被 SkillCatalog 正确解析。

