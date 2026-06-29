# Query Rewrite、实体与上下文继承

适用场景：增加实体类型、改正正则、调整 alias/覆盖优先级、改变追问识别、修改澄清回复拼接方式，或修改 Query Rewrite 的 LLM 输出。

## 当前真实调用链

```text
original_query
  -> EntityExtractor.extract(source=current_query)
  -> EntityResolver.resolve(current candidates)
  -> summary/recent messages entity extraction and resolve(history)
  -> ConversationWindow
  -> QueryRewriteNode: LLM JSON primary path or rule fallback
  -> resolved EntityBag
  -> build_entity_state_updates()
  -> Graph state: entity_bag + derived entities
```

Graph 入口在 `app/runtime/graph.py:query_rewrite()`；实现位于 `app/query/query_rewrite_node.py`。Intent 节点只读取 rewrite 结果，不应成为第二个实体解析器。

## 不可破坏的状态约束

- `entity_bag` 是唯一事实来源，包含 `value/source/confidence/turn_id/inherited` 等 mention 元数据。
- `entities` 只能来自 `EntityBag.to_compact_dict()`；Graph 中通过 `app/query/entity_resolver.py:build_entity_state_updates()` 同步更新两者。
- 不要写 `{**old_entities, **new_entities}`，不要让 Intent Recognition 或 SkillContextResolver 创建独立实体版本。
- 当前轮 `current_query` 与确定性 rule 候选优先于 LLM、recent turn 和 summary；冲突应澄清而不是静默选值。

## 1. 新增或修改确定性实体

### 必改文件

| 文件 | 修改内容 |
| --- | --- |
| `app/query/entity_patterns.yaml` | 新增 `entity_type`、description、regex、`normalized_type`、sensitive、confidence。Regex capture group 必须能提取值。 |
| `app/query/entity_resolver.py` | 在 `_ALIASES` 增加外部写法到 canonical key 的映射；如果实体具有固定格式或 LLM 候选必须被格式过滤，在 `_FORMAT_PATTERNS` 增加校验。 |
| `app/schemas/entities.py` | 只有需要新 mention 元数据、compact 投影语义或类型能力时才修改；普通字符串实体不需要扩张 schema。 |

### 按场景修改

| 条件 | 文件 | 处理 |
| --- | --- | --- |
| 新实体能代表一个完整新请求 | `app/query/context_reference_policy.yaml` | 加到 `strong_anchor_entity_types`，否则短句可能被错误当成追问。 |
| 新实体存在 alias | `app/query/context_reference_policy.yaml` 和 `entity_resolver.py` | 前者影响追问强锚点判断，后者是 canonical alias；两处保持一致。 |
| 新实体被 Skill 强制要求 | 对应 `SKILL.md` frontmatter | 加到 `required_entities`；不要只在工具函数里补正则。 |
| 新实体用于 Agent 路由加分 | 对应 AgentCard | 加到 `required_entities` 或 `optional_entities`，同时评估是否会使错误 Agent 获得高分。 |
| 新实体要绑定外部 API 字段 | Skill 正文或工具 handler | 内部保持 canonical key；仅在工具参数适配时转换为 `policyNo`、`applySeq` 等外部字段。 |

### 测试

至少补充：`tests/test_entity_patterns_loader.py`、`tests/test_entity_extractor.py`、`tests/test_entity_resolver.py`、`tests/test_entity_bag.py`。实体会跨图流转时还要补 `tests/test_entity_state_sync.py` 和对应 Query Rewrite 测试。

## 2. 修改覆盖、冲突或继承策略

主文件：

- `app/query/entity_resolver.py`：`_SOURCE_PRIORITY`、LLM 最低置信度、格式过滤、同类型冲突与澄清问题。
- `app/query/query_rewrite_node.py`：只负责把 current/history/LLM candidate 交给 resolver，及决定何时允许历史继承；不要把优先级散回 node。

推荐测试场景：当前轮纠正历史值、当前 rule 不被 LLM 覆盖、唯一历史高置信继承、多历史候选澄清、summary 不覆盖 recent/current、低置信 LLM 不污染 canonical bag。对应现有测试重点是 `tests/test_entity_resolver.py`、`tests/test_query_rewrite_entity_inheritance.py`、`tests/test_multi_turn_memory.py`。

## 3. 修改追问、澄清回复与上下文引用

| 文件 | 职责 |
| --- | --- |
| `app/query/context_reference_policy.yaml` | 引用词、弱追问词、序号指代、短句阈值、强锚点类型。 |
| `app/query/context_reference_policy.py` | YAML 的解析、匹配、trace。 |
| `app/query/query_rewrite_node.py` | pending clarification 检测、继承历史实体、构造 clarification reply 独立问题、规则 fallback。 |
| `app/schemas/query_rewrite.py` | 只有输出字段变化时修改；`entities` 会由 `entity_bag` 自动投影。 |

改规则前要分别覆盖三类对话：新请求带强锚点、上一轮澄清后的补参、回答后的上下文追问。不要仅用“上一轮有实体就继承”的规则，这会把多个历史保单错误拼成一个请求。

测试：`tests/test_query_context_reference_policy.py`、`tests/test_query_rewrite.py`、`tests/test_query_rewrite_entity_inheritance.py`、`tests/test_multi_turn_memory.py`、`tests/test_clarification_flow.py`。

## 4. 修改 Query Rewrite LLM 行为

| 文件 | 修改内容 |
| --- | --- |
| `app/prompts/query_rewrite/system.md` | 输出职责、实体不可覆盖规则、追问/澄清定义。 |
| `app/prompts/query_rewrite/user.md` | 输入变量的呈现；当前包含 `original_query`、`current_entities`、`conversation_window`。 |
| `app/llm/output_schemas.py` | 改变 JSON 输出字段时同步修改 `QueryRewriteLLMOutput`。 |
| `app/prompts/manifest.yaml` | 改 Prompt 内容语义时提高 scene version；schema 或 eval suite 改名时同步。 |
| `app/evaluation/prompts/cases/query_rewrite_cases.yaml` | 新增正向、反例、追问和澄清回复 fixture。 |

LLM 输出的 `entities` 与 `inherited_entities` 是候选；`QueryRewriteNode._rewrite_with_llm()` 会经 `EntityResolver` 才生成 canonical bag。不能让 Prompt 要求替代服务端优先级。

## 5. 修改规则 fallback

当 provider 不可用、返回 error、JSON 无法解析或 schema 不合法时，Query Rewrite 走 `_rewrite_with_rules()`。修改 fallback 时只改：

- `app/query/query_rewrite_node.py` 的引用判断、继承与 rewritten query 构造；
- `context_reference_policy.yaml` 的声明式信号；
- 相关测试。

不要把 Intent 关键词、AgentCard 选择逻辑或 Tool 参数规则塞进 Rewrite fallback。

## 完成检查

```bash
uv run pytest tests/test_entity_bag.py tests/test_entity_extractor.py tests/test_entity_resolver.py -q
uv run pytest tests/test_query_rewrite.py tests/test_query_rewrite_entity_inheritance.py tests/test_query_context_reference_policy.py -q
uv run pytest tests/test_entity_state_sync.py tests/test_multi_turn_memory.py -q
```
