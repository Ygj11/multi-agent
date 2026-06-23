# Intent Taxonomy 与 Agent Routing

适用场景：新增/删除/调整 intent、sub_intent；调整意图识别；调整 Agent 候选召回、打分、LLM rerank 或权限拒绝。

## 先分清三层

```text
IntentTaxonomy: 系统认识哪些 intent/sub_intent
AgentCard: 哪个 Agent 能处理哪些 route
Skill: 某 Agent 内怎样处理一个或多个 sub_intent
```

`intent` 不是 Agent 名称，`sub_intent` 也不等于 Skill 名称。一个 Agent 可以处理多个 route；一个 Skill 可以覆盖同一 intent 下多个 sub_intent。

## 1. 新增 Intent/Sub-intent 的必改路径

按顺序修改：

1. `app/config/intent_taxonomy.yaml`：新增顶层 intent 或其 `sub_intents`，并写 `display_name`、description、examples。
2. `app/agents/cards/<agent>.yaml`：在 `supported_routes` 增加完全相同的 `intent: [sub_intent]` 声明；系统开启严格覆盖时，每个 taxonomy route 都必须有 enabled card 覆盖。
3. `app/skills/<agent>/<skill>/SKILL.md`：frontmatter 中设置 `intent`、`sub_intents`，并把 `skill_id` 写入对应 AgentCard `skills`。
4. `app/query/intent_fallback_policy.yaml`：LLM 不可用时仍需识别该意图才增加 rules/keywords；仅 LLM 场景可识别时不要伪造宽泛 fallback。
5. `app/prompts/intent_recognition/*.md`：只有分类边界、字段含义或 prompt 指令变化时调整。
6. `app/evaluation/cases/intent_cases.yaml`：增加合法分类、相邻分类、unknown/澄清 fixture。

启动时 `AppContainer` 会调用 `AgentCardLoader.validate_with_intent_taxonomy()`、`SkillCatalog.validate_with_intent_taxonomy()` 和 card-skill 交叉校验。不要通过关闭 `STRICT_TAXONOMY_ROUTE_COVERAGE` 逃避缺失 route。

## 2. 修改 Intent Recognition 本身

### 真实文件边界

| 文件 | 负责什么 |
| --- | --- |
| `app/query/intent_recognition_node.py` | LLM JSON 调用、taxonomy 合法值检查、规则 fallback 调用；不写 canonical 实体。 |
| `app/query/intent_taxonomy_loader.py` | 读取 taxonomy、提供 `allowed_intents` 和按 intent 分组的合法 `candidate_sub_intents`。 |
| `app/query/intent_fallback_policy.py/.yaml` | LLM 不可用或非法输出时的确定性分类。 |
| `app/llm/output_schemas.py` | `IntentRecognitionLLMOutput` 的 JSON contract。 |
| `app/prompts/intent_recognition/system.md` / `user.md` | 模型的分类指令和输入展示。 |

输入优先级是 `rewritten_query + resolved entities`；`original_query` 和会话窗口只用于理解/审计辅助。不要在此节点重新抽取 `original_query + rewritten_query` 并合并实体。

### 修改后的最低测试

```bash
uv run pytest tests/test_intent_taxonomy_loader.py tests/test_intent_fallback_policy.py -q
uv run pytest tests/test_intent_recognition.py tests/test_intent_recognition_llm_json.py -q
```

## 3. 调整 AgentCard 路由

### AgentCard 是权威声明

文件：`app/agents/cards/*.yaml`；schema：`app/schemas/agent_card.py`；加载/交叉校验：`app/agents/card_loader.py`。

常用字段及真实影响：

| 字段 | 影响位置 |
| --- | --- |
| `supported_routes` | `match_candidates()` 的 intent/sub_intent 主打分，也是 taxonomy 交叉校验依据。 |
| `capabilities`、description、examples | 规则关键词命中与 LLM router 的语义候选信息。 |
| `required_entities` / `optional_entities` | Agent 候选分数与候选缺失实体，不替代 Skill 的精确必填检查。 |
| `private_tools` / `public_tools_allowed` / `mcp_policy` | ToolRegistry 的可见工具集合。 |
| `skills` | card-skill 一致性校验；必须引用存在的 Skill。 |
| `access_policy` | Agent 选择完成后的身份、scope、机构/数据访问检查。 |
| `enabled` | disabled card 不进入候选与严格 coverage。 |

### 调整打分或 rerank 条件

| 目标 | 文件 |
| --- | --- |
| 规则权重、阈值、关键词、澄清文案 | `app/agents/routing_policy.yaml` |
| YAML 解析与 trace | `app/agents/routing_policy.py` |
| 候选召回和打分 | `app/agents/card_loader.py:match_candidates()` |
| Top-K、LLM rerank 触发条件、rule fallback | `app/agents/selection.py` |
| LLM router Prompt / schema | `app/agents/llm_router.py`、`app/prompts/agent_selection/*`、`app/llm/output_schemas.py` |

不要在 LLM router 中让模型发明 Agent 名称。它只能在 `match_candidates()` 的 Top-K 中选择。

### 测试

`tests/test_agent_card_loader.py`、`tests/test_agent_routing_policy.py`、`tests/test_agent_selection_hybrid_router.py`、`tests/test_agent_routing_policy.py`、`tests/test_agent_card_loader.py`。route 改动还应运行 `tests/test_skill_selection_end_to_end.py`。

## 4. 与 Query Rewrite 的接口

Agent selection 读取 `rewritten_query`、intent、sub_intent、`entities` 和 `is_follow_up`，不直接拿完整 ConversationWindow 做全文召回。若路由因为缺实体错误，不要先改 AgentCard；先检查 [01-query-rewrite-and-entities.md](01-query-rewrite-and-entities.md) 的实体解析与继承是否正确。
